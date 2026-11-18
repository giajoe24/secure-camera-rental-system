# 起動
#   python main.py

import logging
from logging.handlers import RotatingFileHandler

import admin_screen
import backup
import config
from card_reader import NfcCardReader
from db import Database
from gui import App
from lock import GpioLock


def setup_log():
    # ログファイルは決まった大きさで分けて、古いものから消す(容量不足で止まらないように)
    config.LOG_PATH.parent.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(config.LOG_PATH, maxBytes=config.LOG_FILE_BYTES,
                                       backupCount=config.LOG_FILE_COUNT, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(), file_handler],
    )


def main():
    setup_log()
    logging.info("起動")

    database = Database(config.DB_PATH)
    database.create_tables()
    admin_screen.create_admin_table(database)

    # 前回、解錠したまま止まっていたら取り消しにしておく
    unfinished = database.close_unfinished()
    if unfinished is not None:
        logging.warning("途中で止まっていた%sを取り消しました", unfinished["action"])

    card_reader = NfcCardReader(config.CARD_READER_PATH, config.CARD_TARGETS)
    lock = GpioLock(config.LOCK_GPIO_PIN, config.LOCK_ACTIVE_HIGH, config.LOCK_SWITCH_GPIO_PIN)

    app = App(database, card_reader, lock)

    # 追加機能: DB のバックアップ
    if config.USE_BACKUP:
        backup.start_daily_backup(app)
    try:
        app.mainloop()
    finally:
        lock.close()  # 終わるときは必ず GPIO を OFF にする


if __name__ == "__main__":
    main()
