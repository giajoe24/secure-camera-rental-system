"""
SQLite データベース処理

このファイルの役割:
    ・テーブルの作成
    ・利用者 / カメラ / 貸出記録 / 解錠ログ の読み書き
    ・トランザクション(成功なら commit、失敗なら rollback)
    ・接続を必ず close すること

【接続の扱いについて(WinError 32 対策)】
    sqlite3 の「with sqlite3.connect(...) as connection:」は、
    commit / rollback はしてくれますが、接続を close しません。
    これが「一時DBを削除しようとしたら WinError 32」の典型的な原因です。

    そこで、このクラスでは _open_connection() の finally で
    必ず connection.close() を呼ぶようにしています。
    また、開いている接続の数を open_connection_count で数えておき、
    テストで「すべて閉じられたか」を確認できるようにしています。

【トランザクションの方針】
    ・1回の操作 = 1回の接続 = 1回のトランザクション
    ・書き込みは「BEGIN IMMEDIATE」で開始します。
      これは「書き込みロックを最初に取る」指定で、
      確認(SELECT)してから書き込む(UPDATE/INSERT)までの間に、
      別の処理に割り込まれないようにするためです。
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from camera_rental import errors
from camera_rental.models import (
    CAMERA_STATUS_AVAILABLE,
    CAMERA_STATUS_LABELS,
    CAMERA_STATUS_MAINTENANCE,
    CAMERA_STATUS_RENTED,
    END_REASON_LABELS,
    END_REASON_RETURNED,
    Camera,
    CameraStatusRow,
    Rental,
    User,
    datetime_to_text,
    text_to_datetime,
)

logger = logging.getLogger(__name__)


# データベースの構造のバージョン
# 将来テーブルを変更するときは、この番号を上げて移行処理を書きます。
SCHEMA_VERSION = 1


# --------------------------------------------------
# テーブル定義
# --------------------------------------------------
# 各テーブルの意図は docs/DESIGN.md の「6. DB設計」に書いています。

CREATE_TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id               INTEGER PRIMARY KEY,
        employee_number  TEXT    NOT NULL UNIQUE,
        name             TEXT    NOT NULL,
        card_id          TEXT    NOT NULL UNIQUE,
        is_active        INTEGER NOT NULL DEFAULT 1
                                 CHECK (is_active IN (0, 1)),
        created_at       TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cameras (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE,
        status      TEXT NOT NULL DEFAULT 'available'
                         CHECK (status IN ('available', 'rented', 'maintenance')),
        created_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rentals (
        id            INTEGER PRIMARY KEY,
        user_id       INTEGER NOT NULL
                              REFERENCES users (id) ON DELETE RESTRICT,
        camera_id     INTEGER NOT NULL
                              REFERENCES cameras (id) ON DELETE RESTRICT,
        rental_hours  INTEGER NOT NULL CHECK (rental_hours > 0),
        rented_at     TEXT    NOT NULL,
        due_at        TEXT    NOT NULL,
        returned_at   TEXT,
        end_reason    TEXT
                      CHECK (end_reason IN (
                          'returned',
                          'cancelled_unlock_failed',
                          'admin_force_return'
                      )),

        -- 「返却日時」と「終了理由」は、両方空か、両方入っているかのどちらか
        CHECK (
            (returned_at IS NULL AND end_reason IS NULL)
            OR
            (returned_at IS NOT NULL AND end_reason IS NOT NULL)
        )
    )
    """,
    # 二重貸出防止の最終防衛線:
    #   「未返却(returned_at IS NULL)の貸出」は、カメラ1台につき1件まで
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_rentals_open_camera
        ON rentals (camera_id)
        WHERE returned_at IS NULL
    """,
    # 未返却での再貸出防止の最終防衛線:
    #   「未返却の貸出」は、利用者1人につき1件まで
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_rentals_open_user
        ON rentals (user_id)
        WHERE returned_at IS NULL
    """,
    # 履歴を新しい順に並べるための索引
    """
    CREATE INDEX IF NOT EXISTS ix_rentals_rented_at
        ON rentals (rented_at)
    """,
    # 解錠の成功・失敗を残すログ(DB記録後の解錠失敗を管理者が追えるように)
    """
    CREATE TABLE IF NOT EXISTS unlock_logs (
        id          INTEGER PRIMARY KEY,
        rental_id   INTEGER
                            REFERENCES rentals (id) ON DELETE SET NULL,
        action      TEXT    NOT NULL
                            CHECK (action IN ('borrow', 'return', 'retry', 'admin_test')),
        result      TEXT    NOT NULL
                            CHECK (result IN ('success', 'failed')),
        message     TEXT    NOT NULL DEFAULT '',
        created_at  TEXT    NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_unlock_logs_created_at
        ON unlock_logs (created_at)
    """,
]


# 貸出記録を、利用者名・カメラ名と一緒に取り出す共通の SELECT 文
RENTAL_SELECT_SQL = """
    SELECT
        rentals.id,
        rentals.user_id,
        rentals.camera_id,
        rentals.rental_hours,
        rentals.rented_at,
        rentals.due_at,
        rentals.returned_at,
        rentals.end_reason,
        users.employee_number,
        users.name AS user_name,
        cameras.name AS camera_name
    FROM rentals
    JOIN users
        ON users.id = rentals.user_id
    JOIN cameras
        ON cameras.id = rentals.camera_id
"""


def normalize_card_id(card_id):
    """
    カードIDの表記ゆれをそろえる

    例: "01 2e:4c-aa" → "012E4CAA"
    ・前後の空白を削除
    ・区切り文字(空白, コロン, ハイフン)を削除
    ・英字を大文字にそろえる
    """
    text = str(card_id).strip()
    for separator in [" ", ":", "-"]:
        text = text.replace(separator, "")
    return text.upper()


class Database:
    """SQLite への読み書きをまとめたクラス"""

    def __init__(self, database_path):
        self.database_path = Path(database_path)

        # 現在開いている接続の数(テストで「閉じ忘れがないか」を確認するため)
        self.open_connection_count = 0

    # ==================================================
    # 接続とトランザクション
    # ==================================================

    @contextmanager
    def _open_connection(self):
        """
        接続を開き、使い終わったら必ず閉じる

        使い方:
            with self._open_connection() as connection:
                connection.execute(...)
        """
        try:
            # isolation_level=None:
            #   Python が自動で BEGIN を発行しないようにする設定です。
            #   トランザクションの開始は _transaction() で明示的に行います。
            connection = sqlite3.connect(
                self.database_path,
                timeout=5,
                isolation_level=None,
            )
        except sqlite3.Error as error:
            logger.exception("データベースを開けませんでした: %s", self.database_path)
            raise errors.DatabaseError(detail=str(error)) from error

        self.open_connection_count += 1

        try:
            # 列名でアクセスできるようにする(row["name"] のように書ける)
            connection.row_factory = sqlite3.Row

            # SQLite の外部キー制約は「接続ごと」に有効化が必要
            connection.execute("PRAGMA foreign_keys = ON")

            yield connection
        finally:
            # 成功しても失敗しても、必ず閉じる
            connection.close()
            self.open_connection_count -= 1

    @contextmanager
    def _transaction(self):
        """
        書き込み用のトランザクション

        ブロック内が最後まで成功したら commit、
        途中で例外が起きたら rollback します。
        """
        with self._open_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _run_read(self, function):
        """
        読み取り処理を実行し、SQLite のエラーを DatabaseError に変換する

        function には「connection を受け取って結果を返す関数」を渡します。
        """
        try:
            with self._open_connection() as connection:
                return function(connection)
        except sqlite3.Error as error:
            logger.exception("データベースの読み取りに失敗しました")
            raise errors.DatabaseError(
                title="データを読み込めませんでした",
                user_message="記録を読み込めませんでした。管理者に連絡してください。",
                detail=str(error),
            ) from error

    # ==================================================
    # 初期化
    # ==================================================

    def initialize(self):
        """データベースファイルとテーブルを作成する(既にあれば何もしない)"""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with self._open_connection() as connection:
                current_version = connection.execute("PRAGMA user_version").fetchone()[0]

                if current_version > SCHEMA_VERSION:
                    raise errors.DatabaseError(
                        title="データベースのバージョンが新しすぎます",
                        user_message="このプログラムより新しい形式のデータベースです。管理者に連絡してください。",
                        detail=f"user_version={current_version}",
                    )

                connection.execute("BEGIN IMMEDIATE")
                try:
                    for statement in CREATE_TABLE_STATEMENTS:
                        connection.execute(statement)
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                except BaseException:
                    connection.rollback()
                    raise
                else:
                    connection.commit()
        except sqlite3.Error as error:
            logger.exception("データベースの初期化に失敗しました")
            raise errors.DatabaseError(detail=str(error)) from error

        logger.info("データベースを準備しました: %s", self.database_path)

    def list_table_names(self):
        """作成済みのテーブル名を返す(テスト・確認用)"""

        def read(connection):
            rows = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                ORDER BY name
                """
            ).fetchall()
            return [row["name"] for row in rows]

        return self._run_read(read)

    # ==================================================
    # 利用者
    # ==================================================

    def add_user(self, employee_number, name, card_id, created_at, is_active=True):
        """利用者を登録する"""
        employee_number = str(employee_number).strip()
        name = str(name).strip()
        card_id = normalize_card_id(card_id)

        if not employee_number or not name or not card_id:
            raise errors.CameraRentalError(
                title="利用者を登録できません",
                user_message="社員番号・氏名・カードIDをすべて入力してください。",
            )

        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO users (
                        employee_number,
                        name,
                        card_id,
                        is_active,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        employee_number,
                        name,
                        card_id,
                        1 if is_active else 0,
                        datetime_to_text(created_at),
                    ),
                )
                new_user_id = cursor.lastrowid
        except sqlite3.IntegrityError as error:
            # UNIQUE 制約違反 = 社員番号 または カードID が重複
            raise errors.DuplicateUserError(detail=str(error)) from error
        except sqlite3.Error as error:
            logger.exception("利用者の登録に失敗しました")
            raise errors.DatabaseError(detail=str(error)) from error

        logger.info("利用者を登録しました: 社員番号=%s", employee_number)
        return User(
            id=new_user_id,
            employee_number=employee_number,
            name=name,
            card_id=card_id,
            is_active=is_active,
        )

    def find_user_by_card_id(self, card_id):
        """カードIDから利用者を探す(見つからなければ None)"""
        normalized_card_id = normalize_card_id(card_id)

        def read(connection):
            row = connection.execute(
                """
                SELECT id, employee_number, name, card_id, is_active
                FROM users
                WHERE card_id = ?
                """,
                (normalized_card_id,),
            ).fetchone()
            return self._row_to_user(row)

        return self._run_read(read)

    def find_user_by_employee_number(self, employee_number):
        """社員番号から利用者を探す(見つからなければ None)"""

        def read(connection):
            row = connection.execute(
                """
                SELECT id, employee_number, name, card_id, is_active
                FROM users
                WHERE employee_number = ?
                """,
                (str(employee_number).strip(),),
            ).fetchone()
            return self._row_to_user(row)

        return self._run_read(read)

    def list_users(self):
        """利用者を社員番号順にすべて返す"""

        def read(connection):
            rows = connection.execute(
                """
                SELECT id, employee_number, name, card_id, is_active
                FROM users
                ORDER BY employee_number
                """
            ).fetchall()
            return [self._row_to_user(row) for row in rows]

        return self._run_read(read)

    def set_user_active(self, employee_number, is_active):
        """利用者の利用可否を変更する"""
        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE users
                    SET is_active = ?
                    WHERE employee_number = ?
                    """,
                    (1 if is_active else 0, str(employee_number).strip()),
                )
                if cursor.rowcount == 0:
                    raise errors.UserNotFoundError(detail=f"社員番号={employee_number}")
        except sqlite3.Error as error:
            logger.exception("利用者の更新に失敗しました")
            raise errors.DatabaseError(detail=str(error)) from error

    @staticmethod
    def _row_to_user(row):
        if row is None:
            return None
        return User(
            id=row["id"],
            employee_number=row["employee_number"],
            name=row["name"],
            card_id=row["card_id"],
            is_active=bool(row["is_active"]),
        )

    # ==================================================
    # カメラ
    # ==================================================

    def add_camera(self, name, created_at):
        """カメラを登録する(登録直後は「貸出可能」)"""
        name = str(name).strip()
        if not name:
            raise errors.CameraRentalError(
                title="カメラを登録できません",
                user_message="カメラ名を入力してください。",
            )

        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO cameras (name, status, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (name, CAMERA_STATUS_AVAILABLE, datetime_to_text(created_at)),
                )
                new_camera_id = cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise errors.DuplicateCameraError(detail=str(error)) from error
        except sqlite3.Error as error:
            logger.exception("カメラの登録に失敗しました")
            raise errors.DatabaseError(detail=str(error)) from error

        logger.info("カメラを登録しました: %s", name)
        return Camera(id=new_camera_id, name=name, status=CAMERA_STATUS_AVAILABLE)

    def get_camera(self, camera_id):
        """IDからカメラを取得する(見つからなければ None)"""

        def read(connection):
            row = connection.execute(
                """
                SELECT id, name, status
                FROM cameras
                WHERE id = ?
                """,
                (camera_id,),
            ).fetchone()
            return self._row_to_camera(row)

        return self._run_read(read)

    def list_cameras(self):
        """カメラをID順にすべて返す"""

        def read(connection):
            rows = connection.execute(
                """
                SELECT id, name, status
                FROM cameras
                ORDER BY id
                """
            ).fetchall()
            return [self._row_to_camera(row) for row in rows]

        return self._run_read(read)

    def list_available_cameras(self):
        """貸出可能なカメラだけを返す"""
        all_cameras = self.list_cameras()
        return [camera for camera in all_cameras if camera.is_available]

    def set_camera_status(self, camera_id, new_status):
        """
        カメラの状態を「貸出可能」または「点検中」に変更する(管理用)

        「貸出中」への変更は貸出処理だけが行うので、ここでは受け付けません。
        また、貸出中のカメラは返却されるまで状態を変更できません。
        """
        if new_status not in (CAMERA_STATUS_AVAILABLE, CAMERA_STATUS_MAINTENANCE):
            raise errors.CameraRentalError(
                title="状態を変更できません",
                user_message="設定できる状態は「貸出可能」か「点検中」だけです。",
            )

        try:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT status FROM cameras WHERE id = ?",
                    (camera_id,),
                ).fetchone()

                if row is None:
                    raise errors.CameraNotFoundError(detail=f"camera_id={camera_id}")

                if row["status"] == CAMERA_STATUS_RENTED:
                    raise errors.CameraRentalError(
                        title="状態を変更できません",
                        user_message="貸出中のカメラは、返却されるまで状態を変更できません。",
                    )

                connection.execute(
                    """
                    UPDATE cameras
                    SET status = ?
                    WHERE id = ?
                    """,
                    (new_status, camera_id),
                )
        except sqlite3.Error as error:
            logger.exception("カメラの状態変更に失敗しました")
            raise errors.DatabaseError(detail=str(error)) from error

        logger.info(
            "カメラの状態を変更しました: camera_id=%s → %s",
            camera_id,
            CAMERA_STATUS_LABELS[new_status],
        )

    @staticmethod
    def _row_to_camera(row):
        if row is None:
            return None
        return Camera(id=row["id"], name=row["name"], status=row["status"])

    # ==================================================
    # 貸出・返却
    # ==================================================

    def create_rental(self, user_id, camera_id, rental_hours, rented_at):
        """
        貸出を記録する

        1つのトランザクションの中で、次をまとめて行います。
            1. 利用者が利用可能か確認
            2. 利用者に未返却の貸出がないか確認
            3. カメラが「貸出可能」か確認し、「貸出中」へ変更
            4. 貸出記録を追加
        途中で1つでも失敗したら、すべて取り消されます(rollback)。
        """
        due_at = rented_at + timedelta(hours=rental_hours)

        try:
            with self._transaction() as connection:
                # --- 1. 利用者の確認 ---
                user_row = connection.execute(
                    "SELECT is_active FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()

                if user_row is None:
                    raise errors.UserNotFoundError(detail=f"user_id={user_id}")
                if not user_row["is_active"]:
                    raise errors.UserDisabledError()

                # --- 2. 未返却の貸出がないか ---
                open_rental_row = connection.execute(
                    """
                    SELECT id
                    FROM rentals
                    WHERE user_id = ?
                      AND returned_at IS NULL
                    """,
                    (user_id,),
                ).fetchone()

                if open_rental_row is not None:
                    raise errors.UserHasActiveRentalError()

                # --- 3. カメラを「貸出可能 → 貸出中」へ ---
                # WHERE に status = 'available' を入れておくことで、
                # 「貸出可能だったときだけ」更新されます。
                update_cursor = connection.execute(
                    """
                    UPDATE cameras
                    SET status = ?
                    WHERE id = ?
                      AND status = ?
                    """,
                    (CAMERA_STATUS_RENTED, camera_id, CAMERA_STATUS_AVAILABLE),
                )

                if update_cursor.rowcount == 0:
                    camera_exists = connection.execute(
                        "SELECT id FROM cameras WHERE id = ?",
                        (camera_id,),
                    ).fetchone()
                    if camera_exists is None:
                        raise errors.CameraNotFoundError(detail=f"camera_id={camera_id}")
                    raise errors.CameraNotAvailableError()

                # --- 4. 貸出記録を追加 ---
                insert_cursor = connection.execute(
                    """
                    INSERT INTO rentals (
                        user_id,
                        camera_id,
                        rental_hours,
                        rented_at,
                        due_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        camera_id,
                        rental_hours,
                        datetime_to_text(rented_at),
                        datetime_to_text(due_at),
                    ),
                )
                new_rental_id = insert_cursor.lastrowid

        except sqlite3.IntegrityError as error:
            # 上の確認をすり抜けて、部分UNIQUEインデックスに引っかかった場合
            # (通常は起きない、最終防衛線)。メッセージで原因を見分ける。
            #   "UNIQUE constraint failed: rentals.camera_id" → カメラの二重貸出
            #   "UNIQUE constraint failed: rentals.user_id"   → 利用者の未返却
            # それ以外(CHECK 制約違反など)は保存失敗として扱う。
            error_text = str(error)
            logger.warning("貸出の制約に違反しました: %s", error_text)
            if "rentals.camera_id" in error_text:
                raise errors.CameraNotAvailableError(detail=error_text) from error
            if "rentals.user_id" in error_text:
                raise errors.UserHasActiveRentalError(detail=error_text) from error
            raise errors.DatabaseError(detail=error_text) from error
        except sqlite3.Error as error:
            logger.exception("貸出の記録に失敗しました")
            raise errors.DatabaseError(detail=str(error)) from error

        logger.info(
            "貸出を記録しました: rental_id=%s user_id=%s camera_id=%s %s時間",
            new_rental_id,
            user_id,
            camera_id,
            rental_hours,
        )
        return self.get_rental(new_rental_id)

    def finish_rental(self, rental_id, finished_at, end_reason=END_REASON_RETURNED,
                      camera_status_after=CAMERA_STATUS_AVAILABLE):
        """
        貸出を終了する(返却・取消・管理者返却)

        1つのトランザクションで、
            1. 貸出記録に返却日時と終了理由を書く
            2. カメラの状態を戻す(通常は「貸出可能」)
        を行います。
        """
        if end_reason not in END_REASON_LABELS:
            raise ValueError(f"不明な終了理由です: {end_reason}")

        try:
            with self._transaction() as connection:
                rental_row = connection.execute(
                    """
                    SELECT id, camera_id, returned_at
                    FROM rentals
                    WHERE id = ?
                    """,
                    (rental_id,),
                ).fetchone()

                if rental_row is None:
                    raise errors.RentalNotFoundError(detail=f"rental_id={rental_id}")
                if rental_row["returned_at"] is not None:
                    raise errors.NoActiveRentalError(
                        title="この貸出はすでに返却済みです",
                        user_message="この貸出は、すでに返却処理が完了しています。",
                    )

                connection.execute(
                    """
                    UPDATE rentals
                    SET returned_at = ?,
                        end_reason = ?
                    WHERE id = ?
                    """,
                    (datetime_to_text(finished_at), end_reason, rental_id),
                )

                connection.execute(
                    """
                    UPDATE cameras
                    SET status = ?
                    WHERE id = ?
                    """,
                    (camera_status_after, rental_row["camera_id"]),
                )
        except sqlite3.Error as error:
            logger.exception("返却の記録に失敗しました")
            raise errors.DatabaseError(detail=str(error)) from error

        logger.info("貸出を終了しました: rental_id=%s 理由=%s", rental_id, end_reason)
        return self.get_rental(rental_id)

    def get_rental(self, rental_id):
        """IDから貸出記録を取得する(見つからなければ None)"""

        def read(connection):
            row = connection.execute(
                RENTAL_SELECT_SQL + " WHERE rentals.id = ?",
                (rental_id,),
            ).fetchone()
            return self._row_to_rental(row)

        return self._run_read(read)

    def find_active_rental_by_user(self, user_id):
        """利用者の未返却の貸出を探す(なければ None)"""

        def read(connection):
            row = connection.execute(
                RENTAL_SELECT_SQL
                + """
                WHERE rentals.user_id = ?
                  AND rentals.returned_at IS NULL
                """,
                (user_id,),
            ).fetchone()
            return self._row_to_rental(row)

        return self._run_read(read)

    def list_rentals(self, limit=None):
        """貸出履歴を新しい順に返す(limit が None なら全件)"""

        def read(connection):
            sql = RENTAL_SELECT_SQL + " ORDER BY rentals.rented_at DESC, rentals.id DESC"
            parameters = ()
            if limit is not None:
                sql += " LIMIT ?"
                parameters = (limit,)
            rows = connection.execute(sql, parameters).fetchall()
            return [self._row_to_rental(row) for row in rows]

        return self._run_read(read)

    def list_camera_statuses(self):
        """カメラごとの状態と、貸出中なら貸出記録を返す(ホーム画面の一覧用)"""

        def read(connection):
            camera_rows = connection.execute(
                """
                SELECT id, name, status
                FROM cameras
                ORDER BY id
                """
            ).fetchall()

            open_rental_rows = connection.execute(
                RENTAL_SELECT_SQL + " WHERE rentals.returned_at IS NULL"
            ).fetchall()

            open_rentals_by_camera = {}
            for row in open_rental_rows:
                rental = self._row_to_rental(row)
                open_rentals_by_camera[rental.camera_id] = rental

            status_rows = []
            for camera_row in camera_rows:
                camera = self._row_to_camera(camera_row)
                rental = open_rentals_by_camera.get(camera.id)
                status_rows.append(CameraStatusRow(camera=camera, rental=rental))
            return status_rows

        return self._run_read(read)

    @staticmethod
    def _row_to_rental(row):
        if row is None:
            return None
        return Rental(
            id=row["id"],
            user_id=row["user_id"],
            camera_id=row["camera_id"],
            rental_hours=row["rental_hours"],
            rented_at=text_to_datetime(row["rented_at"]),
            due_at=text_to_datetime(row["due_at"]),
            returned_at=text_to_datetime(row["returned_at"]),
            end_reason=row["end_reason"],
            employee_number=row["employee_number"],
            user_name=row["user_name"],
            camera_name=row["camera_name"],
        )

    # ==================================================
    # 解錠ログ
    # ==================================================

    def add_unlock_log(self, action, result, created_at, rental_id=None, message=""):
        """
        解錠の結果を記録する

        ※ このログの保存に失敗しても、貸出・返却そのものは
          取り消さない方針です(呼び出し側で警告ログだけ残します)。
        """
        try:
            with self._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO unlock_logs (
                        rental_id,
                        action,
                        result,
                        message,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (rental_id, action, result, message, datetime_to_text(created_at)),
                )
        except sqlite3.Error as error:
            logger.exception("解錠ログの保存に失敗しました")
            raise errors.DatabaseError(detail=str(error)) from error

    def list_unlock_logs(self, limit=50):
        """解錠ログを新しい順に返す(辞書のリスト)"""

        def read(connection):
            rows = connection.execute(
                """
                SELECT id, rental_id, action, result, message, created_at
                FROM unlock_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

        return self._run_read(read)

    # ==================================================
    # デモデータ・点検
    # ==================================================

    def seed_demo_data(self, demo_users, demo_cameras, disabled_employee_numbers, created_at):
        """
        デモ用の利用者とカメラを登録する

        すでに登録済みのデータは飛ばすので、何度呼んでも大丈夫です。
        """
        for employee_number, name, card_id in demo_users:
            if self.find_user_by_employee_number(employee_number) is not None:
                continue
            is_active = employee_number not in disabled_employee_numbers
            self.add_user(employee_number, name, card_id, created_at, is_active=is_active)

        registered_names = [camera.name for camera in self.list_cameras()]
        for camera_name in demo_cameras:
            if camera_name in registered_names:
                continue
            self.add_camera(camera_name, created_at)

    def find_inconsistencies(self):
        """
        カメラの状態と貸出記録の食い違いを探す(管理用の点検機能)

        例:
            ・カメラが「貸出中」なのに未返却の貸出記録がない
            ・未返却の貸出記録があるのにカメラが「貸出中」でない
        通常は同じトランザクションで更新しているので起きませんが、
        DBを手で編集した場合などに備えています。
        """
        problems = []
        for status_row in self.list_camera_statuses():
            camera = status_row.camera
            has_open_rental = status_row.rental is not None

            if camera.status == CAMERA_STATUS_RENTED and not has_open_rental:
                problems.append(f"{camera.name}: 状態は貸出中ですが、未返却の貸出記録がありません")
            if camera.status != CAMERA_STATUS_RENTED and has_open_rental:
                problems.append(
                    f"{camera.name}: 未返却の貸出記録がありますが、状態が「{camera.status_label}」です"
                )
        return problems
