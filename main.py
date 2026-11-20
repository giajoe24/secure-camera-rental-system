# 起動
#   python main.py

import logging
import os
from logging.handlers import RotatingFileHandler

import admin_screen
import backup
import config
import events
import export
import pc_test
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


def setup_japanese_input():
    # 管理画面の氏名を USB キーボードで日本語入力できるようにする(手順は docs/日本語入力の設定.txt)
    # tkinter は XIM というしくみで fcitx5 とつながる。XMODIFIERS がないとつながらないので、
    # 自動起動などで設定されていないときはここで入れる(画面を作る前に入れる必要がある)
    os.environ.setdefault("XMODIFIERS", f"@im={config.INPUT_METHOD}")


def main():
    setup_log()
    logging.info("起動")

    database = Database(config.DB_PATH)
    database.create_tables()
    admin_screen.create_admin_table(database)
    events.create_events_table(database)

    # 前回、解錠したまま止まっていたら取り消しにしておく
    unfinished = database.close_unfinished()
    if unfinished is not None:
        logging.warning("途中で止まっていた%sを取り消しました", unfinished["action"])
    export.update_excel(database)

    if config.USE_HARDWARE:
        card_reader = NfcCardReader(config.CARD_READER_PATH, config.CARD_TARGETS)
        lock = GpioLock(config.LOCK_GPIO_PIN, config.LOCK_ACTIVE_HIGH, config.LOCK_SWITCH_GPIO_PIN)
    else:
        # PC で試すとき:機器の代わりを使い、操作用のテストウィンドウを出す
        card_reader = pc_test.PcCardReader()
        lock = pc_test.PcLock()

    setup_japanese_input()
    app = App(database, card_reader, lock)
    app.tk.call("tk", "useinputmethods", "1")   # 入力欄で日本語入力を使う
    if not config.USE_HARDWARE:
        pc_test.TestWindow(app, card_reader, lock)

    # 追加機能: DB のバックアップ
    if config.USE_BACKUP:
        backup.start_daily_backup(app)

    try:
        app.mainloop()
    finally:
        lock.close()  # 終わるときは必ず GPIO を OFF にする


if __name__ == "__main__":
    main()
