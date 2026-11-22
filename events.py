# 追加機能: できごとの記録(config.USE_EVENTS)
# 貸出・返却(logs)とは別に、管理者が知っておきたいことを残す。これも追加するだけ。
#   未登録カード   登録されていない社員証がかざされた
#   不正な開放     解錠していないのに扉が開いた
#   閉め忘れ       扉が開いたまま一定時間たった
#   エラー         解錠の失敗、カードリーダーの故障、DB の異常など
#   期限切れ       返却予定を過ぎた(1 回の貸出につき 1 回)
#   容量不足       SD カードの空きが少ない

import logging
from datetime import datetime

import config
from db import TIME_FORMAT, parse_time

log = logging.getLogger(__name__)

UNKNOWN_CARD = "未登録カード"
FORCED_OPEN = "不正な開放"
LEFT_OPEN = "閉め忘れ"
ERROR = "エラー"
OVERDUE = "期限切れ"
LOW_SPACE = "容量不足"


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


def check_overdue(database, now=None):
    # 貸出中で返却予定を過ぎていたら「期限切れ」を記録する。同じ貸出では 1 回だけ。
    # 延長して返却予定が変わったら、その予定を過ぎたときにもう一度記録する
    if now is None:
        now = datetime.now()
    rental = database.current_rental()
    if rental is None or parse_time(rental["due_at"]) > now:
        return False

    detail = f"{rental['name']} さん(貸出 {rental['rented_at']} / 返却予定 {rental['due_at']})"
    already = database.select_one("SELECT 1 FROM events WHERE kind = ? AND detail = ?", (OVERDUE, detail))
    if already is not None:
        return False
    add_event(database, OVERDUE, detail)
    return True


def start_overdue_check(app):
    # main.py から呼ぶ。1 分ごとに確かめる
    try:
        check_overdue(app.database)
    except Exception:
        log.exception("期限切れの確認でエラー")
    app.after(60 * 1000, lambda: start_overdue_check(app))
