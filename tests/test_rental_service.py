"""
rental_service.py のテスト(ハードウェア不要)

特に「DB記録 → 解錠」の順番と、
「DB記録に失敗したら解錠しない」ことを確認します。
"""

import csv
import unittest
from datetime import timedelta

from camera_rental import errors
from camera_rental.models import (
    CAMERA_STATUS_AVAILABLE,
    CAMERA_STATUS_MAINTENANCE,
    END_REASON_ADMIN,
    END_REASON_CANCELLED,
)
from camera_rental.rental_service import PURPOSE_BORROW, PURPOSE_RETURN, RentalService, protect_csv_cell
from camera_rental.hardware.lock_sensor import (
    LOCK_STATE_LOCKED,
    LOCK_STATE_UNKNOWN,
    LOCK_STATE_UNLOCKED,
    DemoLockSensor,
)
from tests.helpers import FIXED_NOW, FakeLockController, TemporaryDatabaseTestCase


class RentalServiceTestCase(TemporaryDatabaseTestCase):
    """RentalService を使うテストの親クラス"""

    def setUp(self):
        super().setUp()
        self.user = self.add_user(employee_number="10002", name="森 航太郎", card_id="CARD0002")
        self.camera = self.add_camera("セキュアカメラ1号機")
        self.lock = FakeLockController()
        self.service = self.create_service(self.lock)

    def create_service(self, lock, hours_options=(1, 2, 4, 8), lock_sensor=None):
        return RentalService(
            database=self.database,
            lock_controller=lock,
            rental_hours_options=hours_options,
            unlock_seconds=10,
            export_directory=self.temporary_directory / "exports",
            clock=lambda: FIXED_NOW,
            lock_sensor=lock_sensor,
        )


class AuthenticationTest(RentalServiceTestCase):

    def test_registered_card(self):
        user = self.service.authenticate("card0002")
        self.assertEqual(user.employee_number, "10002")

    def test_unregistered_card_is_rejected(self):
        with self.assertRaises(errors.UnknownCardError):
            self.service.authenticate("UNKNOWN")

    def test_disabled_user_is_rejected(self):
        self.database.set_user_active("10002", False)
        with self.assertRaises(errors.UserDisabledError):
            self.service.authenticate("CARD0002")

    def test_empty_card_id_is_read_error(self):
        with self.assertRaises(errors.CardReadError):
            self.service.authenticate("")


class BorrowTest(RentalServiceTestCase):

    def test_borrow_records_then_unlocks(self):
        result = self.service.borrow_camera(self.user, self.camera.id, 2)

        self.assertTrue(result.unlocked)
        self.assertEqual(result.purpose, PURPOSE_BORROW)
        self.assertEqual(self.lock.unlock_calls, [10])
        self.assertEqual(result.rental.due_at, FIXED_NOW + timedelta(hours=2))

        logs = self.database.list_unlock_logs()
        self.assertEqual(logs[0]["result"], "success")
        self.assertEqual(logs[0]["action"], "borrow")

    def test_due_time_calculation(self):
        for hours in [1, 2, 4, 8]:
            self.assertEqual(self.service.calculate_due_at(hours), FIXED_NOW + timedelta(hours=hours))

    def test_borrowable_cameras(self):
        cameras = self.service.get_borrowable_cameras(self.user)
        self.assertEqual([camera.name for camera in cameras], ["セキュアカメラ1号機"])

    def test_no_available_camera(self):
        self.database.set_camera_status(self.camera.id, CAMERA_STATUS_MAINTENANCE)
        self.assertFalse(self.service.has_available_camera())
        with self.assertRaises(errors.NoAvailableCameraError):
            self.service.get_borrowable_cameras(self.user)

    def test_user_with_active_rental_cannot_borrow(self):
        self.add_camera("セキュアカメラ2号機")
        self.service.borrow_camera(self.user, self.camera.id, 1)
        with self.assertRaises(errors.UserHasActiveRentalError):
            self.service.get_borrowable_cameras(self.user)

    def test_double_rental_does_not_unlock(self):
        """二重貸出は拒否され、2回目の解錠も行われないこと"""
        other_user = self.add_user(employee_number="10003", card_id="CARD0003")
        self.service.borrow_camera(self.user, self.camera.id, 1)

        with self.assertRaises(errors.CameraNotAvailableError):
            self.service.borrow_camera(other_user, self.camera.id, 1)

        self.assertEqual(len(self.lock.unlock_calls), 1)

    def test_invalid_hours_are_rejected(self):
        with self.assertRaises(errors.InvalidRentalHoursError):
            self.service.borrow_camera(self.user, self.camera.id, 3)
        self.assertEqual(self.lock.unlock_calls, [])

    def test_hours_options_can_be_changed(self):
        """貸出時間の候補を設定で変更できること"""
        service = self.create_service(self.lock, hours_options=[3, 6])
        result = service.borrow_camera(self.user, self.camera.id, 3)
        self.assertEqual(result.rental.due_at, FIXED_NOW + timedelta(hours=3))


class DatabaseFailureDoesNotUnlockTest(RentalServiceTestCase):
    """最重要: SQLite への記録に失敗した場合は解錠しない"""

    def test_borrow_database_failure_does_not_unlock(self):
        with self.database._transaction() as connection:
            connection.execute("DROP TABLE unlock_logs")
            connection.execute("DROP TABLE rentals")

        with self.assertRaises(errors.DatabaseError):
            self.service.borrow_camera(self.user, self.camera.id, 1)

        self.assertEqual(self.lock.unlock_calls, [])

    def test_return_database_failure_does_not_unlock(self):
        result = self.service.borrow_camera(self.user, self.camera.id, 1)
        self.lock.unlock_calls.clear()

        # 返却の記録(UPDATE)だけが失敗するように、トリガーで邪魔をする
        with self.database._transaction() as connection:
            connection.execute(
                """
                CREATE TRIGGER block_return
                BEFORE UPDATE OF returned_at ON rentals
                BEGIN
                    SELECT RAISE(ABORT, 'test: return blocked');
                END
                """
            )

        with self.assertRaises(errors.DatabaseError):
            self.service.return_camera(self.user, result.rental.id)

        self.assertEqual(self.lock.unlock_calls, [])

    def test_lock_not_ready_blocks_recording(self):
        """ロックが使えないときは、記録もしない(取り出せない貸出を作らない)"""
        service = self.create_service(FakeLockController(is_ready=False))
        with self.assertRaises(errors.LockInitError):
            service.borrow_camera(self.user, self.camera.id, 1)
        self.assertEqual(self.database.list_rentals(), [])


class UnlockFailureTest(RentalServiceTestCase):
    """DB 記録後に解錠へ失敗した場合"""

    def test_borrow_unlock_failure_keeps_record_and_logs(self):
        failing_service = self.create_service(FakeLockController(fail_unlock=True))
        result = failing_service.borrow_camera(self.user, self.camera.id, 1)

        self.assertFalse(result.unlocked)
        self.assertIsNotNone(result.unlock_error)
        # 貸出記録は残っている
        self.assertIsNotNone(self.database.find_active_rental_by_user(self.user.id))
        # 失敗のログが残っている
        self.assertEqual(self.database.list_unlock_logs()[0]["result"], "failed")

    def test_cancel_after_unlock_failure(self):
        failing_service = self.create_service(FakeLockController(fail_unlock=True))
        result = failing_service.borrow_camera(self.user, self.camera.id, 1)

        cancelled = failing_service.cancel_borrow_after_unlock_failure(result.rental)

        self.assertEqual(cancelled.end_reason, END_REASON_CANCELLED)
        self.assertEqual(cancelled.state_label, "取消(解錠失敗)")
        self.assertEqual(self.database.get_camera(self.camera.id).status, CAMERA_STATUS_AVAILABLE)
        # 記録は消さずに残す(管理者が経緯を追えるように)
        self.assertEqual(len(self.database.list_rentals()), 1)

    def test_retry_unlock_success(self):
        failing_lock = FakeLockController(fail_unlock=True)
        service = self.create_service(failing_lock)
        result = service.borrow_camera(self.user, self.camera.id, 1)

        failing_lock.fail_unlock = False
        retry_result = service.retry_unlock(result.rental, PURPOSE_BORROW)

        self.assertTrue(retry_result.unlocked)
        actions = [log["action"] for log in self.database.list_unlock_logs()]
        self.assertEqual(actions, ["retry", "borrow"])

    def test_return_unlock_failure_sets_maintenance(self):
        """返却後に扉が開かなければ、カメラを点検中にして次の貸出を防ぐ"""
        borrow_result = self.service.borrow_camera(self.user, self.camera.id, 1)

        failing_lock = FakeLockController(fail_unlock=True)
        service = self.create_service(failing_lock)
        return_result = service.return_camera(self.user, borrow_result.rental.id)

        self.assertFalse(return_result.unlocked)
        self.assertTrue(return_result.rental.is_returned)
        self.assertEqual(self.database.get_camera(self.camera.id).status, CAMERA_STATUS_MAINTENANCE)

        # 再試行で開いたら「貸出可能」に戻す
        failing_lock.fail_unlock = False
        service.retry_unlock(return_result.rental, PURPOSE_RETURN)
        self.assertEqual(self.database.get_camera(self.camera.id).status, CAMERA_STATUS_AVAILABLE)


class ReturnTest(RentalServiceTestCase):

    def test_return_flow(self):
        borrow_result = self.service.borrow_camera(self.user, self.camera.id, 4)
        target = self.service.get_return_target(self.user)
        self.assertEqual(target.id, borrow_result.rental.id)

        return_result = self.service.return_camera(self.user, target.id)

        self.assertTrue(return_result.unlocked)
        self.assertTrue(return_result.rental.is_returned)
        self.assertEqual(self.database.get_camera(self.camera.id).status, CAMERA_STATUS_AVAILABLE)
        self.assertEqual(len(self.lock.unlock_calls), 2)

    def test_nothing_to_return(self):
        with self.assertRaises(errors.NoActiveRentalError):
            self.service.get_return_target(self.user)

    def test_cannot_return_other_users_rental(self):
        other_user = self.add_user(employee_number="10003", card_id="CARD0003")
        borrow_result = self.service.borrow_camera(self.user, self.camera.id, 1)
        with self.assertRaises(errors.RentalNotFoundError):
            self.service.return_camera(other_user, borrow_result.rental.id)

    def test_force_return_by_admin(self):
        borrow_result = self.service.borrow_camera(self.user, self.camera.id, 1)
        rental = self.service.force_return(borrow_result.rental.id)
        self.assertEqual(rental.end_reason, END_REASON_ADMIN)


class CsvExportTest(RentalServiceTestCase):

    def test_export_history(self):
        borrow_result = self.service.borrow_camera(self.user, self.camera.id, 1)
        self.service.return_camera(self.user, borrow_result.rental.id)

        saved_path = self.service.export_history_csv()

        self.assertTrue(saved_path.exists())
        # Excel で文字化けしないよう BOM 付き UTF-8 になっていること
        self.assertEqual(saved_path.read_bytes()[:3], b"\xef\xbb\xbf")

        with open(saved_path, encoding="utf-8-sig", newline="") as csv_file:
            rows = list(csv.reader(csv_file))

        self.assertEqual(rows[0][0], "貸出ID")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][2], "森 航太郎")
        self.assertEqual(rows[1][8], "返却")

    def test_export_failure_raises_csv_error(self):
        # 保存先のフォルダ名と同じ名前の「ファイル」を置いて、フォルダを作れなくする
        blocking_file = self.temporary_directory / "blocked"
        blocking_file.write_text("x")
        with self.assertRaises(errors.CsvExportError):
            self.service.export_history_csv(output_path=blocking_file / "history.csv")

    def test_formula_injection_is_prevented(self):
        self.assertEqual(protect_csv_cell("=1+1"), "'=1+1")
        self.assertEqual(protect_csv_cell("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(protect_csv_cell("森 航太郎"), "森 航太郎")
        self.assertEqual(protect_csv_cell(15), 15)


class RetryLogTest(RentalServiceTestCase):

    def test_retry_log_records_purpose(self):
        """再試行のログに、貸出・返却どちらの再試行かが残る"""
        failing_lock = FakeLockController(fail_unlock=True)
        service = self.create_service(failing_lock)
        result = service.borrow_camera(self.user, self.camera.id, 1)

        service.retry_unlock(result.rental, PURPOSE_BORROW)
        failed_retry_log = self.database.list_unlock_logs()[0]
        self.assertEqual(failed_retry_log["action"], "retry")
        self.assertTrue(failed_retry_log["message"].startswith("貸出の再試行"))

        failing_lock.fail_unlock = False
        service.retry_unlock(result.rental, PURPOSE_BORROW)
        success_retry_log = self.database.list_unlock_logs()[0]
        self.assertEqual(success_retry_log["result"], "success")
        self.assertEqual(success_retry_log["message"], "貸出の再試行")


class LockSensorServiceTest(RentalServiceTestCase):

    def test_without_sensor_state_is_unknown(self):
        self.assertFalse(self.service.has_lock_sensor)
        self.assertEqual(self.service.read_lock_state(), LOCK_STATE_UNKNOWN)

    def test_reads_sensor_state(self):
        sensor = DemoLockSensor()
        service = self.create_service(self.lock, lock_sensor=sensor)
        self.assertTrue(service.has_lock_sensor)
        self.assertEqual(service.read_lock_state(), LOCK_STATE_LOCKED)
        sensor.open_door()
        self.assertEqual(service.read_lock_state(), LOCK_STATE_UNLOCKED)

    def test_broken_sensor_does_not_stop_borrowing(self):
        """センサーの読み取りで例外が出ても UNKNOWN を返し、貸出は続けられる"""

        class BrokenSensor:
            is_available = True

            def read_state(self):
                raise RuntimeError("テスト: センサー故障")

        service = self.create_service(self.lock, lock_sensor=BrokenSensor())
        self.assertEqual(service.read_lock_state(), LOCK_STATE_UNKNOWN)
        result = service.borrow_camera(self.user, self.camera.id, 1)
        self.assertTrue(result.unlocked)


if __name__ == "__main__":
    unittest.main()
