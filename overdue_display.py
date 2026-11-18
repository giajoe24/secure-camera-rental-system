# 追加機能: 期限切れの表示(config.USE_OVERDUE_DISPLAY)
# 返却予定を過ぎていたら、ホームの状態の下に「返却予定を ○分 過ぎています」を出す。
# 目立たせすぎないよう、点滅はさせず、黄色の枠と文字で出す。
# 30 秒ごとに分数だけ書き換える(画面は作り直さない)

import tkinter
from datetime import datetime

from db import minutes_past, parse_time
from gui_parts import WHITE, YELLOW_TAG, format_minutes, make_label, make_tag


def show_on_home(home, rental):
    if rental is None:
        return

    due_at = parse_time(rental["due_at"])
    box = tkinter.Frame(home.top_area, bg=YELLOW_TAG[1], highlightthickness=1, highlightbackground=YELLOW_TAG[0])
    make_tag(box, "  期限切れ  ", (WHITE, YELLOW_TAG[0])).pack(side="left", padx=8, pady=6)
    label = make_label(box, "", 17, True, YELLOW_TAG[0])
    label.pack(side="left", padx=(0, 8))

    def update():
        late = minutes_past(due_at, datetime.now())
        if late > 0:
            text = f"返却予定を {format_minutes(late)} 過ぎています。早めに返してください。"
            if label.cget("text") != text:   # 変わったときだけ書き換える
                label.configure(text=text)
            if not box.winfo_ismapped():
                box.pack(anchor="w", fill="x", pady=(8, 0))
        home.run_later(30 * 1000, update)

    update()
