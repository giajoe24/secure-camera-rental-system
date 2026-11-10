"""
画面の色・文字・大きさの設定

デザインを変えたいときは、まずこのファイルの値を変更してください。
画面ごとのファイルに色コードを直接書かないようにしているので、
ここを変えればアプリ全体の見た目がそろって変わります。
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
BRAND_RED_LIGHT = "#FDECEF"      # 社員証読み取り部分などの薄い赤背景
BRAND_RED_BORDER = "#F5B5C3"

# 全体
APP_BACKGROUND = "#F3F4F6"
CARD_BACKGROUND = "#FFFFFF"
TEXT_MAIN = "#202124"
TEXT_SUB = "#6B7280"
BORDER = "#E5E7EB"
WHITE = "#FFFFFF"

# 補助ボタン(戻る・やめる など)
SECONDARY_BUTTON = "#E5E7EB"
SECONDARY_BUTTON_HOVER = "#D1D5DB"
DISABLED_BUTTON = "#F3B3C1"

# 成功(緑)
SUCCESS_TEXT = "#137A4B"
SUCCESS_BACKGROUND = "#EAF8F0"
SUCCESS_STRONG = "#1E9E63"

# 警告(黄)
WARNING_TEXT = "#8A5A00"
WARNING_BACKGROUND = "#FFF6DB"
WARNING_BORDER = "#F4D27A"

# エラー(赤)
ERROR_TEXT = "#B3002A"
ERROR_BACKGROUND = "#FDECEF"

# 情報(青)… 「貸出中」の表示に使う(貸出中は異常ではないため、赤や黄にしない)
INFO_TEXT = "#1D4ED8"
INFO_BACKGROUND = "#EAF1FF"

# デモモード表示
DEMO_BADGE_BACKGROUND = "#FFD54F"
DEMO_BADGE_TEXT = "#202124"


# --------------------------------------------------
# 大きさ
# --------------------------------------------------

HEADER_HEIGHT = 72
CORNER_RADIUS = 14
CARD_CORNER_RADIUS = 18
PAGE_PADDING = 24
CARD_PADDING = 28

# タッチ操作しやすいよう、ボタンは高さ 60 以上にしています
BUTTON_HEIGHT = 64
BUTTON_WIDTH = 220
TILE_HEIGHT = 170


# --------------------------------------------------
# 文字
# --------------------------------------------------

FONT_SIZE_HEADER = 22
FONT_SIZE_TITLE = 28
FONT_SIZE_HEADING = 22
FONT_SIZE_BODY = 18
FONT_SIZE_SMALL = 15
FONT_SIZE_BUTTON = 20
FONT_SIZE_TILE = 30

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
