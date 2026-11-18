# 追加機能: 延滞の記録(config.USE_OVERDUE_RECORD)
# 返却日時 - 返却予定 で何分遅れたかを出す(DB に列は増やさない)
# 返却の完了画面と、履歴(管理画面 / CSV / Excel)で使う

from datetime import datetime

from db import minutes_past, parse_time
from gui_parts import YELLOW_TAG, make_label


def late_minutes_of(rental):
    # 何分遅れて返したか。まだ返していなければ None
    if rental["returned_at"] is None:
        return None
    return minutes_past(parse_time(rental["due_at"]), parse_time(rental["returned_at"]))


def late_text(rental):
    # 表や CSV 用の文字(例: "25"、"0"、"貸出中")
    late = late_minutes_of(rental)
    if late is None:
        return "貸出中"
    return str(late)


def show_on_done(done, due_at_text):
    late = minutes_past(parse_time(due_at_text), datetime.now())
    if late > 0:
        text = f"返却予定より {late}分 遅れての返却でした。"
        make_label(done.top_area, text, 18, True, YELLOW_TAG[0]).pack(anchor="w", pady=(8, 0))
