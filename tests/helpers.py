"""
テストで共通して使う道具

    TemporaryDatabaseTestCase:
        テストごとに一時フォルダへ新しい SQLite ファイルを作り、
        テストの最後に「ファイルを削除できること」まで確認します。

        Windows では、接続が1つでも閉じられていないと
        ファイル削除で WinError 32 になります。
        そのため tearDown で毎回削除することで、
        「接続の閉じ忘れ」をすべてのテストで自動的に検出できます。
        (Linux では開いたままでも削除できてしまうので、
         open_connection_count が 0 であることも合わせて確認します)
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from camera_rental import errors
from camera_rental.database import Database


# テストで使う固定の時刻
FIXED_NOW = datetime(2026, 11, 10, 9, 0, 0)


class FakeLockController:
    """
    テスト用のロック

    unlock() が呼ばれた回数を数え、必要なら失敗させられます。
    「DB記録に失敗したら解錠しない」ことの確認に使います。
    """

    def __init__(self, fail_unlock=False, is_ready=True):
        self.fail_unlock = fail_unlock
        self.is_ready = is_ready
        self.not_ready_reason = "" if is_ready else "テスト: GPIO 初期化失敗"
        self.unlock_calls = []

    def unlock(self, seconds):
        self.unlock_calls.append(seconds)
        if self.fail_unlock:
            raise errors.UnlockError(detail="テスト: 解錠失敗")

    def close(self):
        pass


class TemporaryDatabaseTestCase(unittest.TestCase):
    """一時データベースを使うテストの親クラス"""

    def setUp(self):
        self.temporary_directory = Path(tempfile.mkdtemp(prefix="camera_rental_test_"))
        self.database_path = self.temporary_directory / "test.sqlite3"
        self.database = Database(self.database_path)
        self.database.initialize()

    def tearDown(self):
        # 1. 開いている接続が残っていないこと
        self.assertEqual(
            self.database.open_connection_count,
            0,
            "SQLite の接続が閉じられていません",
        )

        # 2. DB ファイルを削除できること(Windows の WinError 32 対策の確認)
        if self.database_path.exists():
            os.remove(self.database_path)
        self.assertFalse(self.database_path.exists())

        shutil.rmtree(self.temporary_directory)

    # ---------- データ準備 ----------

    def add_user(self, employee_number="10001", name="テスト 太郎", card_id="CARD0001", is_active=True):
        return self.database.add_user(employee_number, name, card_id, FIXED_NOW, is_active=is_active)

    def add_camera(self, name="テストカメラ1号機"):
        return self.database.add_camera(name, FIXED_NOW)
