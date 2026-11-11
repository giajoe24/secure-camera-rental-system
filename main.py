"""
セキュアカメラ貸出管理システム 起動ファイル

使い方:
    python main.py              設定ファイル(config.py)の DEMO_MODE に従って起動
    python main.py --demo       デモモードで起動
    python main.py --real       実機モードで起動
    python main.py --demo --demo-unlock-fail
                                デモモードで「解錠失敗」を再現する
    python main.py --demo --demo-lock-sensor
                                デモモードで施錠センサー(扉の開け閉め)を再現する
    python main.py --fullscreen 全画面で起動
"""

import argparse
import logging
import sys
from datetime import datetime

import config
from camera_rental import errors
from camera_rental.app_logging import setup_logging
from camera_rental.database import Database
from camera_rental.hardware import create_card_reader, create_lock_controller, create_lock_sensor
from camera_rental.rental_service import RentalService

logger = logging.getLogger("main")


def parse_arguments():
    parser = argparse.ArgumentParser(description="セキュアカメラ貸出管理システム")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--demo", action="store_true", help="デモモードで起動する")
    mode_group.add_argument("--real", action="store_true", help="実機モードで起動する")

    parser.add_argument("--demo-unlock-fail", action="store_true",
                        help="デモモードで解錠失敗を再現する(1回おきに失敗)")
    parser.add_argument("--demo-lock-sensor", action="store_true",
                        help="デモモードで施錠センサー(扉の開け閉め)を再現する")
    parser.add_argument("--fullscreen", action="store_true", help="全画面で起動する")
    return parser.parse_args()


def decide_demo_mode(arguments):
    """起動オプションがあればそれを優先し、なければ config.DEMO_MODE を使う"""
    if arguments.demo:
        return True
    if arguments.real:
        return False
    return config.DEMO_MODE


def prepare_database(demo_mode):
    """データベースを準備する(デモモードならデモデータも登録する)"""
    if demo_mode:
        database_path = config.DEMO_DATABASE_PATH
    else:
        database_path = config.DATABASE_PATH

    database = Database(database_path)
    database.initialize()

    if demo_mode:
        database.seed_demo_data(
            demo_users=config.DEMO_USERS,
            demo_cameras=config.DEMO_CAMERAS,
            disabled_employee_numbers=config.DEMO_DISABLED_EMPLOYEE_NUMBERS,
            created_at=datetime.now(),
        )

    problems = database.find_inconsistencies()
    for problem in problems:
        logger.warning("データの食い違い: %s", problem)

    return database


def main():
    arguments = parse_arguments()
    log_file_path = setup_logging(config.LOG_DIRECTORY)

    demo_mode = decide_demo_mode(arguments)
    if arguments.demo_unlock_fail:
        config.DEMO_SIMULATE_UNLOCK_FAILURE = True
    if arguments.demo_lock_sensor:
        config.DEMO_USE_LOCK_SENSOR = True
    if arguments.fullscreen:
        config.FULLSCREEN = True

    mode_name = "デモモード" if demo_mode else "実機モード"
    logger.info("起動します: %s / Python %s / ログ %s", mode_name, sys.version.split()[0], log_file_path)

    # CustomTkinter はここで読み込む
    # (入っていない場合に、分かりやすいメッセージを出すため)
    try:
        from camera_rental.gui.app import CameraRentalApp
    except ImportError as error:
        print("CustomTkinter が読み込めません。次のコマンドでインストールしてください。")
        print("    pip install -r requirements.txt")
        print(f"詳細: {error}")
        return 1

    try:
        database = prepare_database(demo_mode)
    except errors.CameraRentalError as error:
        logger.error("データベースを準備できませんでした: %s", error.detail)
        print(f"{error.title}\n{error.user_message}")
        return 1

    card_reader = create_card_reader(config, demo_mode)
    lock_controller = create_lock_controller(config, demo_mode)
    lock_sensor = create_lock_sensor(config, demo_mode)

    if not lock_controller.is_ready:
        # アプリは起動し、ホーム画面で「貸出・返却停止中」を表示する
        logger.error("電磁ロックが使用できません: %s", lock_controller.not_ready_reason)

    if not lock_sensor.is_available:
        # センサーは補助の機能なので、使えなくても貸出・返却は続ける
        logger.info("施錠センサーは使いません: %s", lock_sensor.not_available_reason)

    service = RentalService(
        database=database,
        lock_controller=lock_controller,
        rental_hours_options=config.RENTAL_HOURS_OPTIONS,
        unlock_seconds=config.UNLOCK_SECONDS,
        export_directory=config.EXPORT_DIRECTORY,
        lock_sensor=lock_sensor,
    )

    app = CameraRentalApp(
        service=service,
        card_reader=card_reader,
        settings=config,
        demo_mode=demo_mode,
    )
    app.protocol("WM_DELETE_WINDOW", app.close)

    try:
        app.mainloop()
    finally:
        # どんな終わり方をしても、電磁ロックを施錠状態に戻して GPIO を解放する
        lock_controller.close()
        lock_sensor.close()
        logger.info("終了しました")

    return 0


if __name__ == "__main__":
    sys.exit(main())
