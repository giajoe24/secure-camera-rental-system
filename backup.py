# 追加機能: DB のバックアップ(config.USE_BACKUP)
# 起動時と1時間ごとに見て、今日の分がなければ backups/ にコピーを作る。
# BACKUP_KEEP_DAYS 日より古いものは消す。

import logging
import sqlite3
from datetime import date, datetime, timedelta

import config

log = logging.getLogger(__name__)

NAME_FORMAT = "camera_rental_%Y%m%d.sqlite3"


def backup_path_for(day):
    return config.BACKUP_DIR / day.strftime(NAME_FORMAT)


def make_backup(day):
    # 作ったらそのパス、作らなかったら None を返す
    path = backup_path_for(day)
    if path.exists() or not config.DB_PATH.exists():
        return None

    config.BACKUP_DIR.mkdir(exist_ok=True)
    source = sqlite3.connect(config.DB_PATH)
    copy = sqlite3.connect(path)
    try:
        source.backup(copy)   # 使用中の DB でも安全にコピーできる
    finally:
        copy.close()
        source.close()

    log.info("バックアップを作りました: %s", path)
    return path


def delete_old_backups(today):
    if not config.BACKUP_DIR.exists():
        return
    oldest = today - timedelta(days=config.BACKUP_KEEP_DAYS - 1)
    for file in config.BACKUP_DIR.glob("camera_rental_*.sqlite3"):
        try:
            day = datetime.strptime(file.name, NAME_FORMAT).date()
        except ValueError:
            continue
        if day < oldest:
            file.unlink()
            log.info("古いバックアップを消しました: %s", file)


def backup_if_needed():
    try:
        make_backup(date.today())
        delete_old_backups(date.today())
    except Exception:
        log.exception("バックアップに失敗しました")  # 貸出は止めない


def start_daily_backup(app):
    backup_if_needed()
    app.after(60 * 60 * 1000, lambda: start_daily_backup(app))

