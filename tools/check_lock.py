"""
電磁ロック(GPIO)単体確認プログラム

アプリ本体を起動せずに、GPIO 出力だけを確認します。

【必ず守ってください】
    ・最初は電磁ロックをつながず、LED(抵抗付き)かテスターで GPIO 出力を確認する
    ・電磁ロックを Raspberry Pi の GPIO に直接つながない(リレー / MOSFET 経由)
    ・詳しくは README の「安全上の注意」を読んでください

使い方:
    python tools/check_lock.py                  config.py の設定で1回解錠
    python tools/check_lock.py --seconds 3      3秒だけ解錠
    python tools/check_lock.py --pin 17         GPIO17 で試す
    python tools/check_lock.py --active-low     active low の回路で試す
    python tools/check_lock.py --repeat 3       3回くり返す(5秒間隔)
    python tools/check_lock.py --dry-run        GPIO を使わずに流れだけ確認

※ 実装済み・実機未確認
"""

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIRECTORY))

import config  # noqa: E402
from camera_rental import errors  # noqa: E402
from camera_rental.hardware.lock_controller import DemoLockController, GpioLockController  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="電磁ロック(GPIO)単体確認")
    parser.add_argument("--pin", type=int, default=config.LOCK_GPIO_PIN, help="GPIO 番号(BCM)")
    parser.add_argument("--seconds", type=float, default=config.UNLOCK_SECONDS, help="解錠する秒数")
    parser.add_argument("--repeat", type=int, default=1, help="くり返す回数")
    parser.add_argument("--dry-run", action="store_true", help="GPIO を使わずに流れだけ確認する")

    level_group = parser.add_mutually_exclusive_group()
    level_group.add_argument("--active-high", action="store_true", help="High で解錠する回路")
    level_group.add_argument("--active-low", action="store_true", help="Low で解錠する回路")
    arguments = parser.parse_args()

    # 部品の中のログ(エラーの詳細など)もコンソールに表示する
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    active_high = config.LOCK_ACTIVE_HIGH
    if arguments.active_high:
        active_high = True
    if arguments.active_low:
        active_high = False

    print("========== 電磁ロック確認 ==========")
    print(f"GPIO 番号   : {arguments.pin}(BCM 番号)")
    print(f"解錠時間    : {arguments.seconds} 秒")
    print(f"出力論理    : {'active high(High で解錠)' if active_high else 'active low(Low で解錠)'}")
    print(f"くり返し    : {arguments.repeat} 回")
    print(f"ドライラン  : {'はい(GPIO 出力なし)' if arguments.dry_run else 'いいえ(実際に出力します)'}")
    print("====================================")
    print("※ 電磁ロックを GPIO に直接つないでいないことを確認してください。")

    answer = input("実行してよければ y を入力して Enter: ")
    if answer.strip().lower() != "y":
        print("中止しました")
        return 0

    if arguments.dry_run:
        lock_controller = DemoLockController()
    else:
        lock_controller = GpioLockController(gpio_pin=arguments.pin, active_high=active_high)

    if not lock_controller.is_ready:
        print("GPIO を準備できませんでした。")
        print(f"  詳細: {lock_controller.not_ready_reason}")
        print("  ・Raspberry Pi 上で実行しているか")
        print("  ・gpiozero と lgpio がインストールされているか(README 参照)")
        print("  ・他のプログラム(アプリ本体など)が同じ GPIO を使っていないか")
        return 1

    try:
        for count in range(1, arguments.repeat + 1):
            print(f"[{count}/{arguments.repeat}] 解錠します(出力 ON)")
            lock_controller.unlock(arguments.seconds)

            # 解錠中であることを1秒ごとに表示する
            remaining_seconds = arguments.seconds
            while remaining_seconds > 0:
                print(f"  解錠中… あと {remaining_seconds:.0f} 秒")
                wait_seconds = min(1, remaining_seconds)
                time.sleep(wait_seconds)
                remaining_seconds -= wait_seconds

            # タイマーが施錠に戻すのを少し待つ
            time.sleep(0.3)
            print("  施錠しました(出力 OFF)")

            if count < arguments.repeat:
                time.sleep(5)
    except errors.UnlockError as error:
        print(f"解錠に失敗しました: {error.detail}")
        return 1
    except KeyboardInterrupt:
        print("中断しました")
    finally:
        lock_controller.close()
        print("GPIO を解放しました(施錠状態)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
