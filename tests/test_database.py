"""
database.py のテスト(ハードウェア不要)
"""

import os
import sqlite3
import unittest
from datetime import timedelta

from camera_rental import errors
from camera_rental.database import Database, normalize_card_id
from camera_rental.models import (
    CAMERA_STATUS_AVAILABLE,
    CAMERA_STATUS_MAINTENANCE,
    CAMERA_STATUS_RENTED,
)
from tests.helpers import FIXED_NOW, TemporaryDatabaseTestCase


class DatabaseCreationTest(TemporaryDatabaseTestCase):
    """DB作成・テーブル作成"""

    def test_database_file_is_created(self):
        self.assertTrue(self.database_path.exists())

    def test_tables_are_created(self):
        table_names = self.database.list_table_names()
        for expected_name in ["users", "cameras", "rentals", "unlock_logs"]:
            self.assertIn(expected_name, table_names)

    def test_initialize_twice_is_safe(self):
        # 2回目の起動でもエラーにならず、データも消えないこと
        self.add_user()
        self.database.initialize()
        self.assertEqual(len(self.database.list_users()), 1)

    def test_foreign_keys_are_enabled(self):
        with self.database._open_connection() as connection:
            foreign_keys_setting = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(foreign_keys_setting, 1)

    def test_foreign_key_violation_is_rejected(self):
        # 存在しない利用者・カメラの貸出記録は入れられないこと
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO rentals (user_id, camera_id, rental_hours, rented_at, due_at)
                    VALUES (999, 999, 1, '2026-01-01 00:00:00', '2026-01-01 01:00:00')
                    """
                )


class UserTest(TemporaryDatabaseTestCase):
    """利用者の登録・検索"""

    def test_add_user(self):
        user = self.add_user(employee_number="10002", name="森 航太郎", card_id="012e4caa")
        self.assertEqual(user.employee_number, "10002")
        self.assertEqual(user.name, "森 航太郎")
        self.assertEqual(user.card_id, "012E4CAA")
        self.assertTrue(user.is_active)

    def test_find_user_by_card_id(self):
        self.add_user(card_id="01:2E:4C:AA")
        found_user = self.database.find_user_by_card_id("012e4caa")
        self.assertIsNotNone(found_user)
        self.assertEqual(found_user.employee_number, "10001")

    def test_unknown_card_returns_none(self):
        self.add_user()
        self.assertIsNone(self.database.find_user_by_card_id("NOT_REGISTERED"))

    def test_duplicate_employee_number_is_rejected(self):
        self.add_user(employee_number="10001", card_id="CARD_A")
        with self.assertRaises(errors.DuplicateUserError):
            self.add_user(employee_number="10001", card_id="CARD_B")

    def test_duplicate_card_id_is_rejected(self):
        self.add_user(employee_number="10001", card_id="CARD_A")
        with self.assertRaises(errors.DuplicateUserError):
            self.add_user(employee_number="10002", card_id="card_a")

    def test_empty_values_are_rejected(self):
        with self.assertRaises(errors.CameraRentalError):
            self.add_user(employee_number="", name="名前", card_id="CARD")

    def test_disable_and_enable_user(self):
        self.add_user()
        self.database.set_user_active("10001", False)
        self.assertFalse(self.database.find_user_by_employee_number("10001").is_active)
        self.database.set_user_active("10001", True)
        self.assertTrue(self.database.find_user_by_employee_number("10001").is_active)

    def test_normalize_card_id(self):
        self.assertEqual(normalize_card_id(" 01 2e:4c-aa "), "012E4CAA")


class CameraTest(TemporaryDatabaseTestCase):
    """カメラの登録・状態変更"""

    def test_add_camera(self):
        camera = self.add_camera("セキュアカメラ2号機")
        self.assertEqual(camera.name, "セキュアカメラ2号機")
        self.assertEqual(camera.status, CAMERA_STATUS_AVAILABLE)
        self.assertEqual(camera.status_label, "貸出可能")

    def test_duplicate_camera_is_rejected(self):
        self.add_camera("1号機")
        with self.assertRaises(errors.DuplicateCameraError):
            self.add_camera("1号機")

    def test_set_maintenance_and_back(self):
        camera = self.add_camera()
        self.database.set_camera_status(camera.id, CAMERA_STATUS_MAINTENANCE)
        self.assertEqual(self.database.get_camera(camera.id).status_label, "点検中")
        self.assertEqual(self.database.list_available_cameras(), [])

        self.database.set_camera_status(camera.id, CAMERA_STATUS_AVAILABLE)
        self.assertEqual(len(self.database.list_available_cameras()), 1)

    def test_cannot_set_rented_manually(self):
        camera = self.add_camera()
        with self.assertRaises(errors.CameraRentalError):
            self.database.set_camera_status(camera.id, CAMERA_STATUS_RENTED)

    def test_cannot_change_status_while_rented(self):
        user = self.add_user()
        camera = self.add_camera()
        self.database.create_rental(user.id, camera.id, 1, FIXED_NOW)
        with self.assertRaises(errors.CameraRentalError):
            self.database.set_camera_status(camera.id, CAMERA_STATUS_MAINTENANCE)


class RentalTest(TemporaryDatabaseTestCase):
    """貸出・返却"""

    def setUp(self):
        super().setUp()
        self.user = self.add_user()
        self.camera = self.add_camera()

    def test_create_rental(self):
        rental = self.database.create_rental(self.user.id, self.camera.id, 4, FIXED_NOW)

        self.assertEqual(rental.user_id, self.user.id)
        self.assertEqual(rental.camera_id, self.camera.id)
        self.assertEqual(rental.rented_at, FIXED_NOW)
        self.assertEqual(rental.due_at, FIXED_NOW + timedelta(hours=4))
        self.assertIsNone(rental.returned_at)
        self.assertEqual(rental.state_label, "未返却")
        self.assertEqual(rental.camera_name, self.camera.name)
        self.assertEqual(rental.user_name, self.user.name)

    def test_camera_becomes_rented(self):
        self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)
        camera = self.database.get_camera(self.camera.id)
        self.assertEqual(camera.status, CAMERA_STATUS_RENTED)
        self.assertEqual(camera.status_label, "貸出中")

    def test_same_camera_cannot_be_rented_twice(self):
        """二重貸出防止: 別の人が同じカメラを借りられない"""
        other_user = self.add_user(employee_number="10002", card_id="CARD0002")
        self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)

        with self.assertRaises(errors.CameraNotAvailableError):
            self.database.create_rental(other_user.id, self.camera.id, 1, FIXED_NOW)

        # 失敗した方の記録は残っていないこと(rollback されている)
        self.assertEqual(len(self.database.list_rentals()), 1)

    def test_user_cannot_rent_while_having_active_rental(self):
        """未返却状態での再貸出防止"""
        second_camera = self.add_camera("テストカメラ2号機")
        self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)

        with self.assertRaises(errors.UserHasActiveRentalError):
            self.database.create_rental(self.user.id, second_camera.id, 1, FIXED_NOW)

        # 2台目のカメラは貸出可能のまま(rollback されている)
        self.assertEqual(self.database.get_camera(second_camera.id).status, CAMERA_STATUS_AVAILABLE)

    def test_maintenance_camera_cannot_be_rented(self):
        self.database.set_camera_status(self.camera.id, CAMERA_STATUS_MAINTENANCE)
        with self.assertRaises(errors.CameraNotAvailableError):
            self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)
        self.assertEqual(self.database.list_rentals(), [])

    def test_disabled_user_cannot_rent(self):
        self.database.set_user_active(self.user.employee_number, False)
        with self.assertRaises(errors.UserDisabledError):
            self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)

    def test_partial_unique_index_blocks_second_open_rental(self):
        """
        最終防衛線の確認:
        プログラムの確認をすり抜けて直接 INSERT しても、DB が二重貸出を拒否すること
        """
        other_user = self.add_user(employee_number="10002", card_id="CARD0002")
        self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)

        with self.assertRaises(sqlite3.IntegrityError):
            with self.database._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO rentals (user_id, camera_id, rental_hours, rented_at, due_at)
                    VALUES (?, ?, 1, '2026-11-10 10:00:00', '2026-11-10 11:00:00')
                    """,
                    (other_user.id, self.camera.id),
                )

    def test_return_rental(self):
        rental = self.database.create_rental(self.user.id, self.camera.id, 2, FIXED_NOW)
        returned_time = FIXED_NOW + timedelta(hours=1)

        returned_rental = self.database.finish_rental(rental.id, returned_time)

        self.assertEqual(returned_rental.returned_at, returned_time)
        self.assertTrue(returned_rental.is_returned)
        self.assertEqual(returned_rental.state_label, "返却")

    def test_camera_becomes_available_after_return(self):
        rental = self.database.create_rental(self.user.id, self.camera.id, 2, FIXED_NOW)
        self.database.finish_rental(rental.id, FIXED_NOW + timedelta(hours=1))

        self.assertEqual(self.database.get_camera(self.camera.id).status, CAMERA_STATUS_AVAILABLE)
        self.assertIsNone(self.database.find_active_rental_by_user(self.user.id))

    def test_can_rent_again_after_return(self):
        rental = self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)
        self.database.finish_rental(rental.id, FIXED_NOW + timedelta(minutes=30))
        second_rental = self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW + timedelta(hours=1))
        self.assertIsNotNone(second_rental)

    def test_cannot_return_twice(self):
        rental = self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)
        self.database.finish_rental(rental.id, FIXED_NOW)
        with self.assertRaises(errors.NoActiveRentalError):
            self.database.finish_rental(rental.id, FIXED_NOW)

    def test_history_is_saved(self):
        first = self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)
        self.database.finish_rental(first.id, FIXED_NOW + timedelta(minutes=30))
        self.database.create_rental(self.user.id, self.camera.id, 2, FIXED_NOW + timedelta(hours=1))

        history = self.database.list_rentals()
        self.assertEqual(len(history), 2)
        # 新しい順
        self.assertEqual(history[0].rental_hours, 2)
        self.assertEqual(history[1].state_label, "返却")

    def test_data_remains_after_restart(self):
        """アプリを再起動(Database を作り直し)してもデータが残っていること"""
        self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)

        restarted_database = Database(self.database_path)
        restarted_database.initialize()

        self.assertEqual(len(restarted_database.list_rentals()), 1)
        self.assertEqual(len(restarted_database.list_users()), 1)
        self.assertEqual(restarted_database.open_connection_count, 0)

    def test_camera_status_list(self):
        self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)
        self.add_camera("テストカメラ2号機")

        status_rows = self.database.list_camera_statuses()
        self.assertEqual(len(status_rows), 2)
        self.assertIsNotNone(status_rows[0].rental)
        self.assertIsNone(status_rows[1].rental)

    def test_no_inconsistency_in_normal_use(self):
        rental = self.database.create_rental(self.user.id, self.camera.id, 1, FIXED_NOW)
        self.assertEqual(self.database.find_inconsistencies(), [])
        self.database.finish_rental(rental.id, FIXED_NOW)
        self.assertEqual(self.database.find_inconsistencies(), [])


class ConnectionCloseTest(TemporaryDatabaseTestCase):
    """接続が確実に閉じられること"""

    def test_connections_are_closed_after_success(self):
        user = self.add_user()
        camera = self.add_camera()
        rental = self.database.create_rental(user.id, camera.id, 1, FIXED_NOW)
        self.database.finish_rental(rental.id, FIXED_NOW)
        self.database.list_rentals()
        self.database.list_camera_statuses()
        self.assertEqual(self.database.open_connection_count, 0)

    def test_connections_are_closed_after_errors(self):
        user = self.add_user()
        camera = self.add_camera()
        self.database.create_rental(user.id, camera.id, 1, FIXED_NOW)

        # わざとエラーを起こす
        with self.assertRaises(errors.DuplicateUserError):
            self.add_user()
        with self.assertRaises(errors.UserHasActiveRentalError):
            self.database.create_rental(user.id, camera.id, 1, FIXED_NOW)
        with self.assertRaises(errors.RentalNotFoundError):
            self.database.finish_rental(9999, FIXED_NOW)

        self.assertEqual(self.database.open_connection_count, 0)

    def test_database_file_can_be_deleted_immediately(self):
        """Windows で WinError 32 にならないこと(操作直後に削除できる)"""
        user = self.add_user()
        camera = self.add_camera()
        self.database.create_rental(user.id, camera.id, 1, FIXED_NOW)

        os.remove(self.database_path)
        self.assertFalse(self.database_path.exists())


class DatabaseFailureTest(TemporaryDatabaseTestCase):
    """SQLite の失敗が DatabaseError に変換されること"""

    def test_failed_insert_rolls_back_camera_status(self):
        """
        カメラを「貸出中」にした後で貸出記録の追加に失敗した場合、
        カメラの状態変更も取り消される(rollback)こと

        rental_hours=0 は CHECK 制約(rental_hours > 0)違反になるので、
        「UPDATE は成功 → INSERT で失敗」という状況を作れます。
        """
        user = self.add_user()
        camera = self.add_camera()

        with self.assertRaises(errors.DatabaseError):
            self.database.create_rental(user.id, camera.id, 0, FIXED_NOW)

        self.assertEqual(self.database.get_camera(camera.id).status, CAMERA_STATUS_AVAILABLE)
        self.assertEqual(self.database.list_rentals(), [])

    def test_broken_table_raises_database_error(self):
        user = self.add_user()
        camera = self.add_camera()

        # 貸出テーブルを消して、保存に失敗する状況を作る
        with self.database._transaction() as connection:
            connection.execute("DROP TABLE rentals")

        with self.assertRaises(errors.DatabaseError):
            self.database.create_rental(user.id, camera.id, 1, FIXED_NOW)

        # カメラの状態は変わっていないこと
        self.assertEqual(self.database.get_camera(camera.id).status, CAMERA_STATUS_AVAILABLE)


if __name__ == "__main__":
    unittest.main()
