"""
画面で共通して使う部品

    ・BaseScreen     : すべての画面の親クラス(白いカード + 上/中/下の3段構成)
    ・primary_button : 主要ボタン(DENSOレッド)
    ・secondary_button : 補助ボタン(薄いグレー)
    ・StatusBadge    : 「貸出可能」などの状態表示(色 + 文字)
    ・MessagePanel   : 成功・警告・エラーの色付きお知らせ枠
    ・InfoTable      : 「項目名: 値」の一覧
    ・Pager          : ページ送り(タッチ操作でスクロールしにくいため)

【設計メモ: スクロールではなくページ送りにした理由】
    Raspberry Pi のタッチモニターでは、指でなぞってもマウスホイールの
    スクロールにはならず、CTkScrollableFrame のスクロールが使いにくいです。
    大きな「前へ / 次へ」ボタンの方が確実に操作できるため、一覧はページ送りにしました。
"""

import customtkinter

from camera_rental.gui import theme


# --------------------------------------------------
# ボタン
# --------------------------------------------------

def primary_button(parent, text, command, width=theme.BUTTON_WIDTH, height=theme.BUTTON_HEIGHT):
    """主要ボタン(赤)"""
    return customtkinter.CTkButton(
        parent,
        text=text,
        command=command,
        width=width,
        height=height,
        corner_radius=theme.CORNER_RADIUS,
        fg_color=theme.BRAND_RED,
        hover_color=theme.BRAND_RED_HOVER,
        text_color=theme.WHITE,
        text_color_disabled=theme.WHITE,
        font=theme.font(theme.FONT_SIZE_BUTTON, bold=True),
    )


def secondary_button(parent, text, command, width=theme.BUTTON_WIDTH, height=theme.BUTTON_HEIGHT):
    """補助ボタン(グレー): 戻る・やめる など"""
    return customtkinter.CTkButton(
        parent,
        text=text,
        command=command,
        width=width,
        height=height,
        corner_radius=theme.CORNER_RADIUS,
        fg_color=theme.SECONDARY_BUTTON,
        hover_color=theme.SECONDARY_BUTTON_HOVER,
        text_color=theme.TEXT_MAIN,
        font=theme.font(theme.FONT_SIZE_BUTTON),
    )


def set_button_enabled(button, enabled):
    """ボタンの有効/無効を切り替える(無効時は色も薄くする)"""
    if enabled:
        button.configure(state="normal", fg_color=theme.BRAND_RED)
    else:
        button.configure(state="disabled", fg_color=theme.DISABLED_BUTTON)


# --------------------------------------------------
# 文字
# --------------------------------------------------

def label(parent, text, size=theme.FONT_SIZE_BODY, bold=False, color=theme.TEXT_MAIN,
          wraplength=0, justify="left", anchor="w"):
    """文字ラベル(よく使う設定をまとめたもの)"""
    return customtkinter.CTkLabel(
        parent,
        text=text,
        font=theme.font(size, bold=bold),
        text_color=color,
        wraplength=wraplength,
        justify=justify,
        anchor=anchor,
    )


# --------------------------------------------------
# 状態表示
# --------------------------------------------------

# 種類ごとの (文字色, 背景色)
BADGE_COLORS = {
    "success": (theme.SUCCESS_TEXT, theme.SUCCESS_BACKGROUND),
    "info": (theme.INFO_TEXT, theme.INFO_BACKGROUND),
    "warning": (theme.WARNING_TEXT, theme.WARNING_BACKGROUND),
    "error": (theme.ERROR_TEXT, theme.ERROR_BACKGROUND),
    "neutral": (theme.TEXT_SUB, theme.APP_BACKGROUND),
}

# カメラの状態 → バッジの種類
CAMERA_STATUS_BADGE_KIND = {
    "available": "success",
    "rented": "info",
    "maintenance": "warning",
}


class StatusBadge(customtkinter.CTkLabel):
    """
    状態を表す小さなラベル

    色だけで状態を伝えないよう、必ず文字(「貸出可能」など)を表示します。
    """

    def __init__(self, parent, text, kind="neutral"):
        text_color, background_color = BADGE_COLORS[kind]
        super().__init__(
            parent,
            text=f"  {text}  ",
            font=theme.font(theme.FONT_SIZE_SMALL, bold=True),
            text_color=text_color,
            fg_color=background_color,
            corner_radius=10,
            height=32,
        )


class MessagePanel(customtkinter.CTkFrame):
    """
    色付きのお知らせ枠

    kind: "success" / "warning" / "error" / "info"
    先頭に「完了」「注意」「エラー」などの文字を付けて、色が分からなくても伝わるようにしています。
    """

    KIND_PREFIX = {
        "success": "完了",
        "warning": "注意",
        "error": "エラー",
        "info": "お知らせ",
    }

    def __init__(self, parent, kind, title, message=""):
        text_color, background_color = BADGE_COLORS[kind]
        super().__init__(parent, fg_color=background_color, corner_radius=theme.CORNER_RADIUS)

        prefix = self.KIND_PREFIX[kind]
        title_label = label(
            self,
            f"【{prefix}】{title}",
            size=theme.FONT_SIZE_HEADING,
            bold=True,
            color=text_color,
            wraplength=760,
        )
        title_label.pack(anchor="w", padx=20, pady=(16, 4 if message else 16))

        if message:
            message_label = label(self, message, color=theme.TEXT_MAIN, wraplength=760)
            message_label.pack(anchor="w", padx=20, pady=(0, 16))


class InfoTable(customtkinter.CTkFrame):
    """
    「項目名  値」を縦に並べる表

    rows: [("利用者", "森 航太郎"), ("カメラ", "1号機"), ...]
    """

    def __init__(self, parent, rows, label_width=180):
        super().__init__(parent, fg_color="transparent")

        for row_index, (item_name, item_value) in enumerate(rows):
            name_label = label(self, item_name, color=theme.TEXT_SUB, size=theme.FONT_SIZE_BODY)
            name_label.configure(width=label_width)
            name_label.grid(row=row_index, column=0, sticky="w", pady=6)

            value_label = label(self, item_value, bold=True, size=theme.FONT_SIZE_HEADING)
            value_label.grid(row=row_index, column=1, sticky="w", padx=(12, 0), pady=6)


def circle_icon(parent, text, color, diameter=100, font_size=52):
    """
    丸いアイコン(完了の「✓」、注意の「!」など)

    CTkLabel だけで丸を作ると文字の幅で楕円になることがあるため、
    丸い枠(CTkFrame)の中央に文字を置いています。
    """
    circle = customtkinter.CTkFrame(
        parent,
        width=diameter,
        height=diameter,
        corner_radius=diameter // 2,
        fg_color=color,
    )
    # 中の文字の大きさで、丸の大きさが変わらないようにする
    circle.pack_propagate(False)

    icon_text = customtkinter.CTkLabel(
        circle,
        text=text,
        text_color=theme.WHITE,
        fg_color="transparent",
        font=theme.font(font_size, bold=True),
    )
    icon_text.place(relx=0.5, rely=0.5, anchor="center")
    return circle


# --------------------------------------------------
# ページ送り
# --------------------------------------------------

class Pager(customtkinter.CTkFrame):
    """
    一覧をページに分けて表示する部品

    render_page(list_frame, items_on_page) という関数を渡すと、
    ページが切り替わるたびに list_frame の中身を作り直します。
    """

    def __init__(self, parent, items, page_size, render_page):
        super().__init__(parent, fg_color="transparent")

        self.items = list(items)
        self.page_size = page_size
        self.render_page = render_page
        self.current_page = 0

        self.list_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self.list_frame.pack(fill="both", expand=True)

        self.navigation_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self.navigation_frame.pack(fill="x", pady=(8, 0))

        self.previous_button = secondary_button(
            self.navigation_frame, "◀ 前へ", self.show_previous_page, width=140, height=52
        )
        self.previous_button.pack(side="left")

        self.page_label = label(self.navigation_frame, "", color=theme.TEXT_SUB, anchor="center")
        self.page_label.pack(side="left", expand=True)

        self.next_button = secondary_button(
            self.navigation_frame, "次へ ▶", self.show_next_page, width=140, height=52
        )
        self.next_button.pack(side="right")

        self.show_page(0)

    @property
    def page_count(self):
        if not self.items:
            return 1
        return (len(self.items) + self.page_size - 1) // self.page_size

    def show_page(self, page_number):
        self.current_page = page_number

        for child in self.list_frame.winfo_children():
            child.destroy()

        start_index = page_number * self.page_size
        end_index = start_index + self.page_size
        self.render_page(self.list_frame, self.items[start_index:end_index])

        # 1ページしかないときは、ページ送りボタンを隠す
        if self.page_count <= 1:
            self.navigation_frame.pack_forget()
            return

        self.page_label.configure(text=f"{page_number + 1} / {self.page_count} ページ")
        self.previous_button.configure(state="normal" if page_number > 0 else "disabled")
        is_last_page = page_number >= self.page_count - 1
        self.next_button.configure(state="disabled" if is_last_page else "normal")

    def show_previous_page(self):
        if self.current_page > 0:
            self.show_page(self.current_page - 1)

    def show_next_page(self):
        if self.current_page < self.page_count - 1:
            self.show_page(self.current_page + 1)


# --------------------------------------------------
# 画面の親クラス
# --------------------------------------------------

class BaseScreen(customtkinter.CTkFrame):
    """
    すべての画面の親クラス

    白いカードの中を、次の3段に分けています。
        top_area     : 手順(例「貸出 1/4」)と見出し
        content_area : 画面ごとの中身
        bottom_area  : 「戻る」「次へ」などのボタン

    子クラスで変更できる設定:
        idle_timeout_enabled : 無操作でホームに戻すか(読み取り中・解錠中は False)
    """

    idle_timeout_enabled = True

    def __init__(self, parent, app):
        super().__init__(
            parent,
            fg_color=theme.CARD_BACKGROUND,
            corner_radius=theme.CARD_CORNER_RADIUS,
            border_width=1,
            border_color=theme.BORDER,
        )
        self.app = app

        # after() で予約した処理のID(画面を離れるときにまとめて取り消す)
        self._scheduled_job_ids = set()

        # height=1 : 中身が空のとき、CTkFrame の初期サイズ(200)で場所を取らないようにする
        self.top_area = customtkinter.CTkFrame(self, fg_color="transparent", height=1)
        self.top_area.pack(fill="x", padx=theme.CARD_PADDING, pady=(theme.CARD_PADDING, 8))

        self.bottom_area = customtkinter.CTkFrame(self, fg_color="transparent", height=1)
        self.bottom_area.pack(side="bottom", fill="x", padx=theme.CARD_PADDING, pady=(8, theme.CARD_PADDING))

        self.content_area = customtkinter.CTkFrame(self, fg_color="transparent")
        self.content_area.pack(fill="both", expand=True, padx=theme.CARD_PADDING, pady=8)

    # ---------- 見出し ----------

    def set_title(self, title, step_text=None, subtitle=None):
        """画面上部に手順・見出し・補足を表示する"""
        if step_text:
            step_label = label(self.top_area, step_text, size=theme.FONT_SIZE_SMALL,
                               bold=True, color=theme.BRAND_RED)
            step_label.pack(anchor="w")

        title_label = label(self.top_area, title, size=theme.FONT_SIZE_TITLE, bold=True)
        title_label.pack(anchor="w", pady=(2, 0))

        if subtitle:
            subtitle_label = label(self.top_area, subtitle, color=theme.TEXT_SUB, wraplength=820)
            subtitle_label.pack(anchor="w", pady=(4, 0))

    # ---------- 時間差の処理 ----------

    def schedule(self, delay_milliseconds, callback):
        """
        delay_milliseconds 後に callback を実行する

        画面を離れたときに自動で取り消されるので、
        「消えた画面の部品を更新しようとしてエラー」になりません。
        """
        job_id = None

        def run_callback():
            self._scheduled_job_ids.discard(job_id)
            callback()

        job_id = self.after(delay_milliseconds, run_callback)
        self._scheduled_job_ids.add(job_id)
        return job_id

    # ---------- 画面の切り替え時に呼ばれる ----------

    def on_leave(self):
        """この画面から別の画面へ移る直前に呼ばれる(後片付け)"""
        for job_id in list(self._scheduled_job_ids):
            self.after_cancel(job_id)
        self._scheduled_job_ids.clear()

    def on_idle_timeout(self):
        """無操作が続いたときに呼ばれる(標準ではホームへ戻る)"""
        self.app.go_home()
