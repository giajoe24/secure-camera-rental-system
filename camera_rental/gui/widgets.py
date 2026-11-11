"""
画面で共通して使う部品

    ・BaseScreen        : すべての画面の親クラス(手順表示 / 中身 / 下部ボタン帯)
    ・StepBar           : 「① 社員証 → ② カメラ → …」の手順表示
    ・primary_button    : 主な操作のボタン(赤)
    ・secondary_button  : 戻る・やめる のボタン(白地に枠線)
    ・choice_button     : 一覧から選ぶボタン(カメラ・貸出時間)
    ・status_tag        : 「貸出可能」などの状態表示(色 + 文字)
    ・InfoTable         : 「項目名  値」の表
    ・Pager             : ページ送り

【画面の骨組み(どの画面でも同じ)】

    ┌──────────────────────────────────────┐
    │ ヘッダー(システム名・時計)               │ ← app.py
    ├──────────────────────────────────────┤
    │ ① 社員証 → ② カメラ → ③ 貸出時間 → …     │ ← 今どの手順か
    ├──────────────────────────────────────┤
    │ 見出し(1行)                             │
    │ 説明(1行)                               │
    │                                        │
    │ 中身(選択肢・確認内容など)               │
    │                                        │
    ├──────────────────────────────────────┤
    │ [戻る]                          [次へ] │ ← 位置は固定
    └──────────────────────────────────────┘

    「戻る」は必ず左下、「次へ(貸し出す等)」は必ず右下に置きます。
    画面ごとに位置が変わると、利用者が毎回ボタンを探すことになるためです。
"""

import tkinter

import customtkinter

from camera_rental.gui import theme


# --------------------------------------------------
# ボタン
# --------------------------------------------------

def primary_button(parent, text, command,
                   width=theme.FOOTER_BUTTON_WIDTH, height=theme.FOOTER_BUTTON_HEIGHT):
    """主な操作のボタン(赤)"""
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
        text_color_disabled=theme.DISABLED_TEXT,
        font=theme.font(theme.FONT_SIZE_BUTTON, bold=True),
    )


def secondary_button(parent, text, command,
                     width=theme.FOOTER_BUTTON_WIDTH, height=theme.FOOTER_BUTTON_HEIGHT):
    """補助ボタン(白地に枠線): 戻る・やめる など"""
    return customtkinter.CTkButton(
        parent,
        text=text,
        command=command,
        width=width,
        height=height,
        corner_radius=theme.CORNER_RADIUS,
        fg_color=theme.SECONDARY_BUTTON,
        hover_color=theme.SECONDARY_BUTTON_HOVER,
        border_color=theme.SECONDARY_BUTTON_BORDER,
        border_width=2,
        text_color=theme.TEXT_MAIN,
        text_color_disabled=theme.DISABLED_TEXT,
        font=theme.font(theme.FONT_SIZE_BUTTON),
    )


def choice_button(parent, text, command, height=theme.CHOICE_BUTTON_HEIGHT):
    """
    一覧から1つ選ぶボタン(カメラ・貸出時間)

    押すとすぐ次の画面へ進みます。
    (券売機と同じく「選ぶ → 次へ」の2回押しをなくすため)
    """
    return customtkinter.CTkButton(
        parent,
        text=text,
        command=command,
        height=height,
        anchor="w",
        corner_radius=theme.CORNER_RADIUS,
        fg_color=theme.WHITE,
        hover_color=theme.CHOICE_BUTTON_HOVER,
        border_color=theme.SECONDARY_BUTTON_BORDER,
        border_width=2,
        text_color=theme.TEXT_MAIN,
        font=theme.font(theme.FONT_SIZE_BUTTON, bold=True),
    )


def set_button_enabled(button, enabled):
    """赤いボタンの有効/無効を切り替える(無効時はグレーにする)"""
    if enabled:
        button.configure(state="normal", fg_color=theme.BRAND_RED)
    else:
        button.configure(state="disabled", fg_color=theme.DISABLED_BUTTON)


# --------------------------------------------------
# 文字
# --------------------------------------------------

def label(parent, text, size=theme.FONT_SIZE_BODY, bold=False, color=theme.TEXT_MAIN,
          wraplength=0, anchor="w", justify="left"):
    """文字ラベル(よく使う設定をまとめたもの)"""
    return customtkinter.CTkLabel(
        parent,
        text=text,
        font=theme.font(size, bold=bold),
        text_color=color,
        wraplength=wraplength,
        anchor=anchor,
        justify=justify,
    )


# --------------------------------------------------
# 区切り線
# --------------------------------------------------

def horizontal_line(parent, thickness=1, color=theme.BORDER):
    """
    横の区切り線

    CTkFrame で高さ1の線を作ると描画されないことがあるため、
    標準の tkinter.Frame を使っています(色を塗るだけの単純な四角形)。
    """
    return tkinter.Frame(parent, height=thickness, background=color, borderwidth=0, highlightthickness=0)


# --------------------------------------------------
# 状態表示
# --------------------------------------------------

# 種類ごとの (文字色, 背景色)
TAG_COLORS = {
    "success": (theme.SUCCESS_TEXT, theme.SUCCESS_BACKGROUND),
    "info": (theme.INFO_TEXT, theme.INFO_BACKGROUND),
    "warning": (theme.WARNING_TEXT, theme.WARNING_BACKGROUND),
    "error": (theme.ERROR_TEXT, theme.ERROR_BACKGROUND),
    "neutral": (theme.TEXT_SUB, theme.FOOTER_BACKGROUND),
}

# カメラの状態 → 表示の種類
CAMERA_STATUS_TAG_KIND = {
    "available": "success",
    "rented": "info",
    "maintenance": "warning",
}


def status_tag(parent, text, kind="neutral", width=110):
    """
    状態を表す小さな札

    色だけで状態を伝えないよう、必ず文字(「貸出可能」など)を表示します。
    幅をそろえておくと、一覧で縦に並んだときに読みやすくなります。
    """
    text_color, background_color = TAG_COLORS[kind]
    return customtkinter.CTkLabel(
        parent,
        text=text,
        width=width,
        height=34,
        corner_radius=4,
        fg_color=background_color,
        text_color=text_color,
        font=theme.font(theme.FONT_SIZE_SMALL, bold=True),
    )


class InfoTable(customtkinter.CTkFrame):
    """
    「項目名  値」を縦に並べる表(行の間に細い線を入れる)

    rows: [("利用者", "森 航太郎"), ("カメラ", "1号機"), ...]
    """

    def __init__(self, parent, rows, name_width=200):
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)

        for row_index, (item_name, item_value) in enumerate(rows):
            grid_row = row_index * 2

            name_label = label(self, item_name, color=theme.TEXT_SUB)
            name_label.configure(width=name_width)
            name_label.grid(row=grid_row, column=0, sticky="w", pady=12)

            value_label = label(self, item_value, size=theme.FONT_SIZE_TITLE - 4, bold=True)
            value_label.grid(row=grid_row, column=1, sticky="w", pady=12)

            separator = horizontal_line(self)
            separator.grid(row=grid_row + 1, column=0, columnspan=2, sticky="ew")


# --------------------------------------------------
# 手順表示
# --------------------------------------------------

CIRCLED_NUMBERS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"]


class StepBar(customtkinter.CTkFrame):
    """
    今どの手順にいるかを表示する帯

        ① 社員証  →  ② カメラ  →  ③ 貸出時間  →  ④ 確認  →  ⑤ 完了

    ・終わった手順: 黒
    ・今の手順   : 赤の太字 + 下線
    ・これから   : グレー
    """

    def __init__(self, parent, step_names, current_index):
        super().__init__(
            parent,
            height=theme.STEP_BAR_HEIGHT,
            fg_color=theme.PAGE_BACKGROUND,
            corner_radius=0,
        )
        self.pack_propagate(False)

        row_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        row_frame.pack(side="left", fill="y", padx=theme.PAGE_PADDING_X)

        for index, step_name in enumerate(step_names):
            if index > 0:
                arrow = label(row_frame, "→", size=theme.FONT_SIZE_STEP, color=theme.TEXT_SUB)
                arrow.pack(side="left", padx=10)

            if index < current_index:
                color = theme.TEXT_MAIN
                is_bold = False
            elif index == current_index:
                color = theme.BRAND_RED
                is_bold = True
            else:
                color = theme.TEXT_SUB
                is_bold = False

            # 標準の tkinter.Frame を使うのは、中身の文字の幅ぴったりに縮めるため
            # (CTkFrame は初期幅 200 があり、手順の間隔が広がりすぎる)
            step_frame = tkinter.Frame(row_frame, background=theme.PAGE_BACKGROUND)
            step_frame.pack(side="left", fill="y")

            step_label = label(
                step_frame,
                f"{CIRCLED_NUMBERS[index]} {step_name}",
                size=theme.FONT_SIZE_STEP,
                bold=is_bold,
                color=color,
            )
            step_label.pack(side="top", expand=True)

            # 今の手順だけ、文字の下に赤い線を引く
            underline_color = theme.BRAND_RED if index == current_index else theme.PAGE_BACKGROUND
            underline = horizontal_line(step_frame, thickness=4, color=underline_color)
            underline.pack(side="bottom", fill="x")

        bottom_line = horizontal_line(self)
        bottom_line.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw")


# --------------------------------------------------
# ページ送り
# --------------------------------------------------

class Pager(customtkinter.CTkFrame):
    """
    一覧をページに分けて表示する部品

    render_page(list_frame, items_on_page) という関数を渡すと、
    ページが切り替わるたびに list_frame の中身を作り直します。

    【スクロールではなくページ送りにした理由】
        タッチモニターでは、指でなぞってもスクロールになりにくいためです。
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
            self.navigation_frame, "前のページ", self.show_previous_page, width=150, height=48
        )
        self.previous_button.configure(font=theme.font(theme.FONT_SIZE_SMALL))
        self.previous_button.pack(side="left")

        self.page_label = label(self.navigation_frame, "", size=theme.FONT_SIZE_SMALL, color=theme.TEXT_SUB)
        self.page_label.pack(side="left", padx=16)

        self.next_button = secondary_button(
            self.navigation_frame, "次のページ", self.show_next_page, width=150, height=48
        )
        self.next_button.configure(font=theme.font(theme.FONT_SIZE_SMALL))
        self.next_button.pack(side="left")

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

        self.page_label.configure(text=f"{page_number + 1} / {self.page_count}")
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

    子クラスで使うもの:
        show_steps(手順名のリスト, 今の番号)  手順表示を出す
        set_title(見出し, 説明)              見出しと1行の説明
        content_area                        中身を置く場所
        add_back_button(文言, 処理)          左下のボタン
        add_next_button(文言, 処理)          右下のボタン

    子クラスで変更できる設定:
        idle_timeout_enabled : 無操作でホームに戻すか(読み取り中・扉が開いている間は False)
    """

    idle_timeout_enabled = True

    def __init__(self, parent, app):
        super().__init__(parent, fg_color=theme.PAGE_BACKGROUND, corner_radius=0)
        self.app = app

        # after() で予約した処理のID(画面を離れるときにまとめて取り消す)
        self._scheduled_job_ids = set()

        # 上から: 手順表示 → 見出し → 中身 → 下部ボタン帯
        # height=1 : 中身が空のとき、CTkFrame の初期サイズ(200)で場所を取らないようにする
        self.step_area = customtkinter.CTkFrame(self, fg_color="transparent", height=1, corner_radius=0)
        self.step_area.pack(fill="x")

        self.footer = customtkinter.CTkFrame(
            self,
            height=theme.FOOTER_HEIGHT,
            fg_color=theme.FOOTER_BACKGROUND,
            corner_radius=0,
        )
        self.footer.pack(side="bottom", fill="x")
        # ボタンの有無で帯の高さが変わらないようにする
        self.footer.pack_propagate(False)

        footer_line = horizontal_line(self)
        footer_line.pack(side="bottom", fill="x")

        self.title_area = customtkinter.CTkFrame(self, fg_color="transparent", height=1)
        self.title_area.pack(fill="x", padx=theme.PAGE_PADDING_X, pady=(theme.PAGE_PADDING_Y, 0))

        self.content_area = customtkinter.CTkFrame(self, fg_color="transparent")
        self.content_area.pack(fill="both", expand=True, padx=theme.PAGE_PADDING_X, pady=theme.PAGE_PADDING_Y)

    # ---------- 上部 ----------

    def show_steps(self, step_names, current_index):
        step_bar = StepBar(self.step_area, step_names, current_index)
        step_bar.pack(fill="x")

    def set_title(self, title, note=None, title_color=theme.TEXT_MAIN):
        """見出し(1行)と説明(1行)"""
        title_label = label(self.title_area, title, size=theme.FONT_SIZE_TITLE, bold=True, color=title_color)
        title_label.pack(anchor="w")

        if note:
            note_label = label(self.title_area, note, color=theme.TEXT_SUB)
            note_label.pack(anchor="w", pady=(6, 0))

    # ---------- 下部のボタン帯 ----------

    def add_back_button(self, text, command):
        """左下のボタン(戻る・やめる など)"""
        button = secondary_button(self.footer, text, command)
        button.pack(side="left", padx=(theme.PAGE_PADDING_X, 0))
        return button

    def add_next_button(self, text, command):
        """右下のボタン(貸し出す・返却する など)"""
        button = primary_button(self.footer, text, command)
        button.pack(side="right", padx=(0, theme.PAGE_PADDING_X))
        return button

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
