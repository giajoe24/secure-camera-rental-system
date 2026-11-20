# PC で試すための代わりの機器(config.USE_HARDWARE = False のとき main.py が使う)
#   PcCardReader : 社員証の代わり。テスト用ウィンドウのボタンで「かざした」ことにする
#   PcLock       : 電磁ロックとスイッチの代わり。テスト用ウィンドウのボタンで扉を開け閉めする
#   TestWindow   : 上の2つを操作する小さいウィンドウ(本体の画面とは別に出る)

import logging
import threading
import time
import tkinter

import customtkinter

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
    def __init__(self, app, card_reader, lock):
        super().__init__(app)
        self.app = app
        self.card_reader = card_reader
        self.lock = lock
        self.title("テスト用(PC)")
        self.geometry("320x560+820+0")

        make_label(self, "社員証をかざす", 16, True).pack(anchor="w", padx=12, pady=(10, 4))
        self.card_area = tkinter.Frame(self)
        self.card_area.pack(fill="x", padx=12)
        make_sub_button(self, "利用者を読み直す", self.show_cards, width=290, height=36).pack(padx=12, pady=4)

        make_label(self, "扉", 16, True).pack(anchor="w", padx=12, pady=(14, 4))
        make_sub_button(self, "扉を閉める(施錠)", self.close_door, width=290, height=40).pack(padx=12, pady=3)
        make_sub_button(self, "こじ開ける(不正な開放)", self.force_open, width=290, height=40).pack(padx=12, pady=3)
        self.stuck_box = customtkinter.CTkCheckBox(self, text="解錠しても扉が開かない", font=make_font(14),
                                                   command=self.change_stuck)
        self.stuck_box.pack(anchor="w", padx=12, pady=6)
        self.state_label = make_label(self, "", 14, color=SUB_TEXT_COLOR)
        self.state_label.pack(anchor="w", padx=12, pady=6)

        self.show_cards()
        self.show_state()

    def show_cards(self):
        for widget in self.card_area.winfo_children():
            widget.destroy()
        for user in self.app.database.list_users():
            text = f"{user['name']}({user['employee_number']})"
            button = make_sub_button(self.card_area, text, lambda c=user["card_id"]: self.card_reader.touch(c),
                                     width=290, height=36)
            button.configure(font=make_font(14))
            button.pack(pady=2)
        unknown = make_sub_button(self.card_area, "登録されていないカード",
                                  lambda: self.card_reader.touch("FFFFFFFFFFFFFFFF"), width=290, height=36)
        unknown.configure(font=make_font(14))
        unknown.pack(pady=2)

    def close_door(self):
        self.lock.locked = True

    def force_open(self):
        self.lock.locked = False

    def change_stuck(self):
        self.lock.stuck = self.stuck_box.get() == 1

    def show_state(self):
        if self.lock.locked:
            text = "扉: 閉まっている(施錠)"
        else:
            text = "扉: 開いている"
        self.state_label.configure(text=text)
        self.after(300, self.show_state)
