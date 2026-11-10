"""
RC-S380 単体確認プログラム

アプリ本体を起動せずに、カードリーダーだけを確認します。
社員証をかざすと、カードの種類と「カードID」を表示します。
表示されたカードIDを manage_data.py add-user で登録してください。

使い方:
    python tools/check_card_reader.py            何枚でも続けて読む(Ctrl+C で終了)
    python tools/check_card_reader.py --once     1枚読んだら終了
    python tools/check_card_reader.py --device usb:054c:06c3

※ 実装済み・実機未確認
"""

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

# tools フォルダから実行しても、プロジェクトのファイルを読み込めるようにする
PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIRECTORY))

import config  # noqa: E402  (上の sys.path 設定の後で読み込む必要があるため)
from camera_rental.database import Database  # noqa: E402
from camera_rental.hardware.card_reader import identifier_to_card_id  # noqa: E402


def print_troubleshooting(error):
    print()
    print("カードリーダーを開けませんでした。")
    print(f"  詳細: {error}")
    print()
    print("確認すること:")
    print("  1. RC-S380 が USB に接続されているか")
    print("  2. Linux: python -m nfc を実行し、表示される案内(udev ルール等)に従ったか")
    print("     Permission denied → udev ルール未設定、または再ログインが必要")
    print("     Device or resource busy → 別のプログラム(アプリ本体など)が使用中")
    print("  3. Windows: Zadig で RC-S380 のドライバーを WinUSB に変更したか")
    print("     (変更すると Sony の NFC ポートソフトウェアでは使えなくなります)")


def find_registered_user(card_id):
    """登録済みの利用者か調べる(DB がなければ None)"""
    database_path = config.DEMO_DATABASE_PATH if config.DEMO_MODE else config.DATABASE_PATH
    if not database_path.exists():
        return None
    database = Database(database_path)
    return database.find_user_by_card_id(card_id)


def main():
    parser = argparse.ArgumentParser(description="RC-S380 単体確認")
    parser.add_argument("--once", action="store_true", help="1枚読んだら終了する")
    parser.add_argument("--device", default=config.CARD_READER_DEVICE, help="nfcpy のデバイス指定")
    arguments = parser.parse_args()

    # 部品の中のログ(エラーの詳細など)もコンソールに表示する
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        import nfc
    except ImportError:
        print("nfcpy がインストールされていません: pip install nfcpy")
        return 1

    try:
        frontend = nfc.ContactlessFrontend(arguments.device)
    except OSError as error:
        print_troubleshooting(error)
        return 1

    print(f"カードリーダー: {frontend}")
    print(f"読み取り対象: {', '.join(config.CARD_TARGETS)}")
    print("社員証をかざしてください(Ctrl+C で終了)")
    print()

    stop_event = threading.Event()

    def on_connect(tag):
        # カードがかざされたときに呼ばれる
        card_id = identifier_to_card_id(tag.identifier)
        print("------------------------------------------")
        print(f"カードの種類 : {tag.type}  ({tag})")
        print(f"カードID     : {card_id}")

        user = find_registered_user(card_id)
        if user is None:
            print("登録状況     : 未登録(または DB 未作成)")
        else:
            print(f"登録状況     : 登録済み 社員番号 {user.employee_number} / {user.name} / {user.active_label}")
        print("------------------------------------------")
        print("カードを離してください")

        # True を返すと、カードが離されるまで connect() が待つ
        return True

    try:
        while not stop_event.is_set():
            result = frontend.connect(
                rdwr={
                    "targets": config.CARD_TARGETS,
                    "on-connect": on_connect,
                },
                terminate=stop_event.is_set,
            )
            if result is False:
                # Ctrl+C や通信エラー
                break
            if arguments.once:
                break
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        frontend.close()
        print("終了しました")

    return 0


if __name__ == "__main__":
    sys.exit(main())
