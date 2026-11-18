# DB のテスト
#   python -m unittest

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from db import BORROW, CANCEL, DONE, RETURN, UNLOCK, Database, RentalError

NOW = datetime(2026, 11, 20, 10, 0, 0)


def do_nothing():
    pass


def broken_door():
    raise RuntimeError("扉が開かない")


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = Path(self.folder) / "test.sqlite3"
        self.db = Database(self.path)
        self.db.create_tables()
        self.db.add_user("10001", "山田 太郎", "01:2e:4c:aa")
        self.db.add_user("10002", "森 航太郎", "BBBB")
        self.yamada = self.db.find_user_by_card("012E4CAA")
        self.mori = self.db.find_user_by_card("BBBB")

    def tearDown(self):
        # 接続を閉じ忘れていると、Windows ではここで消せずにエラーになる
        os.remove(self.path)
        os.rmdir(self.folder)

    def steps(self):
        # 記録された (操作, 段階) を古い順に
        return [(log["action"], log["step"]) for log in reversed(self.db.list_logs())]

    def borrow(self, user, minutes=30, now=NOW):
        due = now + timedelta(minutes=minutes)
        self.db.start(BORROW, user, do_nothing, due_at=due, now=now)
        self.db.finish(BORROW, user, due, now=now + timedelta(seconds=20))

    def give_back(self, user, now):
        self.db.start(RETURN, user, do_nothing, now=now)
        self.db.finish(RETURN, user, now=now + timedelta(seconds=20))

    # ---- 利用者 ----

    def test_same_card_cannot_be_added_twice(self):
        with self.assertRaises(RentalError):
            self.db.add_user("10003", "別の人", "012E4CAA")

    # ---- 貸出 ----

    def test_not_rented_until_door_is_closed(self):
        # 解錠しただけでは貸出中にならない(扉が閉まって完了してから)
        due = NOW + timedelta(minutes=30)
        self.db.start(BORROW, self.yamada, do_nothing, due_at=due, now=NOW)
        self.assertIsNone(self.db.current_rental())

        self.db.finish(BORROW, self.yamada, due, now=NOW)
        rental = self.db.current_rental()
        self.assertEqual(rental["name"], "山田 太郎")
        self.assertEqual(rental["due_at"], "2026-11-20 10:30:00")

    def test_cancel_keeps_camera_available(self):
        self.db.start(BORROW, self.yamada, do_nothing, due_at=NOW, now=NOW)
        self.db.cancel(BORROW, self.yamada, "扉が開かれなかったため")
        self.assertIsNone(self.db.current_rental())
        self.assertEqual(self.steps(), [(BORROW, UNLOCK), (BORROW, CANCEL)])

    def test_cannot_borrow_twice(self):
        self.borrow(self.yamada)
        with self.assertRaises(RentalError):
            self.db.start(BORROW, self.mori, do_nothing, due_at=NOW)

    def test_door_not_opened_when_record_fails(self):
        opened = []
        self.db.execute("DROP TABLE logs")
        with self.assertRaises(Exception):
            self.db.start(BORROW, self.yamada, lambda: opened.append(True), due_at=NOW)
        self.assertEqual(opened, [])

    def test_record_removed_when_door_does_not_open(self):
        with self.assertRaises(RuntimeError):
            self.db.start(BORROW, self.yamada, broken_door, due_at=NOW)
        self.assertEqual(self.db.list_logs(), [])

    # ---- 返却 ----

    def test_anyone_registered_can_return(self):
        self.borrow(self.yamada)
        self.give_back(self.mori, NOW + timedelta(hours=1))
        self.assertIsNone(self.db.current_rental())

        rental = self.db.list_rentals()[0]
        self.assertEqual(rental["borrower_name"], "山田 太郎")
        self.assertEqual(rental["returner_name"], "森 航太郎")
        self.assertEqual(rental["returned_at"], "2026-11-20 11:00:20")

    def test_cannot_return_when_not_rented(self):
        with self.assertRaises(RentalError):
            self.db.start(RETURN, self.yamada, do_nothing)

    # ---- 記録 ----

    def test_logs_are_only_added(self):
        # 貸出と返却は別々の行。前の行は書き換えない
        self.borrow(self.yamada)
        first_logs = [dict(log) for log in self.db.list_logs()]
        self.give_back(self.yamada, NOW + timedelta(hours=1))

        self.assertEqual(self.steps(), [(BORROW, UNLOCK), (BORROW, DONE), (RETURN, UNLOCK), (RETURN, DONE)])
        self.assertEqual([dict(log) for log in self.db.list_logs()[2:]], first_logs)

    def test_rentals_newest_first(self):
        self.borrow(self.yamada, now=NOW)
        self.give_back(self.yamada, NOW + timedelta(hours=1))
        self.borrow(self.mori, now=NOW + timedelta(hours=2))

        rentals = self.db.list_rentals()
        self.assertEqual([r["borrower_name"] for r in rentals], ["森 航太郎", "山田 太郎"])
        self.assertIsNone(rentals[0]["returned_at"])

    def test_unfinished_unlock_is_cancelled_at_start(self):
        self.db.start(BORROW, self.yamada, do_nothing, due_at=NOW)
        self.assertIsNotNone(self.db.close_unfinished())
        self.assertEqual(self.steps()[-1], (BORROW, CANCEL))
        self.assertIsNone(self.db.close_unfinished())   # 2回目は何もしない


if __name__ == "__main__":
    unittest.main()
