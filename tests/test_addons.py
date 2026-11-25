# 追加機能のテスト(画面は使わず、計算と DB だけ確かめる)
#   python -m unittest

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import admin_screen
import config
import events
import export
import extend
import long_rental
import storage_check
import user_info
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
        user_info.add_columns(self.database)
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
        self.assertEqual(book.sheetnames, ["貸出一覧", "操作の記録", "できごと", "利用者"])
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


    # ---- 期限切れのできごと ----

    def test_overdue_is_recorded_once(self):
        self.borrow(self.mori, 30)
        later = NOW + timedelta(minutes=45)
        self.assertTrue(events.check_overdue(self.database, later))
        self.assertFalse(events.check_overdue(self.database, later + timedelta(minutes=5)))   # 2 回目は記録しない

        # 延長したら、新しい返却予定を過ぎたときにもう一度記録する
        rental = self.database.current_rental()
        extend.extend_rental(self.database, self.mori, rental, NOW + timedelta(hours=2))
        self.assertFalse(events.check_overdue(self.database, NOW + timedelta(hours=1)))
        self.assertTrue(events.check_overdue(self.database, NOW + timedelta(hours=3)))

    def test_not_overdue_before_due(self):
        self.borrow(self.mori, 30)
        self.assertFalse(events.check_overdue(self.database, NOW + timedelta(minutes=10)))

    # ---- 容量と DB の見張り ----

    def test_low_space_is_recorded_once(self):
        saved = config.LOW_SPACE_MB
        storage_check.low_space = False
        try:
            config.LOW_SPACE_MB = 10 ** 9   # どんな空きでも「少ない」になるようにする
            storage_check.check_space(self.database)
            storage_check.check_space(self.database)
        finally:
            config.LOW_SPACE_MB = saved
            storage_check.low_space = False
        kinds = [e["kind"] for e in events.list_events(self.database)]
        self.assertEqual(kinds, [events.LOW_SPACE])

    def test_delete_old_files(self):
        saved = config.EXPORT_DIR
        config.EXPORT_DIR = Path(self.folder) / "exports"
        try:
            config.EXPORT_DIR.mkdir()
            old = config.EXPORT_DIR / "rental_log_20251001_100000.csv"
            new = config.EXPORT_DIR / "rental_log_20261120_100000.csv"
            temp = config.EXPORT_DIR / "rental_log.tmp"
            latest = config.EXPORT_DIR / "rental_log.xlsx"
            for f in (old, new, temp, latest):
                f.write_text("x")
            forty_days_ago = datetime.now().timestamp() - 40 * 24 * 60 * 60
            os.utime(old, (forty_days_ago, forty_days_ago))
            os.utime(latest, (forty_days_ago, forty_days_ago))

            self.assertEqual(storage_check.delete_old_files(), 2)   # 古いものと .tmp
            self.assertEqual(sorted(f.name for f in config.EXPORT_DIR.iterdir()),
                             ["rental_log.xlsx", "rental_log_20261120_100000.csv"])
        finally:
            config.EXPORT_DIR = saved

    def test_db_check(self):
        self.assertTrue(storage_check.check_db(self.database))

    def test_door_not_opened_when_disk_is_full(self):
        # DB の大きさを今のままに制限して、容量不足を起こす
        original_open = self.database.open

        def small_open():
            conn = original_open()
            pages = conn.execute("PRAGMA page_count").fetchone()[0]
            conn.execute(f"PRAGMA max_page_count = {pages}")
            return conn

        self.database.open = small_open
        conn = self.database.open()
        try:
            while True:   # 解錠の記録と同じ大きさの行で、空いている場所を全部埋める
                self.database.add_log(conn, BORROW, "取り消し", self.mori, NOW, now=NOW)
                conn.commit()
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

        opened = []
        with self.assertRaises(sqlite3.OperationalError):
            self.database.start(BORROW, self.mori, lambda: opened.append(True), due_at=NOW)
        self.assertEqual(opened, [])   # 記録できないので扉は開けていない


    # ---- 部署と利用停止 ----

    def reload(self, user):
        return self.database.find_user_by_card(user["card_id"])

    def test_columns_are_added_to_old_db(self):
        columns = [row["name"] for row in self.database.select_all("PRAGMA table_info(users)")]
        self.assertIn("department", columns)
        self.assertIn("active", columns)
        user_info.add_columns(self.database)   # 2 回呼んでもエラーにならない

    def test_department(self):
        user_info.set_department(self.database, self.mori, "総務部")
        self.assertEqual(user_info.department_of(self.reload(self.mori)), "総務部")

    def test_suspended_user_cannot_use(self):
        user_info.set_active(self.database, self.mori, False)
        mori = self.reload(self.mori)
        with self.assertRaises(RentalError):
            user_info.check_active(mori)

        user_info.set_active(self.database, mori, True)   # 再開
        user_info.check_active(self.reload(self.mori))    # エラーにならない

    def test_admin_cannot_be_suspended(self):
        with self.assertRaises(RentalError):
            user_info.set_active(self.database, self.admin, False, user_is_admin=True)

    def test_users_sheet(self):
        from openpyxl import load_workbook
        user_info.set_department(self.database, self.mori, "総務部")
        user_info.set_active(self.database, self.mori, False)
        path = export.export_to_excel(self.database, Path(self.folder) / "exports")
        rows = list(load_workbook(path)["利用者"].iter_rows(values_only=True))
        self.assertEqual(rows[0], ("社員番号", "氏名", "部署", "状態", "管理者"))
        self.assertEqual(rows[2], ("1000002", "森 航太郎", "総務部", "停止中", None))


    # ---- 履歴の検索 ----

    def test_search_rentals(self):
        self.borrow(self.mori, 30, now=NOW - timedelta(days=10))
        self.give_back(self.admin, NOW - timedelta(days=10))
        self.borrow(self.admin, 30, now=NOW)

        rentals = self.database.list_rentals()
        search = admin_screen.search_rentals
        self.assertEqual(len(search(rentals, "", None, NOW)), 2)
        self.assertEqual(len(search(rentals, "", 7, NOW)), 1)       # 7 日以内は今日の 1 件だけ
        self.assertEqual(len(search(rentals, "森", None, NOW)), 1)   # 借りた人で探す
        self.assertEqual(len(search(rentals, "管理", None, NOW)), 2)  # 返した人でも当たる
        self.assertEqual(len(search(rentals, "1000002", None, NOW)), 1)  # 社員番号
        self.assertEqual(len(search(rentals, "いない人", None, NOW)), 0)


    # ---- 利用者の編集 ----

    def test_update_user(self):
        admin_screen.update_user(self.database, self.mori, "１２３４５６７", "森 航太")   # 全角の数字でもよい
        mori = self.database.find_user_by_card("BBBB")
        self.assertEqual((mori["employee_number"], mori["name"]), ("1234567", "森 航太"))

    def test_update_user_rejects_bad_input(self):
        with self.assertRaises(RentalError):
            admin_screen.update_user(self.database, self.mori, "123", "森")          # 7 桁でない
        with self.assertRaises(RentalError):
            admin_screen.update_user(self.database, self.mori, "1000001", "森")      # ほかの人の番号
        with self.assertRaises(RentalError):
            admin_screen.update_user(self.database, self.mori, "1000002", "")        # 氏名が空

    def test_change_card(self):
        self.borrow(self.mori)
        admin_screen.change_card(self.database, self.mori, "cc:dd:ee")
        self.assertIsNone(self.database.find_user_by_card("BBBB"))                    # 前の社員証は使えない
        self.assertEqual(self.database.find_user_by_card("CCDDEE")["name"], "森 航太郎")
        self.assertEqual(self.database.current_rental()["name"], "森 航太郎")       # 記録はそのまま
        with self.assertRaises(RentalError):
            admin_screen.change_card(self.database, self.mori, "AAAA")                # ほかの人の社員証


if __name__ == "__main__":
    unittest.main()
