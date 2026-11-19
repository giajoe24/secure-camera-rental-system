# 画面で使う部品(色、フォント、ボタンなど)と、全画面の土台 Screen
#
# 7インチ(800×480)のタッチモニターに合わせている。
# 全画面にならずに上にタブやタイトルバーが出ても切れないよう、縦 416px でも収まるようにしている。
#   ・ボタンは高さ 56px 以上(約 10mm。指で押しやすい大きさ)、ボタンどうしは 12px 以上あける
#   ・文字は 16px 以上。背景との明るさの差(コントラスト比)は 4.5 以上
#   ・押すボタンは青。赤はエラー、黄は警告、緑は完了だけに使う(安全色の意味とそろえる)
#   ・状態は色だけでなく、必ず文字でも出す
#   ・点滅やアニメーションは使わない

import tkinter
import tkinter.font

import customtkinter

# ---- 色 ----
BRAND_RED = "#DC0032"       # 上の線だけに使う
BLUE = "#1E4FA3"            # 押すボタン(白文字とのコントラスト比 7.6)
TEXT_COLOR = "#1F2328"
SUB_TEXT_COLOR = "#59616B"  # 白地とのコントラスト比 6.3
LINE_COLOR = "#D8DCE1"
WHITE = "#FFFFFF"
FOOTER_COLOR = "#F2F4F6"
DISABLED_COLOR = "#E4E7EB"
DISABLED_TEXT_COLOR = "#59616B"
BORDER_COLOR = "#B7BDC5"
ERROR_TEXT_COLOR = "#A8001F"
SELECTED_COLOR = "#E8EEF9"  # 選んだボタンの背景

# 札の色 (文字, 背景)
GREEN_TAG = ("#0F6B3E", "#E3F3EA")
BLUE_TAG = ("#1E4FA3", "#E8EEF9")
YELLOW_TAG = ("#7A4D00", "#FFF1CC")
RED_TAG = ("#A8001F", "#FCE8EC")

CIRCLED_NUMBERS = ["①", "②", "③", "④", "⑤"]

# ---- 大きさ ----
SCREEN_PADDING = 24
FOOTER_HEIGHT = 72
BUTTON_HEIGHT = 56
TEXT_WIDTH = 750   # 長い文はこの幅で折り返す


# ---- 日時の表示 ----

def format_date_time(date_time):
    # 例: 11月17日 15:30
    return f"{date_time.month}月{date_time.day}日 {date_time:%H:%M}"


def format_minutes(minutes):
    # 例: 15 → 15分、120 → 2時間、90 → 1時間30分
    hours = minutes // 60
    rest = minutes % 60
    if hours == 0:
        return f"{rest}分"
    if rest == 0:
        return f"{hours}時間"
    return f"{hours}時間{rest}分"


# ---- フォント ----

# 上から順に探して、あったものを使う
JAPANESE_FONT_NAMES = ["Yu Gothic UI", "Meiryo UI", "Noto Sans CJK JP", "Noto Sans JP"]
japanese_font = ""   # まだ探していないときは ""


def find_japanese_font():
    global japanese_font
    if japanese_font == "":
        japanese_font = None  # 見つからなければ標準のフォント
        installed = tkinter.font.families()
        for name in JAPANESE_FONT_NAMES:
            if name in installed:
                japanese_font = name
                break
    return japanese_font


def make_font(size, bold=False):
    if bold:
        weight = "bold"
    else:
        weight = "normal"
    return customtkinter.CTkFont(family=find_japanese_font(), size=size, weight=weight)


# ---- 部品 ----

def make_label(parent, text, size=17, bold=False, color=TEXT_COLOR):
    return customtkinter.CTkLabel(parent, text=text, font=make_font(size, bold), text_color=color,
                                  anchor="w", justify="left", wraplength=TEXT_WIDTH)


def make_tag(parent, text, colors):
    # 「貸出可能」などの札
    text_color, background = colors
    return customtkinter.CTkLabel(parent, text=text, height=32, corner_radius=4, fg_color=background,
                                  text_color=text_color, font=make_font(16, True))


# タッチモニターでは、触ったボタンにホバーの色が残ってしまうので hover=False にしている

def make_main_button(parent, text, command, width=200, height=BUTTON_HEIGHT):
    # その画面で一番押してほしいボタン(青)
    return customtkinter.CTkButton(
        parent, text=text, command=command, width=width, height=height, corner_radius=8, hover=False,
        fg_color=BLUE, text_color=WHITE, text_color_disabled=DISABLED_TEXT_COLOR, font=make_font(20, True),
    )


def make_sub_button(parent, text, command, width=160, height=BUTTON_HEIGHT):
    # 「戻る」など(白地に枠)
    return customtkinter.CTkButton(
        parent, text=text, command=command, width=width, height=height, corner_radius=8, hover=False,
        fg_color=WHITE, border_width=2, border_color=BORDER_COLOR, text_color=TEXT_COLOR,
        text_color_disabled=DISABLED_TEXT_COLOR, font=make_font(19),
    )


def disable_button(button):
    button.configure(state="disabled", fg_color=DISABLED_COLOR)


def enable_main_button(button):
    button.configure(state="normal", fg_color=BLUE)


def show_as_selected(button, selected):
    # 選んだボタンは薄い青 + 太い青枠 + 太字にする(色だけに頼らない)
    if selected:
        button.configure(fg_color=SELECTED_COLOR, border_color=BLUE, border_width=4, text_color=BLUE,
                         font=make_font(21, True))
    else:
        button.configure(fg_color=WHITE, border_color=BORDER_COLOR, border_width=2, text_color=TEXT_COLOR,
                         font=make_font(21))


def make_line(parent, thickness=1, color=LINE_COLOR):
    # 区切り線(CTkFrame だと 1px の線が出ないので tkinter.Frame)
    return tkinter.Frame(parent, height=thickness, bg=color, bd=0, highlightthickness=0)


# ---- 画面の土台 ----
# 上から step_area(手順)、top_area(見出し)、content_area(中身)、footer(下のボタン)
# 「戻る」は左下、「次へ進む」ボタンは右下に、どの画面でも同じ場所に置く

class Screen(customtkinter.CTkFrame):
    idle_timeout = True   # 放っておいたらホームに戻すか

    def __init__(self, app):
        super().__init__(app.body, fg_color=WHITE, corner_radius=0)
        self.app = app
        self.jobs = []   # after() で予約した処理

        self.step_area = tkinter.Frame(self, bg=WHITE)
        self.step_area.pack(fill="x")

        self.footer = customtkinter.CTkFrame(self, height=FOOTER_HEIGHT, fg_color=FOOTER_COLOR, corner_radius=0)
        self.footer.pack(side="bottom", fill="x")
        self.footer.pack_propagate(False)  # ボタンで高さが変わらないように

        self.footer_line = make_line(self)
        self.footer_line.pack(side="bottom", fill="x")

        self.top_area = tkinter.Frame(self, bg=WHITE)
        self.top_area.pack(fill="x", padx=SCREEN_PADDING, pady=(10, 0))

        self.content_area = customtkinter.CTkFrame(self, fg_color="transparent")
        self.content_area.pack(fill="both", expand=True, padx=SCREEN_PADDING, pady=10)

    def show_steps(self, names, current):
        # ① 社員証 → ② 貸出時間 → … を出して、今の手順を青の太字 + 下線にする
        bar = tkinter.Frame(self.step_area, bg=WHITE, height=36)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        row = tkinter.Frame(bar, bg=WHITE)
        row.pack(side="left", fill="y", padx=SCREEN_PADDING)

        for i, name in enumerate(names):
            if i > 0:
                make_label(row, "→", 16, color=SUB_TEXT_COLOR).pack(side="left", padx=8)

            if i == current:
                color = BLUE
            else:
                color = SUB_TEXT_COLOR

            cell = tkinter.Frame(row, bg=WHITE)
            cell.pack(side="left", fill="y")
            make_label(cell, f"{CIRCLED_NUMBERS[i]} {name}", 16, i == current, color).pack(expand=True)

            if i == current:
                make_line(cell, 3, BLUE).pack(side="bottom", fill="x")
            else:
                make_line(cell, 3, WHITE).pack(side="bottom", fill="x")

        make_line(self.step_area).pack(fill="x")

    def show_title(self, title, note=None, color=TEXT_COLOR):
        make_label(self.top_area, title, 24, True, color).pack(anchor="w")
        if note:
            make_label(self.top_area, note, color=SUB_TEXT_COLOR).pack(anchor="w", pady=(4, 0))

    def show_footer(self):
        # 帯を隠している画面で、あとから出すとき用
        if self.footer.winfo_manager() == "":
            self.footer.pack(side="bottom", fill="x", before=self.footer_line)

    def add_left_button(self, text, command):
        button = make_sub_button(self.footer, text, command)
        button.pack(side="left", padx=SCREEN_PADDING)
        return button

    def add_right_button(self, text, command):
        button = make_main_button(self.footer, text, command)
        button.pack(side="right", padx=SCREEN_PADDING)
        return button

    def add_footer_label(self):
        # 下の帯の、左右のボタンの間に置く文字(返却予定など、必ず見せたいもの)
        label = make_label(self.footer, "", 20, True)
        label.pack(side="left", expand=True)
        return label

    def run_later(self, ms, function):
        # after() と同じ。画面を離れるときにまとめて取り消せるよう覚えておく
        self.jobs.append(self.after(ms, function))

    def leave(self):
        # 画面を離れる直前に呼ばれる
        for job in self.jobs:
            self.after_cancel(job)
