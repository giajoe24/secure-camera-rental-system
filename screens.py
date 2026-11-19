# 画面
# 貸出: ホーム → 社員証 → 貸出時間 → 確認 → 扉(開けて閉める) → 完了 → ホーム
# 返却: ホーム → 社員証 → 確認 → 扉(開けて閉める) → 完了 → ホーム
# 扉が閉まって施錠したのを確かめてから「完了」を記録する。

import logging
import threading
import time
import tkinter
from datetime import datetime, timedelta

import customtkinter

import admin_screen
import config
import export
import extend
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

    def __init__(self, app, purpose=BORROW, steps=None, on_card=None):
        # on_card: 管理画面用。指定されていたら、貸出・返却の代わりにこれを呼ぶ
        super().__init__(app)
        self.purpose = purpose
        self.steps = steps
        self.on_card = on_card

        if steps is None:
            if purpose == BORROW:
                steps = BORROW_STEPS
            else:
                steps = RETURN_STEPS
        self.show_steps(steps, 0)
        self.show_title("社員証をカードリーダーにかざしてください", "読み取るまで、社員証を動かさないでください。")

        self.remaining_label = make_label(self.content_area, "", color=SUB_TEXT_COLOR)
        self.remaining_label.pack(anchor="w")

        self.add_left_button("戻る", app.go_home)

        self.cancel_event = threading.Event()  # 「戻る」を読み取り側に伝える
        self.start_time = time.monotonic()

        # 読み取りを頼む。結果はあとで future から受け取る
        self.future = app.card_reader_worker.submit(
            app.card_reader.read_card, config.CARD_WAIT_SECONDS, self.cancel_event)
        self.check_result()

    def check_result(self):
        if not self.future.done():
            remaining = max(0, int(config.CARD_WAIT_SECONDS - (time.monotonic() - self.start_time)))
            text = f"あと {remaining} 秒でホームに戻ります"
            if self.remaining_label.cget("text") != text:   # 変わったときだけ書き換える
                self.remaining_label.configure(text=text)
            self.run_later(100, self.check_result)
            return

        try:
            card_id = self.future.result()
        except Exception as e:
            self.app.show_error(e, retry=self.scan_again, retry_text="もう一度かざす")
            return

        if card_id is None:
            self.app.go_home()  # 時間切れ
        else:
            self.use_card(card_id)

    def scan_again(self):
        self.app.show(ScanScreen, purpose=self.purpose, steps=self.steps, on_card=self.on_card)

    def use_card(self, card_id):
        try:
            if self.on_card is not None:
                self.on_card(self.app, card_id)
                return

            user = self.app.database.find_user_by_card(card_id)
            if user is None:
                log.info("未登録の社員証: %s", card_id)
                raise RentalError("登録されていない社員証です", "利用の登録は管理者に頼んでください。")

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
            self.app.show_error(e, retry=self.scan_again, retry_text="もう一度かざす")
        except Exception as e:
            self.app.show_error(e)

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
        grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="a")

        self.time_buttons = {}  # {分: ボタン}
        for i, minutes in enumerate(config.RENTAL_MINUTES):
            button = make_sub_button(grid, format_minutes(minutes), lambda m=minutes: self.select(m), height=60)
            button.configure(font=make_font(21))
            button.grid(row=i // 3, column=i % 3, sticky="ew", padx=6, pady=6)
            self.time_buttons[minutes] = button

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


class ConfirmScreen(Screen):
    def __init__(self, app, user, minutes):
        super().__init__(app)
        self.user = user
        self.minutes = minutes
        self.show_steps(BORROW_STEPS, 2)
        self.show_title("この内容で借ります", "「借りる」を押すと、扉のロックが開きます。")

        self.due_at = datetime.now() + timedelta(minutes=minutes)
        make_table(self.content_area, [
            ("借りる人", f"{user['name']} さん"),
            ("貸出時間", format_minutes(minutes)),
            ("返却予定", format_date_time(self.due_at)),
        ])

        self.back_button = self.add_left_button("戻る", self.go_back)
        self.borrow_button = self.add_right_button("借りる", self.borrow)

    def go_back(self):
        self.app.show(TimeScreen, user=self.user, selected_minutes=self.minutes)

    def borrow(self):
        # 二度押し防止
        disable_button(self.borrow_button)
        self.back_button.configure(state="disabled")
        self.update_idletasks()

        # 時間を選んでから押すまでの間も数えるため、返却予定は押した時刻から計算し直す
        due_at = datetime.now() + timedelta(minutes=self.minutes)
        try:
            self.app.database.start(BORROW, self.user, self.app.open_door, due_at=due_at)
        except Exception as e:
            self.app.show_error(e)
            return

        log.info("貸出の解錠: %s %s分", self.user["employee_number"], self.minutes)
        self.app.show(DoorScreen, action=BORROW, user=self.user, due_at=due_at)


class ReturnConfirmScreen(Screen):
    # 返却の確認。借りた本人でなくても、登録している人なら返せる
    def __init__(self, app, user, rental):
        super().__init__(app)
        self.user = user
        self.show_steps(RETURN_STEPS, 1)
        self.show_title("カメラを返します", "「返す」を押すと、扉のロックが開きます。")

        make_table(self.content_area, [
            ("返す人", f"{user['name']} さん"),
            ("借りた人", f"{rental['name']} さん"),
            ("貸出日時", format_date_time(parse_time(rental["rented_at"]))),
            ("返却予定", format_date_time(parse_time(rental["due_at"]))),
        ], columns=2)

        self.rental = rental
        self.back_button = self.add_left_button("戻る", app.go_home)
        self.return_button = self.add_right_button("返す", self.give_back)

    def give_back(self):
        disable_button(self.return_button)
        self.back_button.configure(state="disabled")
        self.update_idletasks()

        try:
            self.app.database.start(RETURN, self.user, self.app.open_door)
        except Exception as e:
            self.app.show_error(e)
            return

        log.info("返却の解錠: %s", self.user["employee_number"])
        self.app.show(DoorScreen, action=RETURN, user=self.user, rental=self.rental)


class DoorScreen(Screen):
    # 解錠したあと、扉が開いて、また閉まる(施錠する)のを待つ。
    #   DOOR_OPEN_WAIT_SECONDS 秒たっても開かれなかったら → 取り消し
    #   開いたまま DOOR_CLOSE_WARN_SECONDS 秒たったら      → 閉めるように警告(点滅はさせない)
    #   閉まったら                                         → 完了を記録
    # 状態はマイクロスイッチ(lock.is_locked)で 0.2 秒ごとに見る

    idle_timeout = False   # 扉が開いている間はホームに戻さない

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

        if action == BORROW:
            self.show_steps(BORROW_STEPS, 3)
            self.what_to_do = "カメラを取り出して、扉を閉めてください。"
        else:
            self.show_steps(RETURN_STEPS, 2)
            self.what_to_do = "カメラを戻して、扉を閉めてください。"

        self.footer.pack_forget()   # ここでは押すボタンがない

        self.title_label = make_label(self.top_area, "扉のロックを開けました", 24, True)
        self.title_label.pack(anchor="w")
        self.guide_label = make_label(self.top_area, "扉を開けてください。", 22, True)
        self.guide_label.pack(anchor="w", pady=(8, 0))

        self.note_label = make_label(self.content_area, "", color=SUB_TEXT_COLOR)
        self.note_label.pack(anchor="w")

        # 警告(扉を閉め忘れたとき)。最初は出さない
        self.warning_area = tkinter.Frame(self.content_area, bg=YELLOW_TAG[1], highlightthickness=2,
                                          highlightbackground=YELLOW_TAG[0])
        make_tag(self.warning_area, "  警告  ", (WHITE, YELLOW_TAG[0])).pack(side="left", padx=12, pady=12)
        make_label(self.warning_area, "扉が閉まっていません。扉を閉めてください。", 20, True,
                   YELLOW_TAG[0]).pack(side="left", padx=(0, 12))

        self.watch_door()

    def watch_door(self):
        locked = self.app.lock.is_locked()
        now = time.monotonic()

        if self.state == "待ち":
            if not locked:
                self.state = "開いた"
                self.open_time = now
                self.guide_label.configure(text=self.what_to_do)
                self.note_label.configure(text="扉を閉めると、記録して完了します。")
            elif now - self.start_time > config.DOOR_OPEN_WAIT_SECONDS:
                self.give_up()
                return
            else:
                remaining = int(config.DOOR_OPEN_WAIT_SECONDS - (now - self.start_time))
                text = f"あと {remaining} 秒以内に扉を開けてください。開けないと取り消しになります。"
                if self.note_label.cget("text") != text:
                    self.note_label.configure(text=text)

        elif self.state == "開いた":
            if locked:
                self.finish()
                return
            if now - self.open_time > config.DOOR_CLOSE_WARN_SECONDS and not self.warning_area.winfo_ismapped():
                log.warning("扉が閉まっていません")
                self.warning_area.pack(fill="x", pady=(14, 0))

        self.run_later(200, self.watch_door)

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
            self.app.database.cancel(self.action, self.user, "扉が開かれなかったため")
        except Exception as e:
            self.app.show_error(e)
            return
        log.info("%sの取り消し(扉が開かれなかった): %s", self.action, self.user["employee_number"])
        export.update_excel(self.app.database)
        self.app.show(MessageScreen, title=f"{self.action}を取り消しました",
                      message="扉が開かれなかったため、取り消しました。もう一度最初からやり直してください。",
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
    def __init__(self, app, title, message, retry=None, retry_text="もう一度", tag="エラー"):
        super().__init__(app)
        make_tag(self.top_area, f"  {tag}  ", RED_TAG).pack(anchor="w", pady=(0, 10))
        self.show_title(title, message, ERROR_TEXT_COLOR)
        self.add_left_button("ホームに戻る", app.go_home)
        if retry is not None:
            self.add_right_button(retry_text, retry)
