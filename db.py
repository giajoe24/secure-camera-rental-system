# DB(SQLite)の読み書き
#
# users: 利用者
# logs : 操作の記録。追記するだけで、上書き・削除はしない
#
# 1回の貸出・返却で 2 行書く
#   解錠したとき          step = "解錠"
#   扉が閉まって施錠したとき step = "完了"
#   (扉が開かれなかったとき step = "取り消し")
# カメラが貸出中かどうかは「最後の完了の行が貸出か返却か」で決める。
# 扉が閉まるまでは完了にしないので、扉を開けただけの記録が残っても貸出中にはならない。

import sqlite3
from datetime import datetime
from pathlib import Path

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

BORROW = "貸出"
RETURN = "返却"

UNLOCK = "解錠"
DONE = "完了"
CANCEL = "取り消し"


class RentalError(Exception):
    # 画面にそのまま出すエラー
    def __init__(self, title, message=""):
        super().__init__(title)
        self.title = title
        self.message = message


def normalize_card_id(card_id):
    # "01:2e:4c" も "012E4C" も同じカードにする
    return card_id.replace(":", "").replace(" ", "").upper()


def parse_time(text):
    return datetime.strptime(text, TIME_FORMAT)


def minutes_past(due_at, at_time):
    # 返却予定を何分過ぎたか(過ぎていなければ 0)
    seconds = (at_time - due_at).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60)


class Database:
    def __init__(self, path):
        self.path = Path(path)

    def open(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row  # row["name"] のように列名で取れるようにする
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # よく使う形をまとめたもの。どれも最後に必ず close する
    # (close しないと Windows で DB ファイルが消せなくなる)

    def select_one(self, sql, params=()):
        conn = self.open()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    def select_all(self, sql, params=()):
        conn = self.open()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def execute(self, sql, params=()):
        # 書き込み1回分。変わった行の数を返す
        conn = self.open()
        try:
            with conn:  # 成功したら commit、エラーなら rollback
                cursor = conn.execute(sql, params)
            return cursor.rowcount
        finally:
            conn.close()

    def create_tables(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY,
                employee_number TEXT NOT NULL UNIQUE,
                name            TEXT NOT NULL,
                card_id         TEXT NOT NULL UNIQUE
            )
        """)
        self.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id      INTEGER PRIMARY KEY,
                time    TEXT NOT NULL,
                action  TEXT NOT NULL,   -- 貸出 / 返却
                step    TEXT NOT NULL,   -- 解錠 / 完了 / 取り消し
                user_id INTEGER NOT NULL REFERENCES users (id),   -- 操作した人
                due_at  TEXT,            -- 返却予定(貸出のときだけ)
                note    TEXT NOT NULL DEFAULT ''
            )
        """)

    # ---- 利用者 ----

    def add_user(self, employee_number, name, card_id):
        try:
            self.execute(
                "INSERT INTO users (employee_number, name, card_id) VALUES (?, ?, ?)",
                (employee_number, name, normalize_card_id(card_id)),
            )
        except sqlite3.IntegrityError:
            raise RentalError("登録できません", "社員番号かカードIDがすでに登録されています。")

    def list_users(self):
        return self.select_all("SELECT * FROM users ORDER BY employee_number")

    def find_user_by_card(self, card_id):
        return self.select_one("SELECT * FROM users WHERE card_id = ?", (normalize_card_id(card_id),))

    # ---- 記録を書く ----

    def add_log(self, conn, action, step, user, due_at=None, note="", now=None):
        if now is None:
            now = datetime.now()
        due_text = None
        if due_at is not None:
            due_text = due_at.strftime(TIME_FORMAT)
        conn.execute(
            "INSERT INTO logs (time, action, step, user_id, due_at, note) VALUES (?, ?, ?, ?, ?, ?)",
            (now.strftime(TIME_FORMAT), action, step, user["id"], due_text, note),
        )

    def start(self, action, user, open_door, due_at=None, now=None):
        # 「解錠」を記録して扉を開ける。
        # 記録に失敗したら扉は開けない。扉が開かなかったら記録は取り消し(rollback)。
        conn = self.open()
        try:
            with conn:
                rental = self.find_current_rental(conn)
                if action == BORROW and rental is not None:
                    raise RentalError("いまは借りられません", "ほかの人が借りています。")
                if action == RETURN and rental is None:
                    raise RentalError("返却するカメラがありません", "カメラは貸し出されていません。")

                self.add_log(conn, action, UNLOCK, user, due_at, now=now)
                open_door()
        finally:
            conn.close()

    def finish(self, action, user, due_at=None, now=None):
        # 扉が閉まって施錠したら呼ぶ
        conn = self.open()
        try:
            with conn:
                self.add_log(conn, action, DONE, user, due_at, now=now)
        finally:
            conn.close()

    def cancel(self, action, user, note, now=None):
        # 扉が開かれなかったときなど
        conn = self.open()
        try:
            with conn:
                self.add_log(conn, action, CANCEL, user, note=note, now=now)
        finally:
            conn.close()

    def close_unfinished(self):
        # 起動したときに呼ぶ。完了も取り消しもされていない解錠が最後に残っていたら
        # (途中で電源が切れたなど)、取り消しの行を足しておく
        last = self.select_one("SELECT * FROM logs ORDER BY id DESC LIMIT 1")
        if last is None or last["step"] != UNLOCK:
            return None
        user = {"id": last["user_id"]}
        self.cancel(last["action"], user, "途中で止まったため(再起動)")
        return last

    # ---- 記録を読む ----

    def find_current_rental(self, conn):
        # 貸出中ならその貸出の行(借りた人の名前つき)、貸出中でなければ None
        last = conn.execute("""
            SELECT logs.*, users.name, users.employee_number
            FROM logs JOIN users ON users.id = logs.user_id
            WHERE logs.step = '完了' AND logs.action IN ('貸出', '返却')
            ORDER BY logs.id DESC LIMIT 1
        """).fetchone()
        if last is None or last["action"] != BORROW:
            return None

        rental = dict(last)
        rental["rented_at"] = last["time"]

        # 延長(追加機能)の行があれば、いちばん新しい返却予定を使う
        later_due = conn.execute(
            "SELECT due_at FROM logs WHERE id > ? AND step = '完了' AND due_at IS NOT NULL ORDER BY id DESC LIMIT 1",
            (last["id"],),
        ).fetchone()
        if later_due is not None:
            rental["due_at"] = later_due["due_at"]
        return rental

    def current_rental(self):
        conn = self.open()
        try:
            return self.find_current_rental(conn)
        finally:
            conn.close()

    def list_logs(self):
        # 記録をそのまま全部(新しい順)
        return self.select_all("""
            SELECT logs.*, users.employee_number, users.name
            FROM logs JOIN users ON users.id = logs.user_id
            ORDER BY logs.id DESC
        """)

    def list_rentals(self):
        # 完了した貸出と返却を組にした一覧(新しい順)
        # それぞれ 借りた人、貸出日時、返却予定、返した人、返却日時(返していなければ None)
        rows = self.select_all("""
            SELECT logs.*, users.employee_number, users.name
            FROM logs JOIN users ON users.id = logs.user_id
            WHERE logs.step = '完了'
            ORDER BY logs.id
        """)

        rentals = []
        rental = None
        for row in rows:
            if row["action"] == BORROW:
                rental = {
                    "borrower_number": row["employee_number"],
                    "borrower_name": row["name"],
                    "rented_at": row["time"],
                    "due_at": row["due_at"],
                    "returner_number": None,
                    "returner_name": None,
                    "returned_at": None,
                }
                rentals.append(rental)
            elif row["action"] == RETURN and rental is not None:
                rental["returner_number"] = row["employee_number"]
                rental["returner_name"] = row["name"]
                rental["returned_at"] = row["time"]
                rental = None
            elif rental is not None and row["due_at"] is not None:
                rental["due_at"] = row["due_at"]   # 延長(追加機能)

        rentals.reverse()
        return rentals
