"""
貸出・返却の流れの画面

貸出(5手順):
    HomeScreen → CardScanScreen → CameraSelectScreen → HoursSelectScreen
               → BorrowConfirmScreen → DoneScreen → HomeScreen

返却(3手順):
    HomeScreen → CardScanScreen → ReturnConfirmScreen → DoneScreen → HomeScreen

解錠に失敗したとき:
    → UnlockFailedScreen(もう一度開ける / 貸出を取り消す / 管理者に連絡する)

エラーや注意の表示:
    → MessageScreen

【1画面1操作】
    カメラ選択と貸出時間の選択は、画面を分けています。
    1画面でやることを1つに絞ると、「何を押せばいいか」で迷わなくなるためです。
    選択肢は押した時点で次の画面へ進みます(券売機と同じ操作)。

【画面とスレッドのルール】
    社員証の読み取りは「待つ」処理なので、別スレッドで行います。
    ただし、CustomTkinter の部品は別スレッドから触ってはいけないので、
        別スレッド : 読み取り結果を queue に入れるだけ
        画面       : after() で定期的に queue を確認して画面を更新
    という役割分担にしています(CardScanScreen 参照)。
"""

import logging
import queue
import threading
import time

import customtkinter

from camera_rental import errors
from camera_rental.gui import theme
from camera_rental.gui.widgets import (
    CAMERA_STATUS_TAG_KIND,
    BaseScreen,
    InfoTable,
    Pager,
    choice_button,
    horizontal_line,
    label,
    primary_button,
    secondary_button,
    set_button_enabled,
    status_tag,
)
from camera_rental.models import format_for_display
from camera_rental.rental_service import PURPOSE_BORROW, PURPOSE_RETURN

logger = logging.getLogger(__name__)


# 画面上部に出す手順の名前
BORROW_STEP_NAMES = ["社員証", "カメラ", "貸出時間", "確認", "完了"]
RETURN_STEP_NAMES = ["社員証", "確認", "完了"]


def step_names_for(purpose):
    if purpose == PURPOSE_BORROW:
        return BORROW_STEP_NAMES
    return RETURN_STEP_NAMES


# ======================================================
# ホーム
# ======================================================

class HomeScreen(BaseScreen):
    """
    最初の画面

    配置:
        左: カメラごとの状態の一覧(どれが借りられるか一目で分かるように)
        右: 「カメラを借りる」「カメラを返す」の2つだけ
    """

    CAMERAS_PER_PAGE = 5

    def __init__(self, parent, app):
        super().__init__(parent, app)

        self.lock_is_ready = self.app.service.lock_controller.is_ready

        if not self.lock_is_ready:
            stop_label = label(
                self.title_area,
                "扉のロックが使えないため、貸出・返却を停止しています。管理者に連絡してください。",
                bold=True,
                color=theme.ERROR_TEXT,
            )
            stop_label.pack(anchor="w")

        self.content_area.grid_columnconfigure(0, weight=1)
        self.content_area.grid_columnconfigure(1, weight=0)
        self.content_area.grid_rowconfigure(0, weight=1)

        self._build_camera_list()
        self._build_action_buttons()

        # 左下: 履歴(戻る ボタンの位置。ホームには戻る先がないので補助機能を置く)
        from camera_rental.gui.screens_info import HistoryScreen
        self.add_back_button("履歴を見る", lambda: self.app.show_screen(HistoryScreen))

    def _build_camera_list(self):
        list_column = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        list_column.grid(row=0, column=0, sticky="nsew", padx=(0, 32))

        heading = label(list_column, "カメラの状態", size=theme.FONT_SIZE_TITLE - 4, bold=True)
        heading.pack(anchor="w", pady=(0, 8))

        try:
            status_rows = self.app.service.list_camera_statuses()
        except errors.CameraRentalError as error:
            # ホームでエラー画面に飛ばすと、戻ってもまたエラーになるので、ここに表示する
            error_label = label(list_column, f"{error.title}。{error.user_message}", color=theme.ERROR_TEXT)
            error_label.pack(anchor="w")
            return

        if not status_rows:
            empty_label = label(list_column, "カメラが登録されていません。", color=theme.TEXT_SUB)
            empty_label.pack(anchor="w")
            return

        self.now = self.app.service.now()
        pager = Pager(list_column, status_rows, self.CAMERAS_PER_PAGE, self._render_camera_rows)
        pager.pack(fill="both", expand=True)

    def _render_camera_rows(self, list_frame, rows_on_page):
        """カメラ1台につき1行: 名前 / 状態 / 返却予定"""
        table = customtkinter.CTkFrame(list_frame, fg_color="transparent")
        table.pack(fill="x")
        table.grid_columnconfigure(0, weight=1)

        top_line = horizontal_line(table)
        top_line.grid(row=0, column=0, columnspan=3, sticky="ew")

        for index, status_row in enumerate(rows_on_page):
            camera = status_row.camera
            rental = status_row.rental
            grid_row = index * 2 + 1

            name_label = label(table, camera.name, bold=True)
            name_label.grid(row=grid_row, column=0, sticky="w", pady=14)

            tag = status_tag(table, camera.status_label, CAMERA_STATUS_TAG_KIND.get(camera.status, "neutral"))
            tag.grid(row=grid_row, column=1, sticky="w", padx=16)

            detail_text, detail_color = self._detail_for(rental)
            detail_label = label(table, detail_text, size=theme.FONT_SIZE_SMALL, color=detail_color)
            detail_label.configure(width=130)
            detail_label.grid(row=grid_row, column=2, sticky="w")

            line = horizontal_line(table)
            line.grid(row=grid_row + 1, column=0, columnspan=3, sticky="ew")

    def _detail_for(self, rental):
        """貸出中なら返却予定を表示する(延滞なら赤)"""
        if rental is None:
            return "", theme.TEXT_SUB
        # 一覧の幅に収まるよう、年は省いて「11/12 01:49」の形にする
        due_text = rental.due_at.strftime("%m/%d %H:%M")
        if rental.is_overdue(self.now):
            return f"延滞 {due_text}", theme.ERROR_TEXT
        return f"返却 {due_text}", theme.TEXT_SUB

    def _build_action_buttons(self):
        button_column = customtkinter.CTkFrame(self.content_area, fg_color="transparent", width=280)
        button_column.grid(row=0, column=1, sticky="ns")

        borrow_button = primary_button(button_column, "カメラを借りる", self._start_borrow,
                                       width=280, height=130)
        borrow_button.configure(font=theme.font(theme.FONT_SIZE_LARGE - 2, bold=True))
        borrow_button.pack(pady=(44, 20))

        return_button = primary_button(button_column, "カメラを返す", self._start_return,
                                       width=280, height=130)
        return_button.configure(font=theme.font(theme.FONT_SIZE_LARGE - 2, bold=True))
        return_button.pack()

        if not self.lock_is_ready:
            set_button_enabled(borrow_button, False)
            set_button_enabled(return_button, False)

    def _start_borrow(self):
        # 社員証をかざしてもらう前に、借りられるカメラがあるか確認する
        # (かざした後で「1台もありません」と言われるのを避けるため)
        try:
            has_camera = self.app.service.has_available_camera()
        except Exception as error:
            self.app.show_error(error)
            return

        if not has_camera:
            self.app.show_error(errors.NoAvailableCameraError())
            return

        self.app.show_screen(CardScanScreen, purpose=PURPOSE_BORROW)

    def _start_return(self):
        self.app.show_screen(CardScanScreen, purpose=PURPOSE_RETURN)


# ======================================================
# 社員証の読み取り
# ======================================================

class CardScanScreen(BaseScreen):
    """社員証をかざしてもらう画面"""

    # 読み取り中は、無操作タイムアウトではなく読み取りのタイムアウトを使う
    idle_timeout_enabled = False

    # 読み取り結果を確認する間隔(ミリ秒)
    POLL_INTERVAL_MS = 100

    def __init__(self, parent, app, purpose):
        super().__init__(parent, app)
        self.purpose = purpose
        self.timeout_seconds = self.app.settings.CARD_READ_TIMEOUT_SECONDS

        self.show_steps(step_names_for(purpose), 0)
        self.set_title("社員証をカードリーダーにかざしてください")

        self.remaining_label = label(self.title_area, "", color=theme.TEXT_SUB)
        self.remaining_label.pack(anchor="w", pady=(6, 0))

        if self.app.demo_mode:
            self._build_demo_buttons()

        self.add_back_button("やめる", self.app.go_home)

        # 別スレッドとのやり取りに使うもの
        self.cancel_event = threading.Event()
        self.result_queue = queue.Queue()
        self.start_time = time.monotonic()

        self._start_reading()

    def _build_demo_buttons(self):
        """デモモード専用: どの社員証をかざしたことにするか選ぶボタン"""
        demo_frame = customtkinter.CTkFrame(
            self.content_area,
            fg_color=theme.WARNING_BACKGROUND,
            corner_radius=theme.CORNER_RADIUS,
        )
        demo_frame.pack(side="bottom", fill="x")

        demo_label = label(demo_frame, "デモ用:かざす社員証を選ぶ",
                           size=theme.FONT_SIZE_SMALL, bold=True, color=theme.WARNING_TEXT)
        demo_label.pack(anchor="w", padx=16, pady=(10, 6))

        buttons_frame = customtkinter.CTkFrame(demo_frame, fg_color="transparent")
        buttons_frame.pack(fill="x", padx=16, pady=(0, 14))

        for display_name, card_id in self.app.card_reader.demo_cards:
            demo_button = secondary_button(
                buttons_frame,
                display_name,
                lambda selected_card_id=card_id: self.app.card_reader.simulate_touch(selected_card_id),
                width=160,
                height=48,
            )
            demo_button.configure(font=theme.font(theme.FONT_SIZE_SMALL))
            demo_button.pack(side="left", padx=(0, 8))

    # ---------- 読み取り ----------

    def _start_reading(self):
        reader_thread = threading.Thread(
            target=self._read_card_in_background,
            name="card-reader",
            daemon=True,
        )
        reader_thread.start()
        self._update_remaining_text()
        self.schedule(self.POLL_INTERVAL_MS, self._check_read_result)

    def _read_card_in_background(self):
        """
        【別スレッドで動く処理】

        ここでは画面の部品に一切触らず、結果を queue に入れるだけにします。
        """
        try:
            card_id = self.app.card_reader.read_card(self.timeout_seconds, self.cancel_event)
            self.result_queue.put(("card", card_id))
        except Exception as error:
            self.result_queue.put(("error", error))

    def _check_read_result(self):
        """【画面のスレッドで動く処理】読み取り結果が届いたか確認する"""
        try:
            result_type, result_value = self.result_queue.get_nowait()
        except queue.Empty:
            self._update_remaining_text()
            self.schedule(self.POLL_INTERVAL_MS, self._check_read_result)
            return

        if result_type == "error":
            self.app.show_error(result_value, retry_action=self._retry_scan, retry_label="もう一度かざす")
            return

        card_id = result_value
        if card_id is None:
            if self.cancel_event.is_set():
                return
            self._show_timeout()
            return

        self._handle_card(card_id)

    def _update_remaining_text(self):
        elapsed_seconds = time.monotonic() - self.start_time
        remaining_seconds = max(0, int(self.timeout_seconds - elapsed_seconds))
        self.remaining_label.configure(text=f"読み取るまで動かさずにお待ちください(残り {remaining_seconds} 秒)")

    def _retry_scan(self):
        self.app.show_screen(CardScanScreen, purpose=self.purpose)

    def _show_timeout(self):
        self.app.show_screen(
            MessageScreen,
            level="warning",
            title="社員証を確認できませんでした",
            message="待ち時間が過ぎました。もう一度かざしてください。",
            retry_action=self._retry_scan,
            retry_label="もう一度かざす",
        )

    # ---------- 読み取り後 ----------

    def _handle_card(self, card_id):
        """カードIDから利用者を確認し、次の画面へ進む"""
        try:
            user = self.app.service.authenticate(card_id)

            if self.purpose == PURPOSE_BORROW:
                cameras = self.app.service.get_borrowable_cameras(user)
                self.app.show_screen(CameraSelectScreen, user=user, cameras=cameras)
            else:
                rental = self.app.service.get_return_target(user)
                self.app.show_screen(ReturnConfirmScreen, user=user, rental=rental)

        except (errors.UnknownCardError, errors.UserDisabledError, errors.CardReadError) as error:
            # 別の社員証でやり直せるように「もう一度かざす」を出す
            self.app.show_error(error, retry_action=self._retry_scan, retry_label="もう一度かざす")
        except Exception as error:
            self.app.show_error(error)

    def on_leave(self):
        # 別スレッドの読み取りに「もう待たなくていい」と伝える
        self.cancel_event.set()
        super().on_leave()


# ======================================================
# 貸出: カメラの選択
# ======================================================

class CameraSelectScreen(BaseScreen):
    """借りるカメラを選ぶ画面(押すとすぐ次へ進む)"""

    CAMERAS_PER_PAGE = 4

    def __init__(self, parent, app, user, cameras):
        super().__init__(parent, app)
        self.user = user
        self.cameras = cameras

        self.show_steps(BORROW_STEP_NAMES, 1)
        self.set_title("借りるカメラを選んでください", note=f"{user.name} さん(社員番号 {user.employee_number})")

        pager = Pager(self.content_area, cameras, self.CAMERAS_PER_PAGE, self._render_cameras)
        pager.pack(fill="both", expand=True)

        self.add_back_button("やめる", self.app.go_home)

    def _render_cameras(self, list_frame, cameras_on_page):
        for camera in cameras_on_page:
            button = choice_button(
                list_frame,
                f"   {camera.name}",
                command=lambda selected_camera=camera: self._select(selected_camera),
            )
            button.pack(fill="x", pady=(0, 8))

    def _select(self, camera):
        self.app.show_screen(HoursSelectScreen, user=self.user, camera=camera)


# ======================================================
# 貸出: 貸出時間の選択
# ======================================================

class HoursSelectScreen(BaseScreen):
    """貸出時間を選ぶ画面(押すとすぐ次へ進む)"""

    def __init__(self, parent, app, user, camera):
        super().__init__(parent, app)
        self.user = user
        self.camera = camera

        self.show_steps(BORROW_STEP_NAMES, 2)
        self.set_title("貸出時間を選んでください", note=camera.name)

        # 返却予定の時刻は、ボタンの文字の中に書く(押す前に分かるように)
        self.hours_buttons = {}
        for hours in self.app.service.rental_hours_options:
            button = choice_button(
                self.content_area,
                "",
                command=lambda selected_hours=hours: self._select(selected_hours),
            )
            button.pack(fill="x", pady=(0, 8))
            self.hours_buttons[hours] = button

        self._update_button_texts()
        self.add_back_button("戻る", self._go_back)

    def _update_button_texts(self):
        """返却予定を最新の時刻で計算し直す(画面を開いたまま時間が過ぎても古くならない)"""
        for hours, button in self.hours_buttons.items():
            due_at = self.app.service.calculate_due_at(hours)
            button.configure(text=f"   {hours}時間      返却予定  {format_for_display(due_at)}")
        self.schedule(15_000, self._update_button_texts)

    def _select(self, hours):
        self.app.show_screen(BorrowConfirmScreen, user=self.user, camera=self.camera, rental_hours=hours)

    def _go_back(self):
        go_to_camera_select(self.app, self.user)


def go_to_camera_select(app, user):
    """カメラ選択へ戻る(戻る間にほかの人が借りた場合に備えて、一覧を取り直す)"""
    try:
        cameras = app.service.get_borrowable_cameras(user)
    except Exception as error:
        app.show_error(error)
        return
    app.show_screen(CameraSelectScreen, user=user, cameras=cameras)


# ======================================================
# 貸出: 確認
# ======================================================

class BorrowConfirmScreen(BaseScreen):
    """貸出内容の確認画面"""

    def __init__(self, parent, app, user, camera, rental_hours):
        super().__init__(parent, app)
        self.user = user
        self.camera = camera
        self.rental_hours = rental_hours

        self.show_steps(BORROW_STEP_NAMES, 3)
        self.set_title("この内容で貸し出します", note="「貸し出す」を押すと記録され、扉のロックが開きます。")

        due_at = self.app.service.calculate_due_at(rental_hours)
        info_table = InfoTable(
            self.content_area,
            [
                ("利用者", f"{user.name} さん"),
                ("カメラ", camera.name),
                ("貸出時間", f"{rental_hours}時間"),
                ("返却予定", format_for_display(due_at)),
            ],
        )
        info_table.pack(fill="x")

        self.back_button = self.add_back_button("戻る", self._go_back)
        self.confirm_button = self.add_next_button("貸し出す", self._confirm)

    def _go_back(self):
        self.app.show_screen(HoursSelectScreen, user=self.user, camera=self.camera)

    def _confirm(self):
        # 二度押しで2回処理されないよう、最初にボタンを無効にする
        set_button_enabled(self.confirm_button, False)
        self.back_button.configure(state="disabled")
        self.confirm_button.configure(text="記録しています")
        self.update_idletasks()

        try:
            result = self.app.service.borrow_camera(self.user, self.camera.id, self.rental_hours)
        except Exception as error:
            # DB記録に失敗 or 確認中にほかの人が借りた → 解錠はされていない
            self.app.show_error(error)
            return

        show_unlock_result(self.app, result)


# ======================================================
# 返却: 確認
# ======================================================

class ReturnConfirmScreen(BaseScreen):
    """返却対象の確認画面"""

    def __init__(self, parent, app, user, rental):
        super().__init__(parent, app)
        self.user = user
        self.rental = rental

        self.show_steps(RETURN_STEP_NAMES, 1)
        self.set_title("このカメラを返却します", note="「返却する」を押すと記録され、扉のロックが開きます。")

        info_table = InfoTable(
            self.content_area,
            [
                ("利用者", f"{user.name} さん"),
                ("カメラ", rental.camera_name),
                ("貸出日時", format_for_display(rental.rented_at)),
                ("返却予定", format_for_display(rental.due_at)),
            ],
        )
        info_table.pack(fill="x")

        if rental.is_overdue(self.app.service.now()):
            overdue_label = label(
                self.content_area,
                "返却予定を過ぎています。このまま返却できます。",
                bold=True,
                color=theme.WARNING_TEXT,
            )
            overdue_label.pack(anchor="w", pady=(16, 0))

        self.cancel_button = self.add_back_button("やめる", self.app.go_home)
        self.confirm_button = self.add_next_button("返却する", self._confirm)

    def _confirm(self):
        set_button_enabled(self.confirm_button, False)
        self.cancel_button.configure(state="disabled")
        self.confirm_button.configure(text="記録しています")
        self.update_idletasks()

        try:
            result = self.app.service.return_camera(self.user, self.rental.id)
        except Exception as error:
            self.app.show_error(error)
            return

        show_unlock_result(self.app, result)


def show_unlock_result(app, result):
    """解錠に成功したか失敗したかで、次の画面を切り替える"""
    if result.unlocked:
        app.show_screen(DoneScreen, result=result)
    else:
        app.show_screen(UnlockFailedScreen, result=result)


# ======================================================
# 完了(扉が開いている間)
# ======================================================

class DoneScreen(BaseScreen):
    """
    完了画面

    手続きはもう終わっているので、ここでは「次に利用者がすること」だけを大きく出します。
    扉が施錠に戻るまでの秒数を表示し、時間が来たらホームへ戻ります。
    """

    # 扉が開いている間は、無操作タイムアウトではなくこの画面の秒読みを使う
    idle_timeout_enabled = False

    def __init__(self, parent, app, result):
        super().__init__(parent, app)
        self.remaining_seconds = self.app.settings.UNLOCK_SECONDS
        rental = result.rental

        step_names = step_names_for(result.purpose)
        self.show_steps(step_names, len(step_names) - 1)

        if result.purpose == PURPOSE_BORROW:
            tag_text = "貸出完了"
            instruction = "扉が開きました。\nカメラを取り出して、扉を閉めてください。"
            detail = f"{rental.camera_name}   返却予定  {format_for_display(rental.due_at)}"
        else:
            tag_text = "返却完了"
            instruction = "扉が開きました。\nカメラを元の場所に置いて、扉を閉めてください。"
            detail = rental.camera_name

        tag = status_tag(self.title_area, tag_text, "success", width=120)
        tag.pack(anchor="w", pady=(0, 16))

        instruction_label = label(self.title_area, instruction, size=theme.FONT_SIZE_LARGE + 4, bold=True)
        instruction_label.pack(anchor="w")

        detail_label = label(self.content_area, detail, color=theme.TEXT_SUB)
        detail_label.pack(anchor="w")

        self.countdown_label = label(self.content_area, "", color=theme.TEXT_SUB)
        self.countdown_label.pack(anchor="w", pady=(6, 0))

        self.add_next_button("ホームに戻る", self.app.go_home)

        self._count_down()

    def _count_down(self):
        if self.remaining_seconds <= 0:
            self.app.go_home()
            return
        self.countdown_label.configure(
            text=f"{self.remaining_seconds} 秒後に扉のロックがかかり、ホームに戻ります。"
        )
        self.remaining_seconds -= 1
        self.schedule(1000, self._count_down)


# ======================================================
# 解錠失敗
# ======================================================

class UnlockFailedScreen(BaseScreen):
    """
    DB には記録できたが、解錠に失敗したときの画面

    受付番号(貸出ID)を表示して、利用者と管理者が同じ番号で話せるようにします。
    """

    def __init__(self, parent, app, result, attempt_number=1):
        super().__init__(parent, app)
        self.result = result
        self.rental = result.rental
        self.attempt_number = attempt_number

        step_names = step_names_for(result.purpose)
        self.show_steps(step_names, len(step_names) - 1)

        if result.purpose == PURPOSE_BORROW:
            note = "貸出は記録されています。もう一度開けるか、貸出を取り消してください。"
        else:
            note = "返却は記録されています。このカメラは点検中にしました。"

        self.set_title("扉が開きませんでした", note=note, title_color=theme.ERROR_TEXT)

        info_table = InfoTable(
            self.content_area,
            [
                ("受付番号", f"{self.rental.id}"),
                ("カメラ", self.rental.camera_name),
                ("開けた回数", f"{attempt_number} 回"),
            ],
        )
        info_table.pack(fill="x")

        if result.purpose == PURPOSE_BORROW:
            self.add_back_button("貸出を取り消す", self._cancel_borrow)
        else:
            self.add_back_button("管理者に連絡する", self._contact_admin)

        self.retry_button = self.add_next_button("もう一度開ける", self._retry_unlock)

    def _retry_unlock(self):
        set_button_enabled(self.retry_button, False)
        self.update_idletasks()

        try:
            new_result = self.app.service.retry_unlock(self.rental, self.result.purpose)
        except Exception as error:
            self.app.show_error(error)
            return

        if new_result.unlocked:
            self.app.show_screen(DoneScreen, result=new_result)
        else:
            self.app.show_screen(
                UnlockFailedScreen,
                result=new_result,
                attempt_number=self.attempt_number + 1,
            )

    def _cancel_borrow(self):
        try:
            self.app.service.cancel_borrow_after_unlock_failure(self.rental)
        except Exception as error:
            self.app.show_error(error)
            return

        self.app.show_screen(
            MessageScreen,
            level="info",
            title="貸出を取り消しました",
            message=f"受付番号 {self.rental.id}。扉が開かない場合は管理者に連絡してください。",
        )

    def _contact_admin(self):
        self.app.show_screen(
            MessageScreen,
            level="warning",
            title="管理者に連絡してください",
            message=f"受付番号 {self.rental.id}。カメラは手元で保管してください。",
        )

    def on_idle_timeout(self):
        """
        この画面のまま放置された場合

        ・貸出: カメラを取り出せていないので、貸出を取り消してホームへ
                (そのままだと本人が「未返却」扱いになり、次から借りられなくなるため)
        ・返却: すでに返却・点検中の記録済みなので、そのままホームへ
        """
        if self.result.purpose == PURPOSE_BORROW:
            try:
                self.app.service.cancel_borrow_after_unlock_failure(self.rental)
            except Exception:
                logger.exception("放置された解錠失敗の貸出を取り消せませんでした: rental_id=%s", self.rental.id)
        self.app.go_home()


# ======================================================
# お知らせ・エラー
# ======================================================

class MessageScreen(BaseScreen):
    """
    エラー・注意・お知らせを表示する汎用画面

    「何が起きたか」を見出しに、「次に何をするか」を1行で書きます。
    """

    # レベル → (札の文字, 札の種類, 見出しの色)
    LEVEL_STYLES = {
        "error": ("エラー", "error", theme.ERROR_TEXT),
        "warning": ("注意", "warning", theme.TEXT_MAIN),
        "info": ("お知らせ", "info", theme.TEXT_MAIN),
        "success": ("完了", "success", theme.TEXT_MAIN),
    }

    def __init__(self, parent, app, level, title, message, retry_action=None, retry_label="もう一度試す"):
        super().__init__(parent, app)

        tag_text, tag_kind, title_color = self.LEVEL_STYLES[level]

        tag = status_tag(self.title_area, tag_text, tag_kind)
        tag.pack(anchor="w", pady=(0, 16))

        self.set_title(title, note=message, title_color=title_color)

        self.add_back_button("ホームに戻る", self.app.go_home)

        if retry_action is not None:
            self.add_next_button(retry_label, retry_action)
