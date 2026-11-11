"""
データの入れ物(モデル)の定義

SQLite から取り出した1行を、名前付きで扱えるようにするためのクラスです。
row[3] のような番号ではなく、user.name のように書けるので読みやすくなります。
"""

from dataclasses import dataclass
from datetime import datetime


# --------------------------------------------------
# 日時の扱い
# --------------------------------------------------

# SQLite には日時を「2026-11-10 20:15:00」の文字列で保存します。
# この形式なら文字列のまま大小比較(古い/新しい)ができ、人が見ても分かります。
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# 画面表示用の形式(秒は不要なので省略)
DISPLAY_DATETIME_FORMAT = "%Y/%m/%d %H:%M"


def format_compact(value):
    """一覧表示用の短い形式(例: 26/11/10 20:15)。None は「-」"""
    if value is None:
        return "-"
    return value.strftime("%y/%m/%d %H:%M")


def datetime_to_text(value):
    """datetime を SQLite 保存用の文字列に変換する"""
    return value.strftime(DATETIME_FORMAT)


def text_to_datetime(text):
    """SQLite に保存した文字列を datetime に戻す(None はそのまま返す)"""
    if text is None:
        return None
    return datetime.strptime(text, DATETIME_FORMAT)


def format_for_display(value):
    """datetime を画面表示用の文字列にする(None は「-」)"""
    if value is None:
        return "-"
    return value.strftime(DISPLAY_DATETIME_FORMAT)


# --------------------------------------------------
# カメラの状態
# --------------------------------------------------

# DB には英語の値を保存し、画面には日本語で表示します。
# (表示名を変えたくなっても DB を変更せずに済むため)
CAMERA_STATUS_AVAILABLE = "available"
CAMERA_STATUS_RENTED = "rented"
CAMERA_STATUS_MAINTENANCE = "maintenance"

CAMERA_STATUS_LABELS = {
    CAMERA_STATUS_AVAILABLE: "貸出可能",
    CAMERA_STATUS_RENTED: "貸出中",
    CAMERA_STATUS_MAINTENANCE: "点検中",
}


# --------------------------------------------------
# 貸出の終了理由
# --------------------------------------------------

# 通常の返却
END_REASON_RETURNED = "returned"

# 貸出は記録されたが解錠できず、取り消した
END_REASON_CANCELLED = "cancelled_unlock_failed"

# 管理者がコマンドで強制的に返却扱いにした
END_REASON_ADMIN = "admin_force_return"

END_REASON_LABELS = {
    END_REASON_RETURNED: "返却",
    END_REASON_CANCELLED: "取消(解錠失敗)",
    END_REASON_ADMIN: "管理者返却",
}


# --------------------------------------------------
# モデル
# --------------------------------------------------

@dataclass
class User:
    """利用者(社員)"""

    id: int
    employee_number: str
    name: str
    card_id: str
    is_active: bool

    @property
    def active_label(self):
        """利用可否を日本語で返す"""
        if self.is_active:
            return "利用可"
        return "利用停止"


@dataclass
class Camera:
    """カメラ"""

    id: int
    name: str
    status: str

    @property
    def status_label(self):
        """状態を日本語で返す(色だけで状態を示さないため、必ず文字も出す)"""
        return CAMERA_STATUS_LABELS.get(self.status, self.status)

    @property
    def is_available(self):
        return self.status == CAMERA_STATUS_AVAILABLE


@dataclass
class Rental:
    """貸出記録(1回の貸出〜返却で1行)"""

    id: int
    user_id: int
    camera_id: int
    rental_hours: int
    rented_at: datetime
    due_at: datetime
    returned_at: datetime | None
    end_reason: str | None

    # 一覧表示用に JOIN で取ってくる情報
    employee_number: str = ""
    user_name: str = ""
    camera_name: str = ""

    @property
    def is_returned(self):
        """返却済みかどうか(returned_at が入っていれば返却済み)"""
        return self.returned_at is not None

    @property
    def state_label(self):
        """未返却 / 返却済み などを日本語で返す"""
        if not self.is_returned:
            return "未返却"
        return END_REASON_LABELS.get(self.end_reason, "返却済み")

    def is_overdue(self, now):
        """返却予定日時を過ぎて、まだ返却されていないか"""
        if self.is_returned:
            return False
        return now > self.due_at


@dataclass
class CameraStatusRow:
    """ホーム画面の一覧の1行分(カメラ + 貸出中なら借りている人)"""

    camera: Camera
    rental: Rental | None
