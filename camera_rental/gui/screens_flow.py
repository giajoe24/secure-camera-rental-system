"""
貸出・返却の流れの画面

貸出:
    HomeScreen → CardScanScreen → CameraSelectScreen → BorrowConfirmScreen
               → UnlockedScreen → CompleteScreen → HomeScreen

返却:
    HomeScreen → CardScanScreen → ReturnConfirmScreen
               → UnlockedScreen → CompleteScreen → HomeScreen

解錠に失敗したとき:
    → UnlockFailedScreen(再試行 / 貸出取消 / 管理者へ連絡)

エラーや注意の表示:
    → MessageScreen

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
    CAMERA_STATUS_BADGE_KIND,
    BaseScreen,
    InfoTable,
    MessagePanel,
    Pager,
    StatusBadge,
    circle_icon,
    label,
    primary_button,
    secondary_button,
    set_button_enabled,
)
from camera_rental.models import format_for_display
from camera_rental.rental_service import PURPOSE_BORROW, PURPOSE_RETURN

logger = logging.getLogger(__name__)


# 画面上部に出す手順の表示
BORROW_STEPS = 4
RETURN_STEPS = 3


def borrow_step_text(step_number, step_name):
    return f"貸出  {step_number} / {BORROW_STEPS}  {step_name}"


def return_step_text(step_number, step_name):
    return f"返却  {step_number} / {RETURN_STEPS}  {step_name}"


# ======================================================
# ホーム
# ======================================================

class HomeScreen(BaseScreen):
    """最初の画面: 貸出 / 返却 を選ぶ"""

    def __init__(self, parent, app):
        super().__init__(parent, app)

        self.set_title("ご用件を選んでください")

        lock_is_ready = self.app.service.lock_controller.is_ready
        if not lock_is_ready:
            warning_panel = MessagePanel(
                self.content_area,
                kind="error",
                title="電磁ロックが使用できないため、貸出・返却を停止しています",
                message="管理者に連絡してください。(貸出状況と履歴は確認できます)",
            )
            warning_panel.pack(fill="x", pady=(0, 16))

        self._build_summary()
        self._build_main_buttons(enabled=lock_is_ready)
        self._build_bottom_buttons()

    def _build_summary(self):
        """カメラの台数を状態ごとに表示する"""
        summary_frame = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        summary_frame.pack(fill="x", pady=(0, 16))

        try:
            status_rows = self.app.service.list_camera_statuses()
        except errors.CameraRentalError as error:
            # ホーム画面でエラー画面に飛ばすと、戻ってもまたエラーになるので、ここに表示する
            error_label = label(summary_frame, f"{error.title}: {error.user_message}", color=theme.ERROR_TEXT)
            error_label.pack(anchor="w")
            return

        counts = {"available": 0, "rented": 0, "maintenance": 0}
        for row in status_rows:
            if row.camera.status in counts:
                counts[row.camera.status] += 1

        caption = label(summary_frame, "現在のカメラ:", color=theme.TEXT_SUB)
        caption.pack(side="left", padx=(0, 12))

        status_texts = [
            ("available", "貸出可能"),
            ("rented", "貸出中"),
            ("maintenance", "点検中"),
        ]
        for status, status_name in status_texts:
            badge = StatusBadge(
                summary_frame,
                f"{status_name} {counts[status]}台",
                CAMERA_STATUS_BADGE_KIND[status],
            )
            badge.pack(side="left", padx=(0, 8))

    def _build_main_buttons(self, enabled):
        """大きな「借りる」「返す」ボタン"""
        tiles_frame = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        tiles_frame.pack(fill="both", expand=True)
        tiles_frame.grid_columnconfigure(0, weight=1, uniform="tile")
        tiles_frame.grid_columnconfigure(1, weight=1, uniform="tile")
        tiles_frame.grid_rowconfigure(0, weight=1)

        borrow_button = primary_button(tiles_frame, "カメラを借りる\n(貸出)", self._start_borrow,
                                       height=theme.TILE_HEIGHT)
        borrow_button.configure(font=theme.font(theme.FONT_SIZE_TILE, bold=True))
        borrow_button.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        return_button = primary_button(tiles_frame, "カメラを返す\n(返却)", self._start_return,
                                       height=theme.TILE_HEIGHT)
        return_button.configure(font=theme.font(theme.FONT_SIZE_TILE, bold=True))
        return_button.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

        if not enabled:
            set_button_enabled(borrow_button, False)
            set_button_enabled(return_button, False)

        guide_label = label(
            self.content_area,
            "ボタンを押したあと、社員証をカードリーダーにかざします。",
            color=theme.TEXT_SUB,
        )
        guide_label.pack(anchor="w", pady=(12, 0))

    def _build_bottom_buttons(self):
        # 画面の切り替え先は、ここで読み込む(ファイル同士の循環 import を避けるため)
        from camera_rental.gui.screens_info import HistoryScreen, StatusScreen

        status_button = secondary_button(self.bottom_area, "貸出状況を見る",
                                         lambda: self.app.show_screen(StatusScreen))
        status_button.pack(side="left")

        history_button = secondary_button(self.bottom_area, "履歴を見る",
                                          lambda: self.app.show_screen(HistoryScreen))
        history_button.pack(side="left", padx=(12, 0))

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

        if purpose == PURPOSE_BORROW:
            self.set_title("社員証をかざしてください", step_text=borrow_step_text(1, "本人確認"))
        else:
            self.set_title("社員証をかざしてください", step_text=return_step_text(1, "本人確認"))

        self._build_scan_panel()
        if self.app.demo_mode:
            self._build_demo_buttons()

        cancel_button = secondary_button(self.bottom_area, "やめる", self.app.go_home)
        cancel_button.pack(side="left")

        # 別スレッドとのやり取りに使うもの
        self.cancel_event = threading.Event()
        self.result_queue = queue.Queue()
        self.start_time = time.monotonic()

        self._start_reading()

    def _build_scan_panel(self):
        """薄い赤背景の、読み取り案内パネル"""
        scan_panel = customtkinter.CTkFrame(
            self.content_area,
            fg_color=theme.BRAND_RED_LIGHT,
            border_color=theme.BRAND_RED_BORDER,
            border_width=2,
            corner_radius=theme.CORNER_RADIUS,
        )
        scan_panel.pack(fill="both", expand=True)

        inner_frame = customtkinter.CTkFrame(scan_panel, fg_color="transparent")
        inner_frame.place(relx=0.5, rely=0.5, anchor="center")

        # カードの形をした簡単な図(画像を使わずに枠で表現)
        card_shape = customtkinter.CTkFrame(
            inner_frame,
            width=150,
            height=95,
            fg_color=theme.WHITE,
            border_color=theme.BRAND_RED,
            border_width=3,
            corner_radius=12,
        )
        card_shape.pack(pady=(0, 16))
        card_shape.pack_propagate(False)
        card_text = label(card_shape, "社員証", size=theme.FONT_SIZE_HEADING, bold=True,
                          color=theme.BRAND_RED, anchor="center")
        card_text.pack(expand=True)

        instruction_label = label(
            inner_frame,
            "カードリーダーの上に、社員証を動かさずに置いてください",
            size=theme.FONT_SIZE_HEADING,
            bold=True,
            anchor="center",
            justify="center",
        )
        instruction_label.pack()

        self.status_label = label(inner_frame, "読み取り待ち…", color=theme.TEXT_SUB, anchor="center")
        self.status_label.pack(pady=(8, 0))

    def _build_demo_buttons(self):
        """デモモード専用: どの社員証をかざしたことにするか選ぶボタン"""
        demo_frame = customtkinter.CTkFrame(
            self.content_area,
            fg_color=theme.WARNING_BACKGROUND,
            corner_radius=theme.CORNER_RADIUS,
        )
        demo_frame.pack(fill="x", pady=(12, 0))

        demo_label = label(demo_frame, "デモ: かざす社員証を選んでください",
                           size=theme.FONT_SIZE_SMALL, bold=True, color=theme.WARNING_TEXT)
        demo_label.pack(anchor="w", padx=16, pady=(10, 4))

        buttons_frame = customtkinter.CTkFrame(demo_frame, fg_color="transparent")
        buttons_frame.pack(fill="x", padx=16, pady=(0, 12))

        for display_name, card_id in self.app.card_reader.demo_cards:
            demo_button = customtkinter.CTkButton(
                buttons_frame,
                text=display_name,
                height=48,
                width=170,
                corner_radius=10,
                fg_color=theme.WHITE,
                hover_color=theme.SECONDARY_BUTTON,
                text_color=theme.TEXT_MAIN,
                border_color=theme.WARNING_BORDER,
                border_width=2,
                font=theme.font(theme.FONT_SIZE_SMALL, bold=True),
                command=lambda selected_card_id=card_id: self.app.card_reader.simulate_touch(selected_card_id),
            )
            demo_button.pack(side="left", padx=(0, 8))

    # ---------- 読み取り ----------

    def _start_reading(self):
        reader_thread = threading.Thread(
            target=self._read_card_in_background,
            name="card-reader",
            daemon=True,
        )
        reader_thread.start()
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
            self._update_waiting_text()
            self.schedule(self.POLL_INTERVAL_MS, self._check_read_result)
            return

        if result_type == "error":
            self._show_read_error(result_value)
            return

        card_id = result_value
        if card_id is None:
            if self.cancel_event.is_set():
                return
            self._show_timeout()
            return

        self._handle_card(card_id)

    def _update_waiting_text(self):
        elapsed_seconds = time.monotonic() - self.start_time
        remaining_seconds = max(0, int(self.timeout_seconds - elapsed_seconds))
        dot_count = int(elapsed_seconds * 2) % 4
        dots = "・" * dot_count
        self.status_label.configure(text=f"読み取り待ち{dots}  (あと {remaining_seconds} 秒)")

    def _retry_scan(self):
        self.app.show_screen(CardScanScreen, purpose=self.purpose)

    def _show_read_error(self, error):
        self.app.show_error(error, retry_action=self._retry_scan)

    def _show_timeout(self):
        self.app.show_screen(
            MessageScreen,
            level="warning",
            title="社員証が確認できませんでした",
            message="読み取りの待ち時間が終わりました。\nもう一度お試しください。",
            retry_action=self._retry_scan,
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
            self.app.show_error(error, retry_action=self._retry_scan)
        except Exception as error:
            self.app.show_error(error)

    def on_leave(self):
        # 別スレッドの読み取りに「もう待たなくていい」と伝える
        self.cancel_event.set()
        super().on_leave()


# ======================================================
# 貸出: カメラと貸出時間の選択
# ======================================================

class CameraSelectScreen(BaseScreen):
    """カメラと貸出時間を選ぶ画面"""

    CAMERAS_PER_PAGE = 4

    def __init__(self, parent, app, user, cameras, selected_camera_id=None, selected_hours=None):
        super().__init__(parent, app)
        self.user = user
        self.cameras = cameras
        self.selected_camera_id = selected_camera_id
        self.selected_hours = selected_hours

        self.camera_buttons = {}
        self.hours_buttons = {}

        self.set_title(
            "カメラと貸出時間を選んでください",
            step_text=borrow_step_text(2, "カメラと時間の選択"),
            subtitle=f"{user.name} さん(社員番号 {user.employee_number})",
        )

        self.content_area.grid_columnconfigure(0, weight=3, uniform="column")
        self.content_area.grid_columnconfigure(1, weight=2, uniform="column")
        self.content_area.grid_rowconfigure(0, weight=1)

        self._build_camera_list()
        self._build_hours_selector()
        self._build_bottom_buttons()

        self._refresh_selection()
        self._update_due_text_regularly()

    def _build_camera_list(self):
        camera_column = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        camera_column.grid(row=0, column=0, sticky="nsew", padx=(0, 16))

        heading = label(camera_column, "1. カメラ", size=theme.FONT_SIZE_HEADING, bold=True)
        heading.pack(anchor="w", pady=(0, 8))

        pager = Pager(camera_column, self.cameras, self.CAMERAS_PER_PAGE, self._render_camera_page)
        pager.pack(fill="both", expand=True)

    def _render_camera_page(self, list_frame, cameras_on_page):
        """ページに表示するカメラのボタンを作る(ページ送りのたびに呼ばれる)"""
        self.camera_buttons = {}
        for camera in cameras_on_page:
            camera_button = customtkinter.CTkButton(
                list_frame,
                text=camera.name,
                height=58,
                anchor="w",
                corner_radius=12,
                border_width=2,
                font=theme.font(theme.FONT_SIZE_BODY, bold=True),
                command=lambda camera_id=camera.id: self._select_camera(camera_id),
            )
            camera_button.pack(fill="x", pady=4)
            self.camera_buttons[camera.id] = camera_button
        self._refresh_selection()

    def _build_hours_selector(self):
        hours_column = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        hours_column.grid(row=0, column=1, sticky="nsew")

        heading = label(hours_column, "2. 貸出時間", size=theme.FONT_SIZE_HEADING, bold=True)
        heading.pack(anchor="w", pady=(0, 8))

        buttons_grid = customtkinter.CTkFrame(hours_column, fg_color="transparent")
        buttons_grid.pack(fill="x")
        buttons_grid.grid_columnconfigure(0, weight=1, uniform="hours")
        buttons_grid.grid_columnconfigure(1, weight=1, uniform="hours")

        # 貸出時間の候補は config.RENTAL_HOURS_OPTIONS から作る(2列で並べる)
        for index, hours in enumerate(self.app.service.rental_hours_options):
            hours_button = customtkinter.CTkButton(
                buttons_grid,
                text=f"{hours}時間",
                height=64,
                corner_radius=12,
                border_width=2,
                font=theme.font(theme.FONT_SIZE_BUTTON, bold=True),
                command=lambda selected=hours: self._select_hours(selected),
            )
            row_number = index // 2
            column_number = index % 2
            hours_button.grid(row=row_number, column=column_number, sticky="ew", padx=4, pady=4)
            self.hours_buttons[hours] = hours_button

        due_caption = label(hours_column, "返却予定日時", color=theme.TEXT_SUB)
        due_caption.pack(anchor="w", pady=(20, 0))

        self.due_label = label(hours_column, "-", size=theme.FONT_SIZE_HEADING, bold=True)
        self.due_label.pack(anchor="w")

    def _build_bottom_buttons(self):
        cancel_button = secondary_button(self.bottom_area, "やめる", self.app.go_home)
        cancel_button.pack(side="left")

        self.next_button = primary_button(self.bottom_area, "確認へ進む", self._go_to_confirm)
        self.next_button.pack(side="right")

    # ---------- 選択 ----------

    def _select_camera(self, camera_id):
        self.selected_camera_id = camera_id
        self._refresh_selection()

    def _select_hours(self, hours):
        self.selected_hours = hours
        self._refresh_selection()

    def _refresh_selection(self):
        """選ばれているボタンの見た目を変え、「確認へ進む」の有効/無効を切り替える"""
        for camera_id, button in self.camera_buttons.items():
            self._apply_toggle_style(button, camera_id == self.selected_camera_id)

        for hours, button in self.hours_buttons.items():
            self._apply_toggle_style(button, hours == self.selected_hours)

        self._update_due_text()

        if hasattr(self, "next_button"):
            both_selected = self.selected_camera_id is not None and self.selected_hours is not None
            set_button_enabled(self.next_button, both_selected)

    @staticmethod
    def _apply_toggle_style(button, is_selected):
        # 色だけでなく「✓」を付けて、選ばれていることが分かるようにする
        base_text = button.cget("text").removeprefix("✓ ")
        if is_selected:
            button.configure(
                text=f"✓ {base_text}",
                fg_color=theme.BRAND_RED_LIGHT,
                hover_color=theme.BRAND_RED_LIGHT,
                border_color=theme.BRAND_RED,
                text_color=theme.BRAND_RED,
            )
        else:
            button.configure(
                text=base_text,
                fg_color=theme.WHITE,
                hover_color=theme.APP_BACKGROUND,
                border_color=theme.BORDER,
                text_color=theme.TEXT_MAIN,
            )

    def _update_due_text(self):
        if not hasattr(self, "due_label"):
            return
        if self.selected_hours is None:
            self.due_label.configure(text="貸出時間を選んでください")
            return
        due_at = self.app.service.calculate_due_at(self.selected_hours)
        self.due_label.configure(text=format_for_display(due_at))

    def _update_due_text_regularly(self):
        """画面を開いたまま時間が過ぎても、返却予定が古くならないようにする"""
        self._update_due_text()
        self.schedule(15_000, self._update_due_text_regularly)

    def _go_to_confirm(self):
        selected_camera = None
        for camera in self.cameras:
            if camera.id == self.selected_camera_id:
                selected_camera = camera
        if selected_camera is None or self.selected_hours is None:
            return

        self.app.show_screen(
            BorrowConfirmScreen,
            user=self.user,
            camera=selected_camera,
            rental_hours=self.selected_hours,
        )


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

        self.set_title("貸出内容を確認してください", step_text=borrow_step_text(3, "内容の確認"))

        due_at = self.app.service.calculate_due_at(rental_hours)
        info_table = InfoTable(
            self.content_area,
            [
                ("利用者", f"{user.name} さん"),
                ("社員番号", user.employee_number),
                ("カメラ", camera.name),
                ("貸出時間", f"{rental_hours}時間"),
                ("返却予定日時", format_for_display(due_at)),
            ],
        )
        info_table.pack(anchor="w")

        notice_label = label(
            self.content_area,
            "「貸出を確定する」を押すと記録され、保管庫の扉のロックが開きます。\n"
            "※ 返却予定日時は、確定した時刻から計算します。",
            color=theme.TEXT_SUB,
        )
        notice_label.pack(anchor="w", pady=(20, 0))

        self.back_button = secondary_button(self.bottom_area, "戻る", self._go_back)
        self.back_button.pack(side="left")

        self.confirm_button = primary_button(self.bottom_area, "貸出を確定する", self._confirm, width=260)
        self.confirm_button.pack(side="right")

    def _go_back(self):
        try:
            cameras = self.app.service.get_borrowable_cameras(self.user)
        except Exception as error:
            self.app.show_error(error)
            return

        self.app.show_screen(
            CameraSelectScreen,
            user=self.user,
            cameras=cameras,
            selected_camera_id=self.camera.id,
            selected_hours=self.rental_hours,
        )

    def _confirm(self):
        # 二度押しで2回処理されないよう、最初にボタンを無効にする
        set_button_enabled(self.confirm_button, False)
        self.back_button.configure(state="disabled")
        self.confirm_button.configure(text="記録しています…")
        self.update_idletasks()

        try:
            result = self.app.service.borrow_camera(self.user, self.camera.id, self.rental_hours)
        except errors.CameraNotAvailableError as error:
            # 確認中にほかの人が借りた場合など
            self.app.show_error(error)
            return
        except Exception as error:
            # DB記録に失敗 → 解錠はされていない
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

        self.set_title(
            "このカメラを返却しますか?",
            step_text=return_step_text(2, "返却対象の確認"),
            subtitle=f"{user.name} さん(社員番号 {user.employee_number})",
        )

        now = self.app.service.now()
        if rental.is_overdue(now):
            overdue_panel = MessagePanel(
                self.content_area,
                kind="warning",
                title="返却予定日時を過ぎています",
                message="このまま返却できます。延滞の扱いは管理者の指示に従ってください。",
            )
            overdue_panel.pack(fill="x", pady=(0, 16))

        info_table = InfoTable(
            self.content_area,
            [
                ("カメラ", rental.camera_name),
                ("貸出日時", format_for_display(rental.rented_at)),
                ("返却予定日時", format_for_display(rental.due_at)),
            ],
        )
        info_table.pack(anchor="w")

        notice_label = label(
            self.content_area,
            "「返却する」を押すと記録され、保管庫の扉のロックが開きます。",
            color=theme.TEXT_SUB,
        )
        notice_label.pack(anchor="w", pady=(20, 0))

        self.cancel_button = secondary_button(self.bottom_area, "やめる", self.app.go_home)
        self.cancel_button.pack(side="left")

        self.confirm_button = primary_button(self.bottom_area, "返却する", self._confirm, width=260)
        self.confirm_button.pack(side="right")

    def _confirm(self):
        set_button_enabled(self.confirm_button, False)
        self.cancel_button.configure(state="disabled")
        self.confirm_button.configure(text="記録しています…")
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
        app.show_screen(UnlockedScreen, result=result)
    else:
        app.show_screen(UnlockFailedScreen, result=result)


# ======================================================
# 解錠中
# ======================================================

class UnlockedScreen(BaseScreen):
    """解錠した後の案内画面(カメラの取り出し / 返却)"""

    # 扉が開いている間は、ホームに戻さない
    idle_timeout_enabled = False

    def __init__(self, parent, app, result):
        super().__init__(parent, app)
        self.result = result
        self.remaining_seconds = self.app.settings.UNLOCK_SECONDS

        camera_name = result.rental.camera_name
        if result.purpose == PURPOSE_BORROW:
            step_text = borrow_step_text(4, "カメラの取り出し")
            instruction = f"扉を開けて「{camera_name}」を取り出し、扉を閉めてください。"
        else:
            step_text = return_step_text(3, "カメラの返却")
            instruction = f"扉を開けて「{camera_name}」を元の場所に戻し、扉を閉めてください。"

        self.set_title("扉のロックを開けました", step_text=step_text)

        green_panel = customtkinter.CTkFrame(
            self.content_area,
            fg_color=theme.SUCCESS_BACKGROUND,
            corner_radius=theme.CORNER_RADIUS,
        )
        green_panel.pack(fill="both", expand=True)

        inner_frame = customtkinter.CTkFrame(green_panel, fg_color="transparent")
        inner_frame.place(relx=0.5, rely=0.5, anchor="center")

        instruction_label = label(
            inner_frame,
            instruction,
            size=theme.FONT_SIZE_HEADING,
            bold=True,
            color=theme.SUCCESS_TEXT,
            wraplength=760,
            anchor="center",
            justify="center",
        )
        instruction_label.pack()

        self.countdown_label = label(inner_frame, "", size=theme.FONT_SIZE_TITLE, bold=True,
                                     color=theme.SUCCESS_TEXT, anchor="center")
        self.countdown_label.pack(pady=(16, 0))

        done_button = primary_button(self.bottom_area, "完了", self._finish)
        done_button.pack(side="right")

        self._count_down()

    def _count_down(self):
        if self.remaining_seconds <= 0:
            self._finish()
            return
        self.countdown_label.configure(text=f"あと {self.remaining_seconds} 秒で自動的に施錠されます")
        self.remaining_seconds -= 1
        self.schedule(1000, self._count_down)

    def _finish(self):
        self.app.show_screen(CompleteScreen, result=self.result)


# ======================================================
# 完了
# ======================================================

class CompleteScreen(BaseScreen):
    """完了画面(しばらくすると自動でホームへ戻る)"""

    def __init__(self, parent, app, result):
        super().__init__(parent, app)
        self.remaining_seconds = self.app.settings.COMPLETE_SCREEN_SECONDS
        rental = result.rental

        green_panel = customtkinter.CTkFrame(
            self.content_area,
            fg_color=theme.SUCCESS_BACKGROUND,
            corner_radius=theme.CORNER_RADIUS,
        )
        green_panel.pack(fill="both", expand=True)

        inner_frame = customtkinter.CTkFrame(green_panel, fg_color="transparent")
        inner_frame.place(relx=0.5, rely=0.5, anchor="center")

        check_mark = circle_icon(inner_frame, "✓", theme.SUCCESS_STRONG, diameter=110, font_size=60)
        check_mark.pack(pady=(0, 16))

        if result.purpose == PURPOSE_BORROW:
            title_text = "貸出が完了しました"
            detail_text = f"{rental.camera_name}\n返却予定: {format_for_display(rental.due_at)}"
        else:
            title_text = "返却が完了しました"
            detail_text = f"{rental.camera_name}\nご利用ありがとうございました"

        title_label = label(inner_frame, title_text, size=theme.FONT_SIZE_TITLE, bold=True,
                            color=theme.SUCCESS_TEXT, anchor="center")
        title_label.pack()

        detail_label = label(inner_frame, detail_text, anchor="center", justify="center")
        detail_label.pack(pady=(8, 0))

        self.countdown_label = label(self.bottom_area, "", color=theme.TEXT_SUB)
        self.countdown_label.pack(side="left")

        home_button = primary_button(self.bottom_area, "ホームへ", self.app.go_home)
        home_button.pack(side="right")

        self._count_down()

    def _count_down(self):
        if self.remaining_seconds <= 0:
            self.app.go_home()
            return
        self.countdown_label.configure(text=f"{self.remaining_seconds} 秒後にホームに戻ります")
        self.remaining_seconds -= 1
        self.schedule(1000, self._count_down)


# ======================================================
# 解錠失敗
# ======================================================

class UnlockFailedScreen(BaseScreen):
    """
    DB には記録できたが、解錠に失敗したときの画面

    利用者と管理者が状況を判断できるよう、
        ・何が記録されたか
        ・受付番号(貸出ID)
        ・次に選べる操作
    を表示します。
    """

    def __init__(self, parent, app, result, attempt_number=1):
        super().__init__(parent, app)
        self.result = result
        self.rental = result.rental
        self.attempt_number = attempt_number

        if result.purpose == PURPOSE_BORROW:
            self.set_title("貸出は記録されましたが、扉が開きませんでした")
            message = (
                "「もう一度解錠する」を押してください。\n"
                "それでも開かない場合は「貸出を取り消す」を押してください。"
            )
        else:
            self.set_title("返却は記録されましたが、扉が開きませんでした")
            message = (
                "「もう一度解錠する」を押してください。\n"
                "それでも開かない場合は、カメラを手元で保管し、管理者に連絡してください。\n"
                "(このカメラは、他の人に貸し出されないよう「点検中」にしました)"
            )

        warning_panel = MessagePanel(self.content_area, kind="warning", title="扉のロックを解錠できません",
                                     message=message)
        warning_panel.pack(fill="x")

        info_table = InfoTable(
            self.content_area,
            [
                ("受付番号", f"{self.rental.id}"),
                ("カメラ", self.rental.camera_name),
                ("解錠の試行", f"{attempt_number} 回目"),
            ],
        )
        info_table.pack(anchor="w", pady=(16, 0))

        admin_note = label(
            self.content_area,
            "管理者に連絡する場合は、受付番号を伝えてください。",
            color=theme.TEXT_SUB,
        )
        admin_note.pack(anchor="w", pady=(8, 0))

        if result.purpose == PURPOSE_BORROW:
            cancel_button = secondary_button(self.bottom_area, "貸出を取り消す", self._cancel_borrow, width=240)
        else:
            cancel_button = secondary_button(self.bottom_area, "管理者に連絡する", self._contact_admin, width=240)
        cancel_button.pack(side="left")

        self.retry_button = primary_button(self.bottom_area, "もう一度解錠する", self._retry_unlock, width=260)
        self.retry_button.pack(side="right")

    def _retry_unlock(self):
        set_button_enabled(self.retry_button, False)
        self.update_idletasks()

        try:
            new_result = self.app.service.retry_unlock(self.rental, self.result.purpose)
        except Exception as error:
            self.app.show_error(error)
            return

        if new_result.unlocked:
            self.app.show_screen(UnlockedScreen, result=new_result)
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
            message=(
                f"受付番号 {self.rental.id} の貸出は取り消されました。\n"
                "扉が開かない状態が続く場合は、管理者に連絡してください。"
            ),
        )

    def _contact_admin(self):
        self.app.show_screen(
            MessageScreen,
            level="warning",
            title="管理者に連絡してください",
            message=(
                f"受付番号 {self.rental.id}:返却は記録済みです。\n"
                f"「{self.rental.camera_name}」は点検中に設定しました。\n"
                "カメラは手元で保管し、管理者の指示に従ってください。"
            ),
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
    """エラー・注意・お知らせを表示する汎用画面"""

    # レベル → (アイコンの文字, アイコンの色, 見出しの色)
    LEVEL_STYLES = {
        "error": ("!", theme.BRAND_RED, theme.ERROR_TEXT),
        "warning": ("!", "#E0A100", theme.WARNING_TEXT),
        "info": ("i", theme.INFO_TEXT, theme.INFO_TEXT),
        "success": ("✓", theme.SUCCESS_STRONG, theme.SUCCESS_TEXT),
    }

    # 画面上部に表示する、レベルの文字(色が分からなくても伝わるように)
    LEVEL_NAMES = {
        "error": "エラー",
        "warning": "注意",
        "info": "お知らせ",
        "success": "完了",
    }

    def __init__(self, parent, app, level, title, message, retry_action=None, retry_label="もう一度試す"):
        super().__init__(parent, app)

        icon_text, icon_color, title_color = self.LEVEL_STYLES[level]

        inner_frame = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        inner_frame.place(relx=0.5, rely=0.45, anchor="center")

        icon_label = circle_icon(inner_frame, icon_text, icon_color, diameter=96, font_size=52)
        icon_label.pack(pady=(0, 12))

        level_label = label(inner_frame, self.LEVEL_NAMES[level], size=theme.FONT_SIZE_SMALL,
                            bold=True, color=title_color, anchor="center")
        level_label.pack()

        title_label = label(inner_frame, title, size=theme.FONT_SIZE_TITLE, bold=True,
                            color=title_color, anchor="center", justify="center", wraplength=780)
        title_label.pack(pady=(4, 12))

        message_label = label(inner_frame, message, anchor="center", justify="center", wraplength=780)
        message_label.pack()

        home_button = secondary_button(self.bottom_area, "ホームに戻る", self.app.go_home)
        home_button.pack(side="left")

        if retry_action is not None:
            retry_button = primary_button(self.bottom_area, retry_label, retry_action, width=260)
            retry_button.pack(side="right")
