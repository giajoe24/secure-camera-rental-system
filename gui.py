# ウィンドウ本体
# 上の帯と時計、画面の切り替え、放置したらホームに戻す、エラー画面

import logging
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import customtkinter

import config
import events
import forced_open
from card_reader import CardReaderError
from db import RentalError
from gui_parts import BRAND_RED, SCREEN_PADDING, SUB_TEXT_COLOR, WHITE, format_date_time, make_label, make_line
from lock import LockError
from screens import HomeScreen, MessageScreen, ScanScreen

log = logging.getLogger(__name__)


class App(customtkinter.CTk):
    def __init__(self, database, card_reader, lock):
        # 画面の拡大率を 1 倍に固定する(OS の設定で勝手に大きくなって、はみ出さないように)
        customtkinter.set_widget_scaling(1.0)
        customtkinter.set_window_scaling(1.0)
        customtkinter.set_appearance_mode("light")
        super().__init__()

        self.database = database
        self.card_reader = card_reader
        self.lock = lock
        self.screen = None
        self.last_touch_time = time.monotonic()

        # 社員証の読み取りは別スレッドでやる。
        # max_workers=1 なので、読み取りは1回ずつ順番になる(リーダーの取り合いにならない)
        self.card_reader_worker = ThreadPoolExecutor(max_workers=1)

        self.title("セキュアカメラ貸出")
        self.geometry("800x480")
        self.configure(fg_color=WHITE)
        if config.FULLSCREEN:
            self.attributes("-fullscreen", True)
            # 起動した直後だと全画面にならないことがあるので、ウィンドウが出てからもう一度
            self.after(500, self.attributes, "-fullscreen", True)
            self.configure(cursor="none")   # タッチで使うのでマウスの矢印は出さない

        self.bind("<Escape>", self.exit_fullscreen)       # 保守用
        self.protocol("WM_DELETE_WINDOW", self.close)      # × で閉じたとき
        self.bind_all("<ButtonPress>", self.record_touch, add="+")

        # 上の帯(赤は細い線だけにして、目に強すぎないようにする)
        make_line(self, 4, BRAND_RED).pack(fill="x")
        header = customtkinter.CTkFrame(self, height=40, fg_color=WHITE, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        make_label(header, "セキュアカメラ貸出", 17, True).pack(side="left", padx=SCREEN_PADDING)
        self.clock_label = make_label(header, "", 17, color=SUB_TEXT_COLOR)
        self.clock_label.pack(side="right", padx=SCREEN_PADDING)
        make_line(self).pack(fill="x")

        # 画面を入れる場所
        self.body = customtkinter.CTkFrame(self, fg_color=WHITE, corner_radius=0)
        self.body.pack(fill="both", expand=True)

        self.go_home()
        self.every_second()

    def exit_fullscreen(self, event):
        self.attributes("-fullscreen", False)
        self.configure(cursor="")

    def record_touch(self, event):
        self.last_touch_time = time.monotonic()

    def every_second(self):
        # 時計は表示が変わるときだけ書き換える(毎秒書き換えるとちらつくため)
        text = format_date_time(datetime.now())
        if self.clock_label.cget("text") != text:
            self.clock_label.configure(text=text)

        # 追加機能: 解錠していないのに棚が開いていないか
        if config.USE_FORCED_OPEN_CHECK:
            forced_open.check(self)

        # しばらく触られていなければホームに戻す
        if self.screen.idle_timeout and time.monotonic() - self.last_touch_time > config.IDLE_SECONDS:
            log.info("操作がないのでホームに戻ります")
            self.go_home()

        self.after(1000, self.every_second)

    def show(self, screen_class, **kwargs):
        # 新しい画面を作り終えてから、前の画面を消して、新しい画面を出す。
        # (前の画面を先に消すと、作っている間なにもない画面が見えてちらつくため)
        new_screen = screen_class(self, **kwargs)
        if self.screen is not None:
            self.screen.leave()
            self.screen.destroy()
        self.screen = new_screen
        self.screen.pack(fill="both", expand=True)
        self.last_touch_time = time.monotonic()

    def go_home(self):
        self.show(HomeScreen)

    def scan_card(self, steps, on_card, back=None, back_name="ホーム"):
        # 管理画面などで使う。社員証を読んで、読めたら on_card(app, カードID) を呼ぶ
        # back: 「戻る」・時間切れ・エラーのときの戻り先(なければホーム)
        self.show(ScanScreen, steps=steps, on_card=on_card, back=back, back_name=back_name)

    def unlock(self):
        self.lock.open()

    def close(self):
        # 読み取り中でもすぐ終われるように、先に読み取りを止めてから閉じる
        if self.screen is not None:
            self.screen.leave()
        self.card_reader_worker.shutdown(wait=False, cancel_futures=True)
        self.destroy()

    def show_error(self, error, retry=None, retry_text="もう一度", back=None, back_text="ホームに戻る"):
        # エラーの種類ごとに、利用者向けの文に直して出す
        if isinstance(error, RentalError):
            title = error.title
            message = error.message
        elif isinstance(error, LockError):
            log.error("解錠に失敗: %s", error)
            events.add_event(self.database, events.ERROR, f"解錠に失敗: {error}")
            title = "棚が開きませんでした"
            message = "記録は取り消しました。管理者に連絡してください。"
        elif isinstance(error, CardReaderError):
            log.error("カードリーダーのエラー: %s", error)
            events.add_event(self.database, events.ERROR, f"カードリーダー: {error}")
            title = "社員証を読み取れませんでした"
            message = "もう一度かざしてください。続く場合は管理者に連絡してください。"
        elif isinstance(error, sqlite3.Error):
            log.exception("DB のエラー", exc_info=error)
            events.add_event(self.database, events.ERROR, f"DB: {error}")
            title = "記録できませんでした"
            message = "棚は開けていません。続く場合は管理者に連絡してください。"
        else:
            log.exception("想定外のエラー", exc_info=error)
            events.add_event(self.database, events.ERROR, f"想定外: {error!r}")
            title = "処理を中止しました"
            message = "棚は開けていません。続く場合は管理者に連絡してください。"

        self.show(MessageScreen, title=title, message=message, retry=retry, retry_text=retry_text,
                  back=back, back_text=back_text)

    def report_callback_exception(self, exc_type, exc, tb):
        # ボタンの処理などで起きたエラーもエラー画面にする(tkinter が呼ぶ)
        self.show_error(exc)
