# 設定

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "camera_rental.sqlite3"
LOG_PATH = BASE_DIR / "logs" / "camera_rental.log"
EXPORT_DIR = BASE_DIR / "exports"   # Excel の保存先

# ---- 動かし方 ----
MUST_ONLY = False       # True にすると追加機能を全部止めて、MUST だけの動きになる
USE_HARDWARE = True     # False にすると PC で試せる(社員証と扉はテスト用ウィンドウのボタンで代わりにする)

CAMERA_NAME = "セキュアカメラ"
ITEM_NAME = "カメラ"    # 箱から取り出すもの。画面の「○○を取り出して」に使う

# 貸出時間の選択肢(分)
RENTAL_MINUTES = [15, 30, 60, 120, 240, 480]

# 電磁ロック
LOCK_GPIO_PIN = 18        # BCM 番号
LOCK_ACTIVE_HIGH = True   # Low で動くリレーなら False

# 解錠パルス(実機では 2ms で外れたので 5ms にしている)
UNLOCK_PULSE_COUNT = 1
UNLOCK_PULSE_ON_SECONDS = 0.005
UNLOCK_PULSE_OFF_SECONDS = 0.2    # 2回以上出すときの間隔

# LE-53 のマイクロスイッチ(COM → GND、NO → この GPIO、外付け 10kΩ でプルアップ)
LOCK_SWITCH_GPIO_PIN = 23

# カードリーダー
CARD_READER_PATH = "usb"
CARD_TARGETS = ["212F", "106A", "106B"]  # FeliCa / Type A / Type B

# 待ち時間(秒)。MTG では 10〜30 秒で、実機で確かめてから決めることになった
CARD_WAIT_SECONDS = 30        # 社員証をかざすのを待つ
IDLE_SECONDS = 30             # 操作がないとホームに戻る
UNLOCK_WAIT_SECONDS = 30   # 解錠してから扉が開かれるのを待つ(過ぎたら取り消し)
UNLOCKED_WARN_SECONDS = 60  # 扉が開いたままこれだけたったら警告を出す
DONE_SCREEN_SECONDS = 5       # 完了画面を出しておく

# 日本語入力(管理画面の氏名)。fcitx5 + Mozc を入れておく(docs/日本語入力の設定.txt)
INPUT_METHOD = "fcitx"

# 画面(7インチ 800×480 のタッチモニター)
FULLSCREEN = True         # PC で試すときは False(Esc でも解除できる)

# ログファイル(容量がいっぱいにならないよう、1MB ごとに分けて 5 つまで残す)
LOG_FILE_BYTES = 1_000_000
LOG_FILE_COUNT = 5

# ---- 追加機能 ----
# 使うものだけ True にする

USE_OVERDUE_DISPLAY = True   # 期限切れをホームに控えめに出す(overdue_display.py)
USE_OVERDUE_RECORD = True    # 何分遅れて返したかを出す(overdue_record.py)

USE_LONG_RENTAL = True       # 日をまたぐ貸出(出張など)(long_rental.py)
LONG_RENTAL_MAX_DAYS = 31    # 何日先まで借りられるか
LONG_RENTAL_DEFAULT_HOUR = 17  # はじめに出しておく返却時刻(明日の○時)

USE_EXTEND = True            # 返却予定の延長(extend.py)
EXTEND_MINUTES = [15, 30, 60, 120]

USE_BACKUP = True            # DB を1日1回バックアップ(backup.py)
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_KEEP_DAYS = 31        # 記録は最低1か月残す決まりなので、それより長く

USE_ADMIN_SCREEN = True      # 管理画面(admin_screen.py)。OFF なら登録は register.py で
USE_EVENTS = True            # できごとの記録(events.py):未登録カード、不正な開放、閉め忘れ、エラー
USE_FORCED_OPEN_CHECK = True # 解錠していないのに扉が開いたら警告する(forced_open.py)

USE_USER_INFO = True         # 利用者の部署と、利用停止・再開(user_info.py)

USE_STORAGE_CHECK = True     # 容量と DB の見張り(storage_check.py)
LOW_SPACE_MB = 500           # SD カードの空きがこれより少なくなったら警告
EXPORT_KEEP_DAYS = 31        # exports/ の日時入りファイルを何日残すか

# ---- フラグの組み合わせ(ここは触らなくてよい) ----
if MUST_ONLY:
    USE_OVERDUE_DISPLAY = False
    USE_OVERDUE_RECORD = False
    USE_EXTEND = False
    USE_LONG_RENTAL = False
    USE_BACKUP = False
    USE_ADMIN_SCREEN = False
    USE_EVENTS = False
    USE_FORCED_OPEN_CHECK = False
    USE_STORAGE_CHECK = False
    USE_USER_INFO = False

if not USE_HARDWARE:
    FULLSCREEN = False   # PC ではウィンドウで出す
