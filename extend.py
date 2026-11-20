# 追加機能: 返却予定の延長(config.USE_EXTEND)
# 貸出中はホームに「延長する」を出す。登録している人なら、借りた本人でなくても延ばせる。
# 期限を過ぎてから延ばすときは「今」から延ばす。
# 延長も記録は書き換えず、「延長」の行を足す(新しい返却予定はその行に入る)

from datetime import datetime, timedelta

import customtkinter

import config
import export
from db import DONE, RentalError, parse_time
from gui_parts import (GREEN_TAG, SCREEN_PADDING, SUB_TEXT_COLOR, TEXT_COLOR, Screen, disable_button, enable_main_button,
                       format_date_time, format_minutes, make_font, make_label, make_sub_button, make_tag,
                       show_as_selected)

EXTEND = "延長"
STEPS = ["社員証", "延長時間", "完了"]


def add_button_on_home(home, rental):
    if rental is None:
        return
    home.show_footer()
    # ホームでは「カメラを返す」が主なので、延長は白いボタンにして目立たせすぎない
    button = make_sub_button(home.footer, "延長する", lambda: home.app.scan_card(STEPS, card_read))
    button.pack(side="right", padx=SCREEN_PADDING)


def card_read(app, card_id):
    # 社員証が読めたら呼ばれる
    user = app.database.find_user_by_card(card_id)
    if user is None:
        raise RentalError("登録されていない社員証です", "利用の登録は管理者に頼んでください。")

    rental = app.database.current_rental()
    if rental is None:
        raise RentalError("延長できません", "いまは貸し出されていません。")
    app.show(ExtendScreen, user=user, rental=rental)


def new_due_at(rental, minutes, now):
    due_at = parse_time(rental["due_at"])
    if due_at > now:
        return due_at + timedelta(minutes=minutes)
    return now + timedelta(minutes=minutes)  # もう過ぎていたら今から


def extend_rental(database, user, rental, new_due, now=None):
    conn = database.open()
    try:
        with conn:
            current = database.find_current_rental(conn)
            if current is None or current["id"] != rental["id"]:
                raise RentalError("延長できません", "すでに返却されています。")
            database.add_log(conn, EXTEND, DONE, user, new_due, now=now)
    finally:
        conn.close()


class ExtendScreen(Screen):
    def __init__(self, app, user, rental):
        super().__init__(app)
        self.user = user
        self.rental = rental
        self.new_due = None

        self.show_steps(STEPS, 1)
        due_text = format_date_time(parse_time(rental["due_at"]))
        self.show_title("どれだけ延ばしますか?",
                        f"借りた人 {rental['name']} さん / 延ばす人 {user['name']} さん / 今の返却予定 {due_text}")

        self.add_left_button("戻る", app.go_home)
        self.ok_button = self.add_right_button("OK", self.extend)
        disable_button(self.ok_button)

        grid = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="a")

        self.time_buttons = {}
        for i, minutes in enumerate(config.EXTEND_MINUTES):
            button = make_sub_button(grid, f"+{format_minutes(minutes)}", lambda m=minutes: self.select(m), height=60)
            button.configure(font=make_font(21))
            button.grid(row=i // 4, column=i % 4, sticky="ew", padx=6, pady=6)
            self.time_buttons[minutes] = button

        # 新しい返却予定は下の帯に出す(画面が狭くても必ず見えるように)
        self.due_label = self.add_footer_label()
        self.due_label.configure(text="時間を選んでください", text_color=SUB_TEXT_COLOR)

    def select(self, minutes):
        for m, button in self.time_buttons.items():
            show_as_selected(button, m == minutes)

        self.new_due = new_due_at(self.rental, minutes, datetime.now())
        self.due_label.configure(text=f"新しい返却予定 {format_date_time(self.new_due)}", text_color=TEXT_COLOR)
        enable_main_button(self.ok_button)

    def extend(self):
        disable_button(self.ok_button)
        try:
            extend_rental(self.app.database, self.user, self.rental, self.new_due)
        except Exception as e:
            self.app.show_error(e)
            return
        export.update_excel(self.app.database)
        self.app.show(ExtendDoneScreen, new_due=self.new_due)


class ExtendDoneScreen(Screen):
    def __init__(self, app, new_due):
        super().__init__(app)
        self.show_steps(STEPS, 2)
        make_tag(self.top_area, "  完了  ", GREEN_TAG).pack(anchor="w", pady=(0, 10))
        make_label(self.top_area, "延長しました。", 28, True).pack(anchor="w")
        make_label(self.top_area, f"新しい返却予定は {format_date_time(new_due)} です。", 20).pack(anchor="w", pady=(8, 0))
        make_label(self.content_area, "まもなくホームに戻ります。", color=SUB_TEXT_COLOR).pack(anchor="w")

        self.add_right_button("ホームに戻る", app.go_home)
        self.run_later(config.DONE_SCREEN_SECONDS * 1000, app.go_home)
