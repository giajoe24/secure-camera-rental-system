# 追加機能: 日をまたぐ貸出(出張など)(config.USE_LONG_RENTAL)
# 貸出時間の画面の「その他(日をまたぐ)」から、返却する日と時刻をボタンで選ぶ。
# 文字を打たずにタッチだけで選べるよう、◀ ▶ で 1 日 / 30 分ずつ動かす。
# 最長 LONG_RENTAL_MAX_DAYS 日先まで。

from datetime import datetime, timedelta

import customtkinter

import config
from gui_parts import (SUB_TEXT_COLOR, TEXT_COLOR, Screen, disable_button, enable_main_button, format_date_time,
                       make_label, make_sub_button)

WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


def first_due(now):
    # はじめに出しておく返却予定:明日の決まった時刻
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=config.LONG_RENTAL_DEFAULT_HOUR, minute=0, second=0, microsecond=0)


def limit_of(now):
    # 選べる一番遠い日時
    last_day = now + timedelta(days=config.LONG_RENTAL_MAX_DAYS)
    return last_day.replace(hour=23, minute=30, second=0, microsecond=0)


def check_due(due_at, now):
    # 選べない返却予定なら理由を返す。選べるなら None
    if due_at <= now + timedelta(minutes=15):
        return "返却予定は今から 15 分より後にしてください"
    if due_at > limit_of(now):
        return f"借りられるのは {config.LONG_RENTAL_MAX_DAYS} 日先までです"
    return None


def format_day(day):
    # 例: 11月25日(水)
    return f"{day.month}月{day.day}日({WEEKDAYS[day.weekday()]})"


class LongTimeScreen(Screen):
    # back_screen / next_screen: 「戻る」と「OK」で行く画面(screens.py から渡してもらう)
    def __init__(self, app, user, steps, back_screen, next_screen, due_at=None):
        super().__init__(app)
        self.user = user
        self.steps = steps
        self.back_screen = back_screen
        self.next_screen = next_screen
        if due_at is None:
            due_at = first_due(datetime.now())
        self.due_at = due_at

        self.show_steps(steps, 1)
        self.show_title("返却する日と時刻を選んでください",
                        f"{user['name']} さん  (最長 {config.LONG_RENTAL_MAX_DAYS} 日先まで)")

        self.add_left_button("戻る", self.go_back)
        self.ok_button = self.add_right_button("OK", self.go_next)
        self.due_label = self.add_footer_label()

        form = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        form.pack(fill="x")
        form.grid_columnconfigure(0, minsize=120)
        form.grid_columnconfigure(2, weight=1)

        make_label(form, "返却日", color=SUB_TEXT_COLOR).grid(row=0, column=0, sticky="w")
        self.day_label = self.make_stepper(form, 0, lambda: self.move(days=-1), lambda: self.move(days=1))
        week_button = make_sub_button(form, "+1週間", lambda: self.move(days=7), width=120, height=56)
        week_button.grid(row=0, column=4, padx=(12, 0), pady=6)

        make_label(form, "返却時刻", color=SUB_TEXT_COLOR).grid(row=1, column=0, sticky="w")
        self.time_label = self.make_stepper(form, 1, lambda: self.move(minutes=-30), lambda: self.move(minutes=30))

        self.show_due()

    def make_stepper(self, form, row, back, forward):
        # [◀] 値 [▶] の並び。値のラベルを返す
        make_sub_button(form, "◀", back, width=64, height=56).grid(row=row, column=1, pady=6)
        label = make_label(form, "", 24, True)
        label.configure(anchor="center", width=240)
        label.grid(row=row, column=2, sticky="ew", padx=8)
        make_sub_button(form, "▶", forward, width=64, height=56).grid(row=row, column=3, pady=6)
        return label

    def move(self, days=0, minutes=0):
        self.due_at = self.due_at + timedelta(days=days, minutes=minutes)
        self.show_due()

    def show_due(self):
        self.day_label.configure(text=format_day(self.due_at))
        self.time_label.configure(text=f"{self.due_at:%H:%M}")

        problem = check_due(self.due_at, datetime.now())
        if problem is None:
            self.due_label.configure(text=f"返却予定 {format_date_time(self.due_at)}", text_color=TEXT_COLOR)
            enable_main_button(self.ok_button)
        else:
            self.due_label.configure(text=problem, text_color=SUB_TEXT_COLOR)
            disable_button(self.ok_button)

    def go_back(self):
        self.app.show(self.back_screen, user=self.user)

    def go_next(self):
        self.app.show(self.next_screen, user=self.user, due_at=self.due_at)
