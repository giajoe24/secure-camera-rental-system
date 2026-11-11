"""
画面の色・文字・大きさの設定

デザインを変えたいときは、まずこのファイルの値を変更してください。
画面ごとのファイルに色コードを直接書かないようにしているので、
ここを変えればアプリ全体の見た目がそろって変わります。

【デザインの方針】
    駅の券売機や受付端末のように「迷わない」ことを優先しています。
    ・装飾(影・グラデーション・アイコン・入れ子のカード)は使わない
    ・角丸は小さめ(6px)。丸すぎると業務端末らしさがなくなるため
    ・色は意味のあるところだけに使う(赤=主な操作、緑/青/黄=状態)
    ・文字は左寄せ。視線が左上から右下へ素直に流れるようにする
"""

import sys
import tkinter.font

import customtkinter


# --------------------------------------------------
# 色
# --------------------------------------------------

# ブランドカラー(DENSOレッド)
BRAND_RED = "#DC0032"
BRAND_RED_HOVER = "#B8002A"

# 全体
PAGE_BACKGROUND = "#FFFFFF"      # 画面の地(白一色にして、カードの入れ子をなくす)
FOOTER_BACKGROUND = "#F3F4F6"    # 下部のボタン帯
TEXT_MAIN = "#202124"
TEXT_SUB = "#6B7280"
BORDER = "#E5E7EB"
WHITE = "#FFFFFF"

# 補助ボタン(戻る・やめる など)
SECONDARY_BUTTON = "#FFFFFF"
SECONDARY_BUTTON_HOVER = "#E5E7EB"
SECONDARY_BUTTON_BORDER = "#C9CDD3"
DISABLED_BUTTON = "#E5E7EB"
DISABLED_TEXT = "#9CA3AF"

# 選択肢のボタン(カメラ・貸出時間)
CHOICE_BUTTON_HOVER = "#F9FAFB"

# 状態の色(文字色, 背景色)
SUCCESS_TEXT = "#137A4B"
SUCCESS_BACKGROUND = "#EAF8F0"
INFO_TEXT = "#1D4ED8"            # 「貸出中」は異常ではないので青
INFO_BACKGROUND = "#EAF1FF"
WARNING_TEXT = "#8A5A00"
WARNING_BACKGROUND = "#FFF6DB"
ERROR_TEXT = "#B3002A"
ERROR_BACKGROUND = "#FDECEF"

# デモモード表示
DEMO_BADGE_BACKGROUND = "#FFD54F"


# --------------------------------------------------
# 大きさ
# --------------------------------------------------

HEADER_HEIGHT = 52
STEP_BAR_HEIGHT = 56
FOOTER_HEIGHT = 92
CORNER_RADIUS = 6
PAGE_PADDING_X = 40
PAGE_PADDING_Y = 22

# 下部のボタン(戻る・次へ)は、どの画面でも同じ大きさ・同じ位置
FOOTER_BUTTON_WIDTH = 260
FOOTER_BUTTON_HEIGHT = 68

# 選択肢のボタン
CHOICE_BUTTON_HEIGHT = 60


# --------------------------------------------------
# 文字
# --------------------------------------------------

FONT_SIZE_HEADER = 18      # ヘッダーのシステム名
FONT_SIZE_STEP = 17        # 手順表示
FONT_SIZE_TITLE = 26       # 画面の見出し(1画面に1つ)
FONT_SIZE_LARGE = 30       # 完了画面の「次にすること」
FONT_SIZE_BODY = 19
FONT_SIZE_SMALL = 16
FONT_SIZE_BUTTON = 21

# 日本語フォントの候補(上から順に、見つかったものを使う)
#   Windows      : Yu Gothic UI / Meiryo UI
#   Raspberry Pi : Noto Sans CJK JP(sudo apt install fonts-noto-cjk)
JAPANESE_FONT_CANDIDATES = [
    "Yu Gothic UI",
    "Meiryo UI",
    "Meiryo",
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "IPAexGothic",
    "TakaoGothic",
]

# 実際に使うフォント名(アプリ起動時に choose_font_family() で決まる)
_font_family = None


def choose_font_family(root_window):
    """インストールされている日本語フォントを選ぶ(ウィンドウ作成後に1回呼ぶ)"""
    global _font_family

    installed_families = set(tkinter.font.families(root_window))
    for family in JAPANESE_FONT_CANDIDATES:
        if family in installed_families:
            _font_family = family
            return family

    # 見つからなければ OS の標準フォントに任せる
    if sys.platform.startswith("win"):
        _font_family = "Segoe UI"
    else:
        _font_family = "TkDefaultFont"
    return _font_family


def font(size=FONT_SIZE_BODY, bold=False):
    """画面で使うフォントを作る"""
    weight = "bold" if bold else "normal"
    return customtkinter.CTkFont(family=_font_family, size=size, weight=weight)
