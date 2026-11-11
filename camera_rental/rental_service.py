"""
貸出・返却の業務処理

GUI(画面)とデータベース・電磁ロックの「間」に立つクラスです。

    画面 → RentalService → Database(記録)
                         → LockController(解錠)

【いちばん大事なルール】
    1. まず SQLite に記録する
    2. 記録に成功したときだけ、電磁ロックを解錠する
    3. 記録に失敗したら、解錠しない(例外をそのまま画面へ返す)

    この順番をこのクラスの中だけで守ることで、
    画面側のコードが間違った順番で呼んでしまう事故を防ぎます。

【DB記録後に解錠へ失敗した場合】
    ・解錠ログ(unlock_logs)に「失敗」を記録する
    ・画面には「記録は済んだが扉が開かなかった」ことと受付番号を表示する
    ・貸出時  : 「再試行」または「貸出を取り消す」を選べる
    ・返却時  : カメラを自動的に「点検中」にする
               (カメラが保管庫に戻っていない可能性があるため、
                次の人に貸し出されないようにする)
               「再試行」で解錠できたら「貸出可能」に戻す

【施錠センサー(LE-53 のカムスイッチ)】
    設定で有効にした場合だけ、扉が閉まって施錠されたかを読み取れます。
    センサーは補助の機能なので、使えなくても貸出・返却は止めません。
"""

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from camera_rental import errors
from camera_rental.models import (
    CAMERA_STATUS_AVAILABLE,
    CAMERA_STATUS_MAINTENANCE,
    END_REASON_ADMIN,
    END_REASON_CANCELLED,
    format_for_display,
)
from camera_rental.hardware.lock_sensor import LOCK_STATE_UNKNOWN, NoLockSensor

logger = logging.getLogger(__name__)


# 解錠の目的(ログに残す action の値と同じ)
PURPOSE_BORROW = "borrow"
PURPOSE_RETURN = "return"

# 再試行のログに残す「何の再試行か」
RETRY_PURPOSE_LABELS = {
    PURPOSE_BORROW: "貸出の再試行",
    PURPOSE_RETURN: "返却の再試行",
}


@dataclass
class OperationResult:
    """貸出・返却・再解錠の結果"""

    # 対象の貸出記録
    rental: object

    # 貸出 or 返却
    purpose: str

    # 解錠に成功したか
    unlocked: bool

    # 解錠に失敗した場合のエラー(成功時は None)
    unlock_error: errors.UnlockError | None = None


class RentalService:
    """貸出・返却の手続きをまとめたクラス"""

    def __init__(
        self,
        database,
        lock_controller,
        rental_hours_options,
        unlock_seconds,
        export_directory,
        clock=datetime.now,
        lock_sensor=None,
    ):
        self.database = database
        self.lock_controller = lock_controller

        # 施錠センサー(指定がなければ「使わない」)
        self.lock_sensor = lock_sensor if lock_sensor is not None else NoLockSensor()
        self.rental_hours_options = list(rental_hours_options)
        self.unlock_seconds = unlock_seconds
        self.export_directory = Path(export_directory)

        # 現在時刻を返す関数(テストでは固定の時刻を返す関数に差し替える)
        self._clock = clock

    def now(self):
        """現在時刻(秒より細かい部分は切り捨て)"""
        return self._clock().replace(microsecond=0)

    # ==================================================
    # 事前確認
    # ==================================================

    def ensure_lock_is_ready(self):
        """
        ロックが使える状態か確認する

        ロックが使えないのに貸出を記録すると、
        「記録はあるのにカメラを取り出せない」状態になってしまうため、
        記録の前に確認します。
        """
        if not self.lock_controller.is_ready:
            raise errors.LockInitError(detail=self.lock_controller.not_ready_reason)

    def authenticate(self, card_id):
        """カードIDから利用者を探し、利用できる人か確認する"""
        if not card_id:
            raise errors.CardReadError(detail="空のカードIDを受け取りました")

        user = self.database.find_user_by_card_id(card_id)

        if user is None:
            # カードIDそのものは個人情報に近いので、ログには一部だけ残す
            logger.warning("未登録の社員証がかざされました: 末尾=%s", str(card_id)[-4:])
            raise errors.UnknownCardError()

        if not user.is_active:
            logger.warning("利用停止中の利用者です: 社員番号=%s", user.employee_number)
            raise errors.UserDisabledError()

        logger.info("利用者を確認しました: 社員番号=%s", user.employee_number)
        return user

    def get_borrowable_cameras(self, user):
        """
        貸出前の確認をして、選べるカメラの一覧を返す

            ・利用者に未返却の貸出があれば UserHasActiveRentalError
            ・貸出可能なカメラがなければ NoAvailableCameraError
        """
        active_rental = self.database.find_active_rental_by_user(user.id)
        if active_rental is not None:
            raise errors.UserHasActiveRentalError(
                user_message=(
                    f"先に「{active_rental.camera_name}」"
                    f"(返却予定 {format_for_display(active_rental.due_at)})を返却してください。"
                ),
            )

        available_cameras = self.database.list_available_cameras()
        if not available_cameras:
            raise errors.NoAvailableCameraError()

        return available_cameras

    def has_available_camera(self):
        """貸出可能なカメラが1台以上あるか(ホーム画面での事前案内用)"""
        return len(self.database.list_available_cameras()) > 0

    def calculate_due_at(self, rental_hours, start_time=None):
        """返却予定日時を計算する"""
        if start_time is None:
            start_time = self.now()
        return start_time + timedelta(hours=rental_hours)

    # ==================================================
    # 貸出
    # ==================================================

    def borrow_camera(self, user, camera_id, rental_hours):
        """
        カメラを貸し出す

            1. 入力チェック
            2. ロックが使えるか確認
            3. SQLite に記録(失敗したら例外 → 解錠しない)
            4. 解錠
        """
        if rental_hours not in self.rental_hours_options:
            raise errors.InvalidRentalHoursError(detail=f"rental_hours={rental_hours}")

        self.ensure_lock_is_ready()

        # ここで例外が出たら、この下の解錠処理には進みません
        rental = self.database.create_rental(
            user_id=user.id,
            camera_id=camera_id,
            rental_hours=rental_hours,
            rented_at=self.now(),
        )

        return self._unlock_after_record(rental, PURPOSE_BORROW)

    def cancel_borrow_after_unlock_failure(self, rental):
        """
        貸出を記録したが解錠できなかったので、貸出を取り消す

        記録は消さずに「取消(解錠失敗)」として終了させます。
        (後から管理者が経緯を追えるようにするため)
        """
        cancelled_rental = self.database.finish_rental(
            rental_id=rental.id,
            finished_at=self.now(),
            end_reason=END_REASON_CANCELLED,
            camera_status_after=CAMERA_STATUS_AVAILABLE,
        )
        logger.warning("解錠失敗のため貸出を取り消しました: rental_id=%s", rental.id)
        return cancelled_rental

    # ==================================================
    # 返却
    # ==================================================

    def get_return_target(self, user):
        """利用者の返却対象(未返却の貸出)を返す。なければ NoActiveRentalError"""
        active_rental = self.database.find_active_rental_by_user(user.id)
        if active_rental is None:
            raise errors.NoActiveRentalError()
        return active_rental

    def return_camera(self, user, rental_id):
        """
        カメラを返却する

            1. ロックが使えるか確認
            2. 本人の未返却の貸出か確認
            3. SQLite に返却を記録(失敗したら例外 → 解錠しない)
            4. 解錠
        """
        self.ensure_lock_is_ready()

        rental = self.database.get_rental(rental_id)
        if rental is None or rental.user_id != user.id:
            raise errors.RentalNotFoundError(detail=f"rental_id={rental_id} user_id={user.id}")
        if rental.is_returned:
            raise errors.NoActiveRentalError()

        returned_rental = self.database.finish_rental(
            rental_id=rental.id,
            finished_at=self.now(),
        )

        return self._unlock_after_record(returned_rental, PURPOSE_RETURN)

    # ==================================================
    # 施錠センサー
    # ==================================================

    @property
    def has_lock_sensor(self):
        """施錠センサーが使えるか"""
        return self.lock_sensor.is_available

    def read_lock_state(self):
        """
        扉の施錠状態を返す(LOCK_STATE_LOCKED / UNLOCKED / UNKNOWN)

        センサーの読み取りで想定外のエラーが出ても、画面を止めないよう
        UNKNOWN を返します。
        """
        try:
            return self.lock_sensor.read_state()
        except Exception:
            logger.exception("施錠センサーの読み取り中に想定外のエラーが発生しました")
            return LOCK_STATE_UNKNOWN

    # ==================================================
    # 解錠
    # ==================================================

    def retry_unlock(self, rental, purpose):
        """解錠失敗画面の「もう一度開ける」から呼ばれる"""
        self.ensure_lock_is_ready()
        return self._unlock_after_record(rental, purpose, is_retry=True)

    def _unlock_after_record(self, rental, purpose, is_retry=False):
        """
        DB記録の後に解錠する

        解錠に失敗しても例外は投げず、OperationResult で結果を返します。
        (DBの記録は済んでいるので、画面側で「次にどうするか」を案内するため)
        """
        log_action = "retry" if is_retry else purpose

        # 再試行のログは action が "retry" だけになるので、
        # 貸出・返却のどちらの再試行かを message の先頭に残す
        message_prefix = RETRY_PURPOSE_LABELS.get(purpose, "") if is_retry else ""

        try:
            self.lock_controller.unlock(self.unlock_seconds)
        except errors.UnlockError as error:
            unlock_error = error
        except Exception as error:
            # 想定外のエラーも「解錠失敗」として扱う
            logger.exception("解錠中に想定外のエラーが発生しました")
            unlock_error = errors.UnlockError(detail=str(error))
        else:
            unlock_error = None

        if unlock_error is None:
            self._save_unlock_log(log_action, "success", rental.id, message_prefix)

            # 返却時の再試行で解錠できたら、点検中にしていたカメラを戻す
            if purpose == PURPOSE_RETURN and is_retry:
                self._set_camera_status_quietly(rental.camera_id, CAMERA_STATUS_AVAILABLE)

            return OperationResult(rental=rental, purpose=purpose, unlocked=True)

        logger.error(
            "DB記録後に解錠できませんでした: rental_id=%s 目的=%s 詳細=%s",
            rental.id,
            purpose,
            unlock_error.detail,
        )
        failure_message = " ".join(
            part for part in (message_prefix, str(unlock_error.detail or "")) if part
        )
        self._save_unlock_log(log_action, "failed", rental.id, failure_message)

        # 返却したのに扉が開かない = カメラが保管庫に戻っていない可能性がある
        # → 次の人に貸し出されないよう「点検中」にしておく
        if purpose == PURPOSE_RETURN:
            self._set_camera_status_quietly(rental.camera_id, CAMERA_STATUS_MAINTENANCE)

        return OperationResult(
            rental=rental,
            purpose=purpose,
            unlocked=False,
            unlock_error=unlock_error,
        )

    def _save_unlock_log(self, action, result, rental_id, message):
        """解錠ログを保存する。失敗しても貸出・返却は取り消さない"""
        try:
            self.database.add_unlock_log(
                action=action,
                result=result,
                created_at=self.now(),
                rental_id=rental_id,
                message=message,
            )
        except errors.DatabaseError:
            logger.error("解錠ログを保存できませんでした: rental_id=%s 結果=%s", rental_id, result)

    def _set_camera_status_quietly(self, camera_id, status):
        """カメラの状態を変える。失敗してもログだけ残して続行する"""
        try:
            self.database.set_camera_status(camera_id, status)
        except errors.CameraRentalError:
            logger.exception("カメラの状態を変更できませんでした: camera_id=%s", camera_id)

    # ==================================================
    # 管理者向け
    # ==================================================

    def force_return(self, rental_id):
        """管理者が貸出を強制的に返却扱いにする(manage_data.py から使用)"""
        return self.database.finish_rental(
            rental_id=rental_id,
            finished_at=self.now(),
            end_reason=END_REASON_ADMIN,
        )

    # ==================================================
    # 表示・出力
    # ==================================================

    def list_camera_statuses(self):
        return self.database.list_camera_statuses()

    def list_recent_rentals(self, limit):
        return self.database.list_rentals(limit=limit)

    def export_history_csv(self, output_path=None):
        """
        貸出履歴をすべて CSV に保存し、保存先のパスを返す

        文字コードは「UTF-8 BOM付き(utf-8-sig)」です。
        Windows の Excel でダブルクリックしても文字化けしないためです。
        """
        rentals = self.database.list_rentals()
        now = self.now()

        if output_path is None:
            file_name = f"rental_history_{now.strftime('%Y%m%d_%H%M%S')}.csv"
            output_path = self.export_directory / file_name
        output_path = Path(output_path)

        header = [
            "貸出ID",
            "社員番号",
            "氏名",
            "カメラ",
            "貸出時間(時間)",
            "貸出日時",
            "返却予定日時",
            "返却日時",
            "状態",
            "延滞",
        ]

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8-sig", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(header)
                for rental in rentals:
                    writer.writerow(self._rental_to_csv_row(rental, now))
        except OSError as error:
            logger.exception("CSV の保存に失敗しました: %s", output_path)
            raise errors.CsvExportError(detail=str(error)) from error

        logger.info("履歴を CSV に出力しました: %s (%s 件)", output_path, len(rentals))
        return output_path

    def _rental_to_csv_row(self, rental, now):
        is_late = self._was_returned_late(rental, now)
        row = [
            rental.id,
            rental.employee_number,
            rental.user_name,
            rental.camera_name,
            rental.rental_hours,
            format_for_display(rental.rented_at),
            format_for_display(rental.due_at),
            # 未返却の場合は空欄(画面表示用の「-」は使わない)
            format_for_display(rental.returned_at) if rental.returned_at else "",
            rental.state_label,
            "延滞" if is_late else "",
        ]
        return [protect_csv_cell(value) for value in row]

    @staticmethod
    def _was_returned_late(rental, now):
        """未返却で期限切れ、または期限を過ぎてから返却されたか"""
        if rental.returned_at is None:
            return now > rental.due_at
        return rental.returned_at > rental.due_at


def protect_csv_cell(value):
    """
    Excel で開いたときに数式として実行されないようにする

    「=」「+」「-」「@」で始まる文字列は Excel が数式とみなすため、
    先頭に「'」を付けて文字列として扱わせます(CSVインジェクション対策)。
    """
    if not isinstance(value, str):
        return value
    if value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
