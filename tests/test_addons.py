# 追加機能のテスト(画面は使わず、計算と DB だけ確かめる)
#   python -m unittest

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import admin_screen
import events
import export
import extend
import long_rental
import overdue_record
from db import BORROW, RETURN, Database, RentalError, minutes_past

NOW = datetime(2026, 11, 20, 10, 0, 0)


def do_nothing():
    pass


class AddonTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.database = Database(Path(self.folder) / "test.sqlite3")
        self.database.create_tables()
        admin_screen.create_admin_table(self.database)
        events.create_events_table(self.database)
        self.database.add_user("1000001", "管理 太郎", "AAAA")
        self.database.add_user("1000002", "森 航太郎", "BBBB")
        self.admin = self.database.find_user_by_card("AAAA")
        self.mori = self.database.find_user_by_card("BBBB")
        admin_screen.set_admin(self.database, self.admin, True)

    def tearDown(self):
        shutil.rmtree(self.folder)

    def borrow(self, user, minutes=30, now=NOW):
        due = now + timedelta(minutes=minutes)
        self.database.start(BORROW, user, do_nothing, due_at=due, now=now)
        self.database.finish(BORROW, user, due, now=now)

    def give_back(self, user, now):
        self.database.start(RETURN, user, do_nothing, now=now)
        self.database.finish(RETURN, user, now=now)

    # ---- 延滞 ----

    def test_minutes_past(self):
        self.assertEqual(minutes_past(NOW, NOW - timedelta(minutes=5)), 0)
        self.assertEqual(minutes_past(NOW, NOW + timedelta(seconds=59)), 0)
        self.assertEqual(minutes_past(NOW, NOW + timedelta(minutes=25, seconds=30)), 25)

    def test_late_minutes(self):
        self.borrow(self.mori, 30)
        self.give_back(self.mori, NOW + timedelta(minutes=55))
        self.assertEqual(overdue_record.late_minutes_of(self.database.list_rentals()[0]), 25)

    def test_late_minutes_while_rented(self):
        self.borrow(self.mori, 30)
        self.assertIsNone(overdue_record.late_minutes_of(self.database.list_rentals()[0]))

    # ---- 延長 ----

    def test_extend_from_due_time(self):
        self.borrow(self.mori, 60)
        rental = self.database.current_rental()
        self.assertEqual(extend.new_due_at(rental, 30, NOW + timedelta(minutes=10)), NOW + timedelta(minutes=90))

    def test_extend_after_due_starts_from_now(self):
        self.borrow(self.mori, 60)
        rental = self.database.current_rental()
        later = NOW + timedelta(minutes=80)
        self.assertEqual(extend.new_due_at(rental, 30, later), later + timedelta(minutes=30))

    def test_extend_adds_a_row(self):
        self.borrow(self.mori, 60)
        rental = self.database.current_rental()
        extend.extend_rental(self.database, self.mori, rental, NOW + timedelta(hours=3))

        self.assertEqual(self.database.current_rental()["due_at"], "2026-11-20 13:00:00")
        self.assertEqual(self.database.list_rentals()[0]["due_at"], "2026-11-20 13:00:00")
        self.assertEqual(len(self.database.list_logs()), 3)   # 解錠・完了・延長(書き換えではなく追加)

    def test_cannot_extend_after_return(self):
        self.borrow(self.mori, 60)
        rental = self.database.current_rental()
        self.give_back(self.mori, NOW + timedelta(minutes=5))
        with self.assertRaises(RentalError):
            extend.extend_rental(self.database, self.mori, rental, NOW + timedelta(hours=3))

    # ---- 管理画面 ----

    def test_admin_flag(self):
        self.assertTrue(admin_screen.is_admin(self.database, self.admin))
        self.assertFalse(admin_screen.is_admin(self.database, self.mori))
        admin_screen.set_admin(self.database, self.admin, False)
        self.assertEqual(admin_screen.count_admins(self.database), 0)

    def test_delete_user_without_logs(self):
        admin_screen.delete_user(self.database, self.mori)
        self.assertIsNone(self.database.find_user_by_card("BBBB"))
        self.assertEqual(len(self.database.list_users()), 1)

    def test_delete_user_keeps_logs(self):
        self.borrow(self.mori)
        self.give_back(self.mori, NOW + timedelta(minutes=5))
        admin_screen.delete_user(self.database, self.mori)

        self.assertIsNone(self.database.find_user_by_card("BBBB"))
        self.assertEqual(self.database.list_rentals()[0]["borrower_name"], "森 航太郎")
        self.database.add_user("1000003", "新しい 人", "BBBB")   # 同じ社員証を登録し直せる

    def test_cannot_delete_user_who_is_renting(self):
        self.borrow(self.mori)
        with self.assertRaises(RentalError):
            admin_screen.delete_user(self.database, self.mori)

    def test_cannot_delete_admin(self):
        with self.assertRaises(RentalError):
            admin_screen.delete_user(self.database, self.admin)

    # ---- ファイルに保存 ----

    def test_export_csv(self):
        self.borrow(self.mori, 30)
        self.give_back(self.admin, NOW + timedelta(minutes=55))
        path = export.export_to_csv(self.database, Path(self.folder) / "exports")

        lines = path.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(lines[0].split(",")[-1], "延滞(分)")
        self.assertEqual(lines[1].split(",")[5], "管理 太郎")   # 返した人
        self.assertEqual(lines[1].split(",")[-1], "25")

    def test_export_excel(self):
        from openpyxl import load_workbook
        self.borrow(self.mori, 30)
        path = export.export_to_excel(self.database, Path(self.folder) / "exports")
        book = load_workbook(path)
        self.assertEqual(book.sheetnames, ["貸出一覧", "操作の記録", "できごと"])
        self.assertEqual(book["操作の記録"].max_row, 3)   # 見出し + 解錠 + 完了


    def test_someone_else_can_extend(self):
        self.borrow(self.mori, 60)
        rental = self.database.current_rental()
        extend.extend_rental(self.database, self.admin, rental, NOW + timedelta(hours=3))

        last = self.database.list_logs()[0]
        self.assertEqual((last["action"], last["name"]), ("延長", "管理 太郎"))   # 延ばした人が残る
        self.assertEqual(self.database.current_rental()["name"], "森 航太郎")      # 借りた人は変わらない

    # ---- できごと ----

    def test_events_are_added(self):
        events.add_event(self.database, events.UNKNOWN_CARD, "カードID FFFF")
        events.add_event(self.database, events.FORCED_OPEN, "解錠していないのに扉が開いた")
        kinds = [e["kind"] for e in events.list_events(self.database)]
        self.assertEqual(kinds, [events.FORCED_OPEN, events.UNKNOWN_CARD])   # 新しい順


    # ---- 日をまたぐ貸出 ----

    def test_long_rental_first_due_is_tomorrow(self):
        due = long_rental.first_due(NOW)
        self.assertEqual(due, datetime(2026, 11, 21, 17, 0))
        self.assertIsNone(long_rental.check_due(due, NOW))

    def test_long_rental_limits(self):
        self.assertIsNotNone(long_rental.check_due(NOW + timedelta(minutes=10), NOW))   # 近すぎる
        self.assertIsNotNone(long_rental.check_due(NOW + timedelta(days=32), NOW))      # 遠すぎる
        self.assertIsNone(long_rental.check_due(NOW + timedelta(days=31), NOW))


if __name__ == "__main__":
    unittest.main()
