"""
アプリのメインウィンドウ

    ・赤いヘッダー(システム名・デモ表示・時計)
    ・画面の切り替え(show_screen)
    ・無操作タイムアウト(一定時間触られなければホームへ戻す)
    ・エラーの表示(show_error)

画面そのもの(ホーム、社員証読み取りなど)は screens_flow.py / screens_info.py にあります。
"""

import logging
import time
from datetime import datetime

import customtkinter

from camera_rental import errors
from camera_rental.gui import theme
from camera_rental.gui.widgets import label

logger = logging.getLogger(__name__)


class CameraRentalApp(customtkinter.CTk):
    """セキュアカメラ貸出管理システムのメインウィンドウ"""

    def __init__(self, service, card_reader, settings, demo_mode):
        super().__init__()

        self.service = service
        self.card_reader = card_reader
        self.settings = settings
        self.demo_mode = demo_mode

        self.current_screen = None
        self.last_interaction_time = time.monotonic()

        self._setup_window()
        theme.choose_font_family(self)
        self._build_header()
        self._build_body()
        self._watch_user_interaction()

        # 画面モジュールは、ここで読み込む(循環 import を避けるため)
        from camera_rental.gui.screens_flow import HomeScreen
        self.home_screen_class = HomeScreen

        self.go_home()
        self._update_clock()
        self._check_idle_timeout()

    # ==================================================
    # ウィンドウの準備
    # ==================================================

    def _setup_window(self):
        customtkinter.set_appearance_mode("light")

        self.title(self.settings.SYSTEM_NAME)
        self.geometry(f"{self.settings.WINDOW_WIDTH}x{self.settings.WINDOW_HEIGHT}")
        self.minsize(self.settings.WINDOW_MIN_WIDTH, self.settings.WINDOW_MIN_HEIGHT)
        self.configure(fg_color=theme.APP_BACKGROUND)

        if self.settings.FULLSCREEN:
            self.attributes("-fullscreen", True)

        # Esc キーで全画面を解除できるようにする(保守作業用)
        self.bind("<Escape>", self._exit_fullscreen)

    def _exit_fullscreen(self, event=None):
        self.attributes("-fullscreen", False)

    def _build_header(self):
        """上部の赤いヘッダー"""
        header = customtkinter.CTkFrame(
            self,
            height=theme.HEADER_HEIGHT,
            corner_radius=0,
            fg_color=theme.BRAND_RED,
        )
        header.pack(fill="x")
        # 中身の大きさでヘッダーの高さが変わらないようにする
        header.pack_propagate(False)

        self._add_logo_if_configured(header)

        system_name_label = label(
            header,
            self.settings.SYSTEM_NAME,
            size=theme.FONT_SIZE_HEADER,
            bold=True,
            color=theme.WHITE,
        )
        system_name_label.pack(side="left", padx=(theme.PAGE_PADDING, 0))

        self.clock_label = label(header, "", size=theme.FONT_SIZE_BODY, color=theme.WHITE)
        self.clock_label.pack(side="right", padx=theme.PAGE_PADDING)

        if self.demo_mode:
            demo_badge = customtkinter.CTkLabel(
                header,
                text="  デモモード(実機は動きません)  ",
                font=theme.font(theme.FONT_SIZE_SMALL, bold=True),
                fg_color=theme.DEMO_BADGE_BACKGROUND,
                text_color=theme.DEMO_BADGE_TEXT,
                corner_radius=10,
                height=34,
            )
            demo_badge.pack(side="right", padx=(0, 8))

    def _add_logo_if_configured(self, header):
        """
        設定でロゴ画像が指定されていれば表示する

        ※ ロゴは生成せず、正式に提供された画像ファイルだけを使います。
          指定がない・読み込めない場合は、システム名のテキストだけを表示します。
        """
        logo_path = self.settings.LOGO_IMAGE_PATH
        if not logo_path:
            return

        try:
            from PIL import Image

            logo_image = Image.open(logo_path)
            # ヘッダーの高さに合わせて縮小する(縦横比は保つ)
            target_height = 40
            target_width = int(logo_image.width * target_height / logo_image.height)
            self.logo_image = customtkinter.CTkImage(
                light_image=logo_image,
                size=(target_width, target_height),
            )
        except Exception:
            logger.exception("ロゴ画像を読み込めませんでした: %s", logo_path)
            return

        logo_label = customtkinter.CTkLabel(header, text="", image=self.logo_image)
        logo_label.pack(side="left", padx=(theme.PAGE_PADDING, 0))

    def _build_body(self):
        """ヘッダーの下の、画面を表示する場所"""
        self.body = customtkinter.CTkFrame(self, fg_color=theme.APP_BACKGROUND, corner_radius=0)
        self.body.pack(fill="both", expand=True)

    def _update_clock(self):
        """ヘッダーの時計を更新する(1秒ごと)"""
        now_text = datetime.now().strftime("%Y/%m/%d %H:%M")
        self.clock_label.configure(text=now_text)
        self.after(1000, self._update_clock)

    # ==================================================
    # 画面の切り替え
    # ==================================================

    def show_screen(self, screen_class, **screen_arguments):
        """
        画面を切り替える

        前の画面は後片付け(on_leave)をしてから破棄し、新しい画面を作ります。
        画面を使い回さず毎回作り直すことで、前の利用者の情報が残らないようにしています。
        """
        if self.current_screen is not None:
            self.current_screen.on_leave()
            self.current_screen.destroy()

        self.current_screen = screen_class(self.body, app=self, **screen_arguments)
        self.current_screen.pack(fill="both", expand=True, padx=theme.PAGE_PADDING, pady=theme.PAGE_PADDING)

        self.last_interaction_time = time.monotonic()

    def go_home(self):
        self.show_screen(self.home_screen_class)

    # ==================================================
    # エラー表示
    # ==================================================

    def show_error(self, error, retry_action=None):
        """
        例外を、利用者向けのエラー画面で表示する

        ・CameraRentalError: 用意した日本語メッセージを表示
        ・それ以外        : 想定外のエラー。詳細はログに記録し、画面には一般的な案内だけ表示
        """
        from camera_rental.gui.screens_flow import MessageScreen

        if isinstance(error, errors.CameraRentalError):
            logger.warning("処理を中止しました: %s (%s)", error.title, error.detail)
            title = error.title
            message = error.user_message
            level = "warning" if self._is_warning(error) else "error"
        else:
            logger.error("想定外のエラーが発生しました", exc_info=error)
            title = "予期しないエラーが発生しました"
            message = (
                "処理を中止しました。ロックは解錠していません。\n"
                "もう一度お試しください。繰り返す場合は管理者に連絡してください。"
            )
            level = "error"

        self.show_screen(
            MessageScreen,
            level=level,
            title=title,
            message=message,
            retry_action=retry_action,
        )

    @staticmethod
    def _is_warning(error):
        """利用者の操作で解決できる状況は「警告(黄)」で表示する"""
        warning_types = (
            errors.NoAvailableCameraError,
            errors.CameraNotAvailableError,
            errors.UserHasActiveRentalError,
            errors.NoActiveRentalError,
            errors.CardReadError,
        )
        return isinstance(error, warning_types)

    def report_callback_exception(self, exception_type, exception_value, traceback_object):
        """
        ボタンの処理などで、どこにも捕まえられなかった例外が出たときの最終手段

        tkinter の標準ではコンソールに出すだけなので、
        ログに記録したうえで、利用者にはエラー画面を表示します。
        """
        logger.error(
            "画面処理中に例外が発生しました",
            exc_info=(exception_type, exception_value, traceback_object),
        )
        try:
            self.show_error(exception_value)
        except Exception:
            logger.exception("エラー画面の表示にも失敗しました")

    # ==================================================
    # 無操作タイムアウト
    # ==================================================

    def _watch_user_interaction(self):
        """画面のどこかが触られたら、最終操作時刻を更新する"""
        self.bind_all("<ButtonPress>", self._record_interaction, add="+")
        self.bind_all("<KeyPress>", self._record_interaction, add="+")

    def _record_interaction(self, event=None):
        self.last_interaction_time = time.monotonic()

    def _check_idle_timeout(self):
        """1秒ごとに、無操作の時間が設定を超えていないか確認する"""
        screen = self.current_screen
        idle_seconds = time.monotonic() - self.last_interaction_time

        is_home = isinstance(screen, self.home_screen_class)
        timeout_reached = idle_seconds >= self.settings.IDLE_TIMEOUT_SECONDS

        if screen is not None and screen.idle_timeout_enabled and not is_home and timeout_reached:
            logger.info("無操作が続いたため、画面を戻します: %s", type(screen).__name__)
            self.last_interaction_time = time.monotonic()
            screen.on_idle_timeout()

        self.after(1000, self._check_idle_timeout)

    # ==================================================
    # 終了
    # ==================================================

    def close(self):
        """ウィンドウを閉じる(読み取り中のスレッドにも停止を伝える)"""
        if self.current_screen is not None:
            self.current_screen.on_leave()
        self.destroy()
