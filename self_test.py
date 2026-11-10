"""
自己診断テスト(ハードウェア不要)

使い方:
    python self_test.py            結果だけ表示
    python self_test.py --verbose  テストごとの結果も表示

すべて成功すると、最後に次のように表示されます。

    SELF TEST: OK

【テスト方法に unittest を選んだ理由】
    ・Python 標準ライブラリなので、pip install なしで Windows でも Pi でも動く
    ・tests フォルダのテストを自動で集めてくれる(discover)
    ・pytest を入れた場合も、そのまま pytest で実行できる
    独自の self_test だけで書くと、テストが増えたときに管理しにくいため、
    「中身は unittest、入口は self_test.py」という形にしました。
"""

import argparse
import logging
import platform
import sqlite3
import sys
import unittest
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="自己診断テスト")
    parser.add_argument("--verbose", action="store_true", help="テストごとの結果を表示する")
    arguments = parser.parse_args()

    project_directory = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_directory))

    # テスト中の想定どおりの警告ログで画面が埋まらないようにする
    logging.disable(logging.CRITICAL)

    print("========== SELF TEST ==========")
    print(f"Python  : {sys.version.split()[0]}")
    print(f"SQLite  : {sqlite3.sqlite_version}")
    print(f"OS      : {platform.platform()}")
    print("===============================")

    loader = unittest.TestLoader()
    test_suite = loader.discover(
        start_dir=str(project_directory / "tests"),
        top_level_dir=str(project_directory),
    )

    verbosity = 2 if arguments.verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(test_suite)

    print()
    print(f"実行: {result.testsRun} 件 / 失敗: {len(result.failures)} 件 / "
          f"エラー: {len(result.errors)} 件 / スキップ: {len(result.skipped)} 件")
    for skipped_test, reason in result.skipped:
        print(f"  スキップ: {skipped_test.id()}  理由: {reason}")

    if result.wasSuccessful():
        print("SELF TEST: OK")
        return 0

    print("SELF TEST: FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
