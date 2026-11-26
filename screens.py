# 画面
# 貸出: ホーム → 社員証 → 貸出時間 → 確認 → 棚(開けて閉める) → 完了 → ホーム
# 返却: ホーム → 社員証 → 確認 → 棚(開けて閉める) → 完了 → ホーム
# 棚が閉まって施錠したのを確かめてから「完了」を記録する。

import logging
import threading
import time
import tkinter
from datetime import datetime, timedelta

import customtkinter

import admin_screen
import config
import events
import export
import extend
import long_rental
import storage_check
import user_info
import overdue_display
import overdue_record
from db import BORROW, RETURN, RentalError, parse_time
from gui_parts import (BLUE_TAG, ERROR_TEXT_COLOR, GREEN_TAG, RED_TAG, SUB_TEXT_COLOR, TEXT_COLOR, WHITE,
                       YELLOW_TAG, Screen, disable_button, enable_main_button, format_date_time, format_minutes,
                       make_font, make_label, make_line, make_main_button, make_sub_button, make_tag,
                       show_as_selected)

log = logging.getLogger(__name__)

BORROW_STEPS = ["社員証", "貸出時間", "確認", "取り出し"]
RETURN_STEPS = ["社員証", "確認", "返却"]


def can_use_lock(lock):
    # 解錠できて、施錠も確かめられるときだけ使える
    return lock.ready and lock.is_locked() is not None


class HomeScreen(Screen):
    idle_timeout = False   # もうホームなので戻さない(作り直すとちらつくため)

    def __init__(self, app):
        super().__init__(app)
        self.footer.pack_forget()   # 下の帯は、追加機能がボタンを置くときだけ出す(show_footer)
        rental = app.database.current_rental()

        # カメラの状態(札の色と文字の両方で出す)
        make_label(self.top_area, config.CAMERA_NAME, 18, True).pack(anchor="w")
        status_row = tkinter.Frame(self.top_area, bg=WHITE)
        status_row.pack(anchor="w", pady=(8, 0))

        if rental is None:
            make_tag(status_row, "  貸出可能  ", GREEN_TAG).pack(side="left")
            make_label(status_row, "  いつでも借りられます", 22, True).pack(side="left")
        else:
            make_tag(status_row, "  貸出中  ", BLUE_TAG).pack(side="left")
            make_label(status_row, f"  {rental['name']} さんが借りています", 22, True).pack(side="left")
            due_at = parse_time(rental["due_at"])
            self.due_label = make_label(self.top_area, f"返却予定  {format_date_time(due_at)}", color=SUB_TEXT_COLOR)
            self.due_label.pack(anchor="w", pady=(6, 0))

        # 追加機能: 期限切れの表示
        if config.USE_OVERDUE_DISPLAY:
            overdue_display.show_on_home(self, rental)

        # 追加機能: SD カードの空きが少ないとき
        if config.USE_STORAGE_CHECK and storage_check.low_space:
            text = "SD カードの空きが少なくなっています。管理者に連絡してください。"
            make_label(self.top_area, text, 16, True, ERROR_TEXT_COLOR).pack(anchor="w", pady=(4, 0))

        # 大きいボタン2つ
        buttons = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        buttons.pack(fill="both", expand=True)
        buttons.grid_columnconfigure((0, 1), weight=1, uniform="a")
        buttons.grid_rowconfigure(0, weight=1)

        borrow_button = make_main_button(buttons, "カメラを借りる", self.start_borrow)
        borrow_button.configure(font=make_font(26, True))
        borrow_button.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        return_button = make_main_button(buttons, "カメラを返す", self.start_return)
        return_button.configure(font=make_font(26, True))
        return_button.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # 押しても意味がないボタンは押せなくする
        if not can_use_lock(app.lock):
            text = "電磁ロックかスイッチが使えないため停止中です。管理者に連絡してください。"
            make_label(self.content_area, text, bold=True, color=ERROR_TEXT_COLOR).pack(anchor="w", pady=(10, 0))
            disable_button(borrow_button)
            disable_button(return_button)
        elif rental is None:
            disable_button(return_button)
        else:
            disable_button(borrow_button)

        # 追加機能: 管理画面
        if config.USE_ADMIN_SCREEN:
            admin_screen.add_button_on_home(self)

        # 追加機能: 延長
        if config.USE_EXTEND and can_use_lock(app.lock):
            extend.add_button_on_home(self, rental)

    def start_borrow(self):
        self.app.show(ScanScreen, purpose=BORROW)

    def start_return(self):
        self.app.show(ScanScreen, purpose=RETURN)


class ScanScreen(Screen):
    # 社員証をかざしてもらう。
    # 読み取りは app.card_reader_worker(別スレッド)に頼み、
    # 100ms ごとに「終わったか」を見に行く(customtkinter は別スレッドから触れないため)

    idle_timeout = False  # 読み取りの待ち時間で戻るので、こちらでは戻さない

    def __init__(self, app, purpose=BORROW, steps=None, on_card=None, back=None, back_name="ホーム"):
        # on_card: 管理画面用。指定されていたら、貸出・返却の代わりにこれを呼ぶ
        # back / back_name: 「戻る」・時間切れ・エラーのときの戻り先(なければホーム)
        super().__init__(app)
        self.purpose = purpose
        self.steps = steps
        self.on_card = on_card
        self.back = back or app.go_home
        self.back_name = back_name

        if steps is None:
            if purpose == BORROW:
                steps = BORROW_STEPS
            else:
                steps = RETURN_STEPS
        self.show_steps(steps, 0)
        self.show_title("社員証をカードリーダーにかざしてください", "読み取るまで、社員証を動かさないでください。")

        self.remaining_label = make_label(self.content_area, "", color=SUB_TEXT_COLOR)
        self.remaining_label.pack(anchor="w")

        self.add_left_button("戻る" if back is None else f"◀ {back_name}", self.back)

        self.cancel_event = threading.Event()  # 「戻る」を読み取り側に伝える
        self.start_time = time.monotonic()

        # 読み取りを頼む。結果はあとで future から受け取る
        self.future = app.card_reader_worker.submit(
            app.card_reader.read_card, config.CARD_WAIT_SECONDS, self.cancel_event)
        self.check_result()

    def check_result(self):
        if not self.future.done():
            remaining = max(0, int(config.CARD_WAIT_SECONDS - (time.monotonic() - self.start_time)))
            text = f"あと {remaining} 秒で{self.back_name}に戻ります"
            if self.remaining_label.cget("text") != text:   # 変わったときだけ書き換える
                self.remaining_label.configure(text=text)
            self.run_later(100, self.check_result)
            return

        try:
            card_id = self.future.result()
        except Exception as e:
            self.show_error(e)
            return

        if card_id is None:
            self.back()  # 時間切れ
        else:
            self.use_card(card_id)

    def scan_again(self):
        self.app.show(ScanScreen, purpose=self.purpose, steps=self.steps, on_card=self.on_card,
                      back=self.back if self.back != self.app.go_home else None, back_name=self.back_name)

    def show_error(self, error):
        # エラー画面の左のボタンも、この画面の戻り先にする
        self.app.show_error(error, retry=self.scan_again, retry_text="もう一度かざす",
                            back=self.back, back_text=f"{self.back_name}に戻る")

    def use_card(self, card_id):
        try:
            if self.on_card is not None:
                self.on_card(self.app, card_id)
                return

            user = self.app.database.find_user_by_card(card_id)
            if user is None:
                log.info("未登録の社員証: %s", card_id)
                events.add_event(self.app.database, events.UNKNOWN_CARD, f"カードID {card_id}")
                raise RentalError("登録されていない社員証です", "利用の登録は管理者に頼んでください。")

            # 追加機能: 利用停止中の社員証は使えない
            if config.USE_USER_INFO:
                user_info.check_active(user)

            rental = self.app.database.current_rental()
            if self.purpose == BORROW:
                if rental is not None:
                    raise RentalError("いまは借りられません", "ほかの人が借りています。")
                self.app.show(TimeScreen, user=user)
            else:
                if rental is None:
                    raise RentalError("返すカメラがありません", "カメラは貸し出されていません。")
                self.app.show(ReturnConfirmScreen, user=user, rental=rental)

        except RentalError as e:
            self.show_error(e)
        except Exception as e:
            self.app.show_error(e, back=self.back, back_text=f"{self.back_name}に戻る")

    def leave(self):
        self.future.cancel()      # まだ始まっていなければ取り消し
        self.cancel_event.set()   # 始まっていれば止める
        super().leave()


class TimeScreen(Screen):
    # 時間を選ぶと返却予定が出る → OK で確認へ

    def __init__(self, app, user, selected_minutes=None):
        super().__init__(app)
        self.user = user
        self.selected_minutes = None
        self.show_steps(BORROW_STEPS, 1)
        self.show_title("貸出時間を選んでください", f"{user['name']} さん")

        self.add_left_button("戻る", app.go_home)
        self.ok_button = self.add_right_button("OK", self.go_next)
        disable_button(self.ok_button)  # 選ぶまで押せない

        grid = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="a")

        self.time_buttons = {}  # {分: ボタン}
        for i, minutes in enumerate(config.RENTAL_MINUTES):
            button = make_sub_button(grid, format_minutes(minutes), lambda m=minutes: self.select(m), height=60)
            button.configure(font=make_font(21))
            button.grid(row=i // 4, column=i % 4, sticky="ew", padx=6, pady=6)
            self.time_buttons[minutes] = button

        # 追加機能: 日をまたぐ貸出(残りの場所に横長で置く)
        if config.USE_LONG_RENTAL:
            count = len(config.RENTAL_MINUTES)
            other_button = make_sub_button(grid, "その他(日をまたぐ)", self.choose_long, height=60)
            other_button.configure(font=make_font(19))
            other_button.grid(row=count // 4, column=count % 4, columnspan=4 - count % 4, sticky="ew", padx=6, pady=6)

        # 返却予定は下の帯に出す(画面が狭くても必ず見えるように)
        self.due_label = self.add_footer_label()
        self.due_label.configure(text="時間を選んでください", text_color=SUB_TEXT_COLOR)

        # 確認画面から戻ってきたときは、前に選んだ時間を選んでおく
        if selected_minutes is not None:
            self.select(selected_minutes)

    def select(self, minutes):
        self.selected_minutes = minutes
        for m, button in self.time_buttons.items():
            show_as_selected(button, m == minutes)

        due_at = datetime.now() + timedelta(minutes=minutes)
        self.due_label.configure(text=f"返却予定 {format_date_time(due_at)}", text_color=TEXT_COLOR)
        enable_main_button(self.ok_button)

    def go_next(self):
        self.app.show(ConfirmScreen, user=self.user, minutes=self.selected_minutes)

    def choose_long(self):
        self.app.show(long_rental.LongTimeScreen, user=self.user, steps=BORROW_STEPS,
                      back_screen=TimeScreen, next_screen=ConfirmScreen)


def make_table(parent, rows, columns=1):
    # 「項目  値」の表。rows は [(項目, 値), ...]
    # columns=2 にすると2列に並べる(行が多くて縦に入らないとき)
    table = customtkinter.CTkFrame(parent, fg_color="transparent")
    table.pack(fill="x")
    for c in range(columns):
        table.grid_columnconfigure(c * 2, minsize=110)
        table.grid_columnconfigure(c * 2 + 1, weight=1)

    for i, (name, value) in enumerate(rows):
        row = i // columns
        column = (i % columns) * 2
        make_label(table, name, color=SUB_TEXT_COLOR).grid(row=row * 2, column=column, sticky="w", pady=8)
        make_label(table, value, 20, True).grid(row=row * 2, column=column + 1, sticky="w", padx=(0, 12))
        make_line(table).grid(row=row * 2 + 1, column=column, columnspan=2, sticky="ew")


def show_unlock_notice(parent, button_text):
    # 押すとロックが開くことを、黄色(注意の色)の太字の枠で先に知らせる(急に開いて驚かないように)
    box = tkinter.Frame(parent, bg=YELLOW_TAG[1], highlightthickness=2, highlightbackground=YELLOW_TAG[0])
    box.pack(fill="x", pady=(8, 0))
    make_tag(box, "  注意  ", (WHITE, YELLOW_TAG[0])).pack(side="left", padx=10, pady=8)
    make_label(box, f"「{button_text}」を押すと、棚のロックが「カチッ」と開きます。", 19, True,
               YELLOW_TAG[0]).pack(side="left", padx=(0, 10))


class ConfirmScreen(Screen):
    # minutes: 選んだ貸出時間(分)
    # due_at : 日をまたぐ貸出(追加機能)のときは、選んだ返却予定そのもの(minutes は None)
    def __init__(self, app, user, minutes=None, due_at=None):
        super().__init__(app)
        self.user = user
        self.minutes = minutes
        self.fixed_due_at = due_at
        self.show_steps(BORROW_STEPS, 2)
        self.show_title("この内容で借ります")
        show_unlock_notice(self.top_area, "借りる")

        if due_at is None:
            length = format_minutes(minutes)
            due_at = datetime.now() + timedelta(minutes=minutes)
        else:
            days = (due_at.date() - datetime.now().date()).days
            length = f"{days} 日間(日をまたぐ)"
        make_table(self.content_area, [
            ("借りる人", f"{user['name']} さん"),
            ("貸出時間", length),
            ("返却予定", format_date_time(due_at)),
        ])

        self.back_button = self.add_left_button("戻る", self.go_back)
        self.borrow_button = self.add_right_button("借りる", self.borrow)

    def go_back(self):
        if self.fixed_due_at is not None:
            self.app.show(long_rental.LongTimeScreen, user=self.user, steps=BORROW_STEPS,
                          back_screen=TimeScreen, next_screen=ConfirmScreen, due_at=self.fixed_due_at)
        else:
            self.app.show(TimeScreen, user=self.user, selected_minutes=self.minutes)

    def borrow(self):
        # 二度押し防止
        disable_button(self.borrow_button)
        self.back_button.configure(state="disabled")
        self.update_idletasks()

        if self.fixed_due_at is not None:
            due_at = self.fixed_due_at
        else:
            # 時間を選んでから押すまでの間も数えるため、返却予定は押した時刻から計算し直す
            due_at = datetime.now() + timedelta(minutes=self.minutes)
        try:
            self.app.database.start(BORROW, self.user, self.app.unlock, due_at=due_at)
        except Exception as e:
            self.app.show_error(e)
            return

        log.info("貸出の解錠: %s 返却予定 %s", self.user["employee_number"], due_at)
        self.app.show(UnlockScreen, action=BORROW, user=self.user, due_at=due_at)


class ReturnConfirmScreen(Screen):
    # 返却の確認。借りた本人でなくても、登録している人なら返せる
    def __init__(self, app, user, rental):
        super().__init__(app)
        self.user = user
        self.show_steps(RETURN_STEPS, 1)
        self.show_title(f"{config.ITEM_NAME}を返します")
        show_unlock_notice(self.top_area, "返す")

        make_table(self.content_area, [
            ("返す人", f"{user['name']} さん"),
            ("借りた人", f"{rental['name']} さん"),
            ("貸出日時", format_date_time(parse_time(rental["rented_at"]))),
            ("返却予定", format_date_time(parse_time(rental["due_at"]))),
        ])

        self.rental = rental
        self.back_button = self.add_left_button("戻る", app.go_home)
        self.return_button = self.add_right_button("返す", self.give_back)

    def give_back(self):
        disable_button(self.return_button)
        self.back_button.configure(state="disabled")
        self.update_idletasks()

        try:
            self.app.database.start(RETURN, self.user, self.app.unlock)
        except Exception as e:
            self.app.show_error(e)
            return

        log.info("返却の解錠: %s", self.user["employee_number"])
        self.app.show(UnlockScreen, action=RETURN, user=self.user, rental=self.rental)


class UnlockScreen(Screen):
    # 解錠したあと、棚が開いて、また閉まる(施錠する)のを待つ。
    #   UNLOCK_WAIT_SECONDS 秒たっても開かれなかったら → 取り消し
    #   開いたまま UNLOCKED_WARN_SECONDS 秒たったら      → 閉めるように警告(点滅はさせない)
    #   閉まったら                                         → 完了を記録
    # 状態はマイクロスイッチ(lock.is_locked)で 0.2 秒ごとに見る

    idle_timeout = False       # 棚が開いている間はホームに戻さない
    unlock_expected = True    # 自分で解錠しているので、不正な開放ではない

    def __init__(self, app, action, user, due_at=None, rental=None):
        # rental: 返却のとき、返すカメラの貸出(延滞の表示に使う)
        super().__init__(app)
        self.rental = rental
        self.action = action
        self.user = user
        self.due_at = due_at
        self.state = "待ち"        # 待ち → 開いた → 完了
        self.start_time = time.monotonic()
        self.open_time = None

        item = config.ITEM_NAME
        if action == BORROW:
            self.show_steps(BORROW_STEPS, 3)
            self.what_to_do = f"{item}を取り出して、棚を閉めてください。"
            self.reminder = f"{item}は持ち歩かず、使い終わったらすぐに返してください。"
        else:
            self.show_steps(RETURN_STEPS, 2)
            self.what_to_do = f"{item}を中に戻して、棚を閉めてください。"
            self.reminder = f"{item}を持ったまま棚を閉めないよう、中に置いたか確かめてください。"

        self.footer.pack_forget()   # ここでは押すボタンがない

        self.title_label = make_label(self.top_area, "棚のロックが開きました", 30, True)
        self.title_label.pack(anchor="w")
        self.guide_label = make_label(self.top_area, "棚を開けてください。", 22, True)
        self.guide_label.pack(anchor="w", pady=(8, 0))
        make_label(self.top_area, self.reminder, 18, True, BLUE_TAG[0]).pack(anchor="w", pady=(6, 0))

        self.note_label = make_label(self.content_area, "", color=SUB_TEXT_COLOR)
        self.note_label.pack(anchor="w")

        # 警告(棚を閉め忘れたとき)。最初は出さない
        self.warning_area = tkinter.Frame(self.content_area, bg=YELLOW_TAG[1], highlightthickness=2,
                                          highlightbackground=YELLOW_TAG[0])
        make_tag(self.warning_area, "  警告  ", (WHITE, YELLOW_TAG[0])).pack(side="left", padx=12, pady=12)
        make_label(self.warning_area, "棚が閉まっていません。棚を閉めてください。", 20, True,
                   YELLOW_TAG[0]).pack(side="left", padx=(0, 12))

        self.watch_lock()

    def watch_lock(self):
        locked = self.app.lock.is_locked()
        now = time.monotonic()

        if self.state == "待ち":
            if not locked:
                self.state = "開いた"
                self.open_time = now
                self.guide_label.configure(text=self.what_to_do)
                self.note_label.configure(text="棚を閉めると、記録して完了します。")
            elif now - self.start_time > config.UNLOCK_WAIT_SECONDS:
                self.give_up()
                return
            else:
                remaining = int(config.UNLOCK_WAIT_SECONDS - (now - self.start_time))
                text = f"あと {remaining} 秒以内に棚を開けてください。開けないと取り消しになります。"
                if self.note_label.cget("text") != text:
                    self.note_label.configure(text=text)

        elif self.state == "開いた":
            if locked:
                self.finish()
                return
            if now - self.open_time > config.UNLOCKED_WARN_SECONDS and not self.warning_area.winfo_ismapped():
                log.warning("棚が閉まっていません")
                events.add_event(self.app.database, events.LEFT_OPEN,
                                 f"{self.action}のあと {config.UNLOCKED_WARN_SECONDS} 秒 開いたまま({self.user['name']})")
                self.warning_area.pack(fill="x", pady=(14, 0))

        self.run_later(200, self.watch_lock)

    def finish(self):
        self.state = "完了"
        try:
            self.app.database.finish(self.action, self.user, self.due_at)
        except Exception as e:
            self.app.show_error(e)
            return
        log.info("%sの完了(施錠を確認): %s", self.action, self.user["employee_number"])
        export.update_excel(self.app.database)
        self.app.show(DoneScreen, action=self.action, due_at=self.due_at, rental=self.rental)

    def give_up(self):
        try:
            self.app.database.cancel(self.action, self.user, "棚が開かれなかったため")
        except Exception as e:
            self.app.show_error(e)
            return
        log.info("%sの取り消し(棚が開かれなかった): %s", self.action, self.user["employee_number"])
        export.update_excel(self.app.database)
        self.app.show(MessageScreen, title=f"{self.action}を取り消しました",
                      message="棚が開かれなかったため、取り消しました。もう一度最初からやり直してください。",
                      tag="取り消し")


class DoneScreen(Screen):
    def __init__(self, app, action, due_at=None, rental=None):
        super().__init__(app)
        if action == BORROW:
            self.show_steps(BORROW_STEPS, 3)
        else:
            self.show_steps(RETURN_STEPS, 2)

        make_tag(self.top_area, "  完了  ", GREEN_TAG).pack(anchor="w", pady=(0, 10))
        make_label(self.top_area, f"{action}が完了しました。", 28, True).pack(anchor="w")
        if due_at is not None:
            make_label(self.top_area, f"返却予定は {format_date_time(due_at)} です。", 20).pack(anchor="w", pady=(8, 0))

        # 追加機能: 遅れて返したら何分遅れたかを出す
        if config.USE_OVERDUE_RECORD and rental is not None:
            overdue_record.show_on_done(self, rental["due_at"])

        make_label(self.content_area, "まもなくホームに戻ります。", color=SUB_TEXT_COLOR).pack(anchor="w")
        self.add_right_button("ホームに戻る", app.go_home)
        self.run_later(config.DONE_SCREEN_SECONDS * 1000, app.go_home)


class MessageScreen(Screen):
    # エラーや取り消しのお知らせ
    def __init__(self, app, title, message, retry=None, retry_text="もう一度", tag="エラー",
                 back=None, back_text="ホームに戻る"):
        super().__init__(app)
        make_tag(self.top_area, f"  {tag}  ", RED_TAG).pack(anchor="w", pady=(0, 10))
        self.show_title(title, message, ERROR_TEXT_COLOR)
        self.add_left_button(back_text, back or app.go_home)
        if retry is not None:
            self.add_right_button(retry_text, retry)
