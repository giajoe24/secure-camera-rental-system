# 追加機能: できごとの記録(config.USE_EVENTS)
# 貸出・返却(logs)とは別に、管理者が知っておきたいことを残す。これも追加するだけ。
#   未登録カード   登録されていない社員証がかざされた
#   不正な開放     解錠していないのに扉が開いた
#   閉め忘れ       扉が開いたまま一定時間たった
#   エラー         解錠の失敗、カードリーダーの故障など

import logging
from datetime import datetime

import config
from db import TIME_FORMAT

log = logging.getLogger(__name__)

UNKNOWN_CARD = "未登録カード"
FORCED_OPEN = "不正な開放"
LEFT_OPEN = "閉め忘れ"
ERROR = "エラー"


def create_events_table(database):
    database.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id     INTEGER PRIMARY KEY,
            time   TEXT NOT NULL,
            kind   TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        )
    """)


def add_event(database, kind, detail=""):
    # 記録に失敗しても、貸出・返却は止めない
    if not config.USE_EVENTS:
        return
    try:
        database.execute("INSERT INTO events (time, kind, detail) VALUES (?, ?, ?)",
                         (datetime.now().strftime(TIME_FORMAT), kind, detail))
    except Exception:
        log.exception("できごとを記録できませんでした: %s %s", kind, detail)


def list_events(database):
    # 新しい順
    return database.select_all("SELECT * FROM events ORDER BY id DESC")
