# 追加機能: 容量と DB の見張り(config.USE_STORAGE_CHECK)
#   ・SD カードの空きが LOW_SPACE_MB より少なくなったら、できごとに記録してホームに警告を出す
#   ・exports/ の古いファイル(EXPORT_KEEP_DAYS 日より前)と、書きかけで残った .tmp を消す
#   ・起動したときに DB が壊れていないか点検する(PRAGMA quick_check)
# 起動時と、そのあと 1 時間ごとに動く(main.py から start_watch を呼ぶ)

import logging
import shutil
import time

import config
import events

log = logging.getLogger(__name__)

low_space = False   # 今、空きが少ないか(ホームの警告に使う)


def free_mb():
    # プログラムのフォルダがある場所(SD カード)の空き容量(MB)
    return shutil.disk_usage(config.BASE_DIR).free // (1024 * 1024)


def check_space(database):
    global low_space
    mb = free_mb()
    was_low = low_space
    low_space = mb < config.LOW_SPACE_MB
    if low_space and not was_low:   # 少なくなった最初の 1 回だけ記録する
        log.warning("SD カードの空きが少なくなっています: %sMB", mb)
        events.add_event(database, events.LOW_SPACE, f"SD カードの空きが {mb}MB(基準 {config.LOW_SPACE_MB}MB)")
    return mb


def delete_old_files():
    # 消したファイルの数を返す
    if not config.EXPORT_DIR.exists():
        return 0
    oldest_time = time.time() - config.EXPORT_KEEP_DAYS * 24 * 60 * 60
    count = 0
    for file in config.EXPORT_DIR.iterdir():
        if file.name == "rental_log.xlsx":
            continue   # いつも最新にしているファイルは消さない
        if file.suffix == ".tmp" or file.stat().st_mtime < oldest_time:
            file.unlink()
            count += 1
            log.info("古いファイルを消しました: %s", file.name)
    return count


def check_db(database):
    # DB が壊れていなければ True
    result = database.select_one("PRAGMA quick_check")[0]
    if result == "ok":
        return True
    log.error("DB の点検で異常が見つかりました: %s", result)
    events.add_event(database, events.ERROR, f"DB の点検で異常: {result}")
    return False


def start_watch(app):
    check_db(app.database)
    watch(app)


def watch(app):
    try:
        delete_old_files()
        check_space(app.database)
    except Exception:
        log.exception("容量の見張りでエラー")   # 見張りの失敗で貸出は止めない
    app.after(60 * 60 * 1000, lambda: watch(app))
