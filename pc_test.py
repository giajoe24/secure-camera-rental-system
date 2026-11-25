# PC で試すための代わりの機器(config.USE_HARDWARE = False のとき main.py が使う)
#   PcCardReader : 社員証の代わり。テスト用ウィンドウのボタンで「かざした」ことにする
#   PcLock       : 電磁ロックとスイッチの代わり。テスト用ウィンドウのボタンで扉を開け閉めする
#   TestWindow   : 上の2つを操作する小さいウィンドウ(本体の画面とは別に出る)

import logging
import threading
import time
import tkinter

import customtkinter

import config

from gui_parts import SUB_TEXT_COLOR, make_font, make_label, make_sub_button

log = logging.getLogger(__name__)


class PcCardReader:
    def __init__(self):
        self.next_card = None
        self.card_touched = threading.Event()

    def touch(self, card_id):
        # テスト用ウィンドウのボタンから呼ばれる
        self.next_card = card_id
        self.card_touched.set()

    def read_card(self, timeout, cancel_event):
        # 本物と同じく、かざされるか、時間切れか、中止されるまで待つ(別スレッドで動く)
        self.card_touched.clear()
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            if cancel_event.is_set():
                return None
            if self.card_touched.wait(0.1):
                return self.next_card
        return None


class PcLock:
    def __init__(self):
        self.ready = True
        self.locked = True
        self.stuck = False   # True のときは、解錠しても扉が開かない(取り消しを試す用)

    def is_locked(self):
        return self.locked

    def open(self):
        log.info("(PC)解錠パルスを出したことにします")
        if not self.stuck:
            self.locked = False   # 本物もパルスでラッチが外れると「開いた」になる

    def close(self):
        pass


class TestWindow(customtkinter.CTkToplevel):
    # 本体の画面の右に出す、操作用の小さいウィンドウ
    def __init__(self, app, card_reader, lock):
        super().__init__(app)
        self.app = app
        self.card_reader = card_reader
        self.lock = lock
        self.shown_users = None   # いまボタンにしている利用者(変わったら作り直す)
        self.new_card_number = 0
        self.title("テスト用(PC)")
        self.geometry("340x700+820+0")

        # ---- 社員証 ----
        make_label(self, "社員証をかざす", 16, True).pack(anchor="w", padx=12, pady=(10, 2))
        make_label(self, "登録した人は自動でボタンになります", 13, color=SUB_TEXT_COLOR).pack(anchor="w", padx=12)
        self.card_area = customtkinter.CTkScrollableFrame(self, height=230, fg_color="transparent")
        self.card_area.pack(fill="x", padx=6)

        make_sub_button(self, "新しいカード(毎回ちがう ID)", self.touch_new_card,
                        width=310, height=36).pack(padx=12, pady=(6, 2))

        id_row = tkinter.Frame(self)
        id_row.pack(fill="x", padx=12, pady=4)
        self.id_entry = customtkinter.CTkEntry(id_row, width=190, height=36, font=make_font(14),
                                               placeholder_text="カードIDを入れる")
        self.id_entry.pack(side="left")
        make_sub_button(id_row, "かざす", self.touch_typed_card, width=110, height=36).pack(side="left", padx=(8, 0))

        # ---- 扉 ----
        make_label(self, "扉", 16, True).pack(anchor="w", padx=12, pady=(14, 4))
        self.state_label = make_label(self, "", 15, True)
        self.state_label.pack(anchor="w", padx=12, pady=(0, 6))
        make_sub_button(self, "扉を閉める(施錠)", self.relock, width=310, height=40).pack(padx=12, pady=3)
        make_sub_button(self, "こじ開ける(不正な開放を試す)", self.force_open, width=310, height=40).pack(padx=12, pady=3)

        self.stuck_box = customtkinter.CTkCheckBox(self, text="ロックが外れない(取り消しを試す)", font=make_font(14),
                                                   command=self.change_stuck)
        self.stuck_box.pack(anchor="w", padx=12, pady=(10, 2))
        self.stuck_label = make_label(self, "", 13, color=SUB_TEXT_COLOR)
        self.stuck_label.configure(wraplength=310)
        self.stuck_label.pack(anchor="w", padx=12)
        self.change_stuck()

        self.update_panel()

    # ---- 社員証 ----

    def show_cards(self):
        for widget in self.card_area.winfo_children():
            widget.destroy()
        for user in self.app.database.list_users():
            if user["card_id"].startswith("DELETED-"):
                continue
            text = f"{user['name']}({user['employee_number']})"
            button = make_sub_button(self.card_area, text, lambda c=user["card_id"]: self.touch(c),
                                     width=290, height=36)
            button.configure(font=make_font(14))
            button.pack(pady=2)
        unknown = make_sub_button(self.card_area, "登録されていないカード",
                                  lambda: self.touch("FFFFFFFFFFFFFFFF"), width=290, height=36)
        unknown.configure(font=make_font(14))
        unknown.pack(pady=2)

    def touch(self, card_id):
        log.info("(PC)カード %s をかざしたことにします", card_id)
        self.card_reader.touch(card_id)

    def touch_new_card(self):
        # 登録のテスト用。押すたびに、まだ使っていない ID にする
        self.new_card_number += 1
        self.touch(f"PC{self.new_card_number:014X}")

    def touch_typed_card(self):
        card_id = self.id_entry.get().strip()
        if card_id != "":
            self.touch(card_id)

    # ---- 扉 ----

    def relock(self):
        self.lock.locked = True

    def force_open(self):
        self.lock.locked = False

    def change_stuck(self):
        self.lock.stuck = self.stuck_box.get() == 1
        if self.lock.stuck:
            text = (f"ON:「借りる」「返す」を押しても扉が開きません。"
                    f"{config.UNLOCK_WAIT_SECONDS} 秒後に取り消しの画面になります。")
        else:
            text = "OFF:「借りる」「返す」を押すと扉が開きます。"
        self.stuck_label.configure(text=text)

    # ---- 0.3 秒ごとに表示を最新にする ----

    def update_panel(self):
        if self.lock.locked:
            text = "今:閉まっている(施錠)"
        else:
            text = "今:開いている"
        if self.state_label.cget("text") != text:
            self.state_label.configure(text=text)

        users = [tuple(user) for user in self.app.database.list_users()]
        if users != self.shown_users:   # 登録・変更があったらボタンを作り直す
            self.shown_users = users
            self.show_cards()

        self.after(300, self.update_panel)
