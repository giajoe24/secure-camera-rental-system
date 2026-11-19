# 管理画面
# ホームの「管理者」→ 管理者の社員証 → メニュー(利用者の登録 / 利用者の一覧 / 貸出の履歴)
#   利用者の一覧: 管理者にする・やめる、登録を消す
#   貸出の履歴  : 最近の記録を見る、CSV と Excel に保存する
# 記録を見られるのは管理者だけ。管理者は admins テーブルに入れる。
# 管理者がまだ1人もいないときは、「管理者」から最初の管理者を登録する(初期設定)

import logging

import customtkinter

import config
import export
import overdue_record
from db import RentalError, normalize_card_id, parse_time
from gui_parts import (BLUE, BLUE_TAG, BORDER_COLOR, ERROR_TEXT_COLOR, GREEN_TAG, SUB_TEXT_COLOR, TEXT_COLOR,
                       WHITE, YELLOW_TAG, Screen, disable_button, format_date_time, make_font, make_label, make_line,
                       make_sub_button, make_tag)

log = logging.getLogger(__name__)

ADMIN_STEPS = ["管理者の社員証", "管理メニュー"]
REGISTER_STEPS = ["新しい社員証", "社員番号・氏名", "完了"]
FIRST_ADMIN_STEPS = ["管理者の社員証", "社員番号・氏名", "完了"]


# ---- DB ----

def create_admin_table(database):
    database.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY REFERENCES users (id))")


def count_admins(database):
    return database.select_one("SELECT COUNT(*) FROM admins")[0]


def is_admin(database, user):
    return database.select_one("SELECT 1 FROM admins WHERE user_id = ?", (user["id"],)) is not None


def set_admin(database, user, admin):
    if admin:
        database.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user["id"],))
    else:
        database.execute("DELETE FROM admins WHERE user_id = ?", (user["id"],))


def delete_user(database, user):
    # 記録(logs)は消さない。記録がある人は、名前が残るように行は残してカードだけ使えなくする
    if is_admin(database, user):
        raise RentalError("消せません", "管理者は消せません。先に「管理者をやめる」を押してください。")

    rental = database.current_rental()
    if rental is not None and rental["user_id"] == user["id"]:
        raise RentalError("消せません", "この人はいまカメラを借りています。返却してから消してください。")

    if database.select_one("SELECT 1 FROM logs WHERE user_id = ?", (user["id"],)) is None:
        database.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    else:
        database.execute("UPDATE users SET card_id = ? WHERE id = ?", (f"DELETED-{user['id']}", user["id"]))


# ---- ホームから入る ----

def add_button_on_home(home):
    home.add_left_button("管理者", lambda: start_admin(home.app))


def start_admin(app):
    if count_admins(app.database) == 0:
        app.scan_card(FIRST_ADMIN_STEPS, first_admin_card_read)   # 初期設定
    else:
        app.scan_card(ADMIN_STEPS, admin_card_read)


def admin_card_read(app, card_id):
    user = app.database.find_user_by_card(card_id)
    if user is None or not is_admin(app.database, user):
        log.info("管理者ではない社員証: %s", card_id)
        raise RentalError("管理者の社員証ではありません", "管理画面は管理者だけが使えます。")
    log.info("管理画面を開いた: %s", user["employee_number"])
    app.show(AdminMenuScreen)


def first_admin_card_read(app, card_id):
    # 最初の管理者の社員証が読めたら呼ばれる
    if count_admins(app.database) > 0:
        raise RentalError("管理者はもう登録されています", "管理者の社員証で入ってください。")

    user = app.database.find_user_by_card(card_id)
    if user is not None:
        # もう利用者として登録されている人なら、そのまま管理者にする
        set_admin(app.database, user, True)
        log.info("最初の管理者を登録: %s", user["employee_number"])
        app.show(AdminMenuScreen)
    else:
        app.show(RegisterScreen, card_id=normalize_card_id(card_id), first_admin=True)


def new_card_read(app, card_id):
    # 登録する社員証が読めたら呼ばれる
    if app.database.find_user_by_card(card_id) is not None:
        raise RentalError("登録済みの社員証です", "この社員証はもう登録されています。")
    app.show(RegisterScreen, card_id=normalize_card_id(card_id))


# ---- 画面 ----

class AdminMenuScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.show_steps(ADMIN_STEPS, 1)
        self.show_title("管理メニュー", "使い終わったら「終わる」を押してください。")
        self.add_left_button("終わる", app.go_home)

        buttons = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        buttons.pack(fill="both", expand=True)
        buttons.grid_columnconfigure((0, 1, 2), weight=1, uniform="a")
        buttons.grid_rowconfigure(0, weight=1)

        menu = [
            ("利用者の登録", lambda: app.scan_card(REGISTER_STEPS, new_card_read)),
            ("利用者の一覧", lambda: app.show(UserListScreen)),
            ("貸出の履歴", lambda: app.show(HistoryScreen)),
        ]
        for i, (text, command) in enumerate(menu):
            button = make_sub_button(buttons, text, command)
            button.configure(font=make_font(22, True))
            button.grid(row=0, column=i, sticky="nsew", padx=6)


class RegisterScreen(Screen):
    # first_admin=True: 初期設定(最初の管理者を登録する)
    # 社員番号と氏名は USB キーボードで入れる
    def __init__(self, app, card_id, first_admin=False):
        super().__init__(app)
        self.card_id = card_id
        self.first_admin = first_admin

        if first_admin:
            self.show_steps(FIRST_ADMIN_STEPS, 1)
            title = "最初の管理者を登録します"
            self.note = f"社員番号と氏名を入れてください。(カードID {card_id})"
            self.add_left_button("戻る", app.go_home)
        else:
            self.show_steps(REGISTER_STEPS, 1)
            title = "社員番号と氏名を入れてください"
            self.note = f"カードID {card_id}"
            self.add_left_button("戻る", lambda: app.show(AdminMenuScreen))
        self.add_right_button("登録する", self.register)

        # 見出しの下の文は、入力にまちがいがあったらエラーの文に変える(画面の高さを変えないため)
        make_label(self.top_area, title, 24, True).pack(anchor="w")
        self.note_label = make_label(self.top_area, self.note, color=SUB_TEXT_COLOR)
        self.note_label.pack(anchor="w", pady=(4, 0))

        form = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        form.pack(fill="x")
        form.grid_columnconfigure(0, minsize=120)
        form.grid_columnconfigure(1, weight=1)

        make_label(form, "社員番号", color=SUB_TEXT_COLOR).grid(row=0, column=0, sticky="w", pady=6)
        self.number_entry = self.make_entry(form, "例: 10001")
        self.number_entry.grid(row=0, column=1, sticky="ew", pady=6)

        make_label(form, "氏名", color=SUB_TEXT_COLOR).grid(row=1, column=0, sticky="w", pady=6)
        self.name_entry = self.make_entry(form, "例: 山田 太郎")
        self.name_entry.grid(row=1, column=1, sticky="ew", pady=6)

        # 管理者にするか(初期設定のときは必ず管理者なので出さない)
        self.admin_checkbox = customtkinter.CTkCheckBox(form, text="管理者にする", font=make_font(18),
                                                        text_color=TEXT_COLOR, fg_color=BLUE, hover=False,
                                                        checkbox_width=32, checkbox_height=32)
        if not first_admin:
            self.admin_checkbox.grid(row=2, column=1, sticky="w", pady=6)

        self.number_entry.focus_set()

    def make_entry(self, parent, example):
        entry = customtkinter.CTkEntry(parent, height=52, font=make_font(20), placeholder_text=example,
                                       fg_color=WHITE, text_color=TEXT_COLOR, border_width=2,
                                       border_color=BORDER_COLOR, corner_radius=8)
        entry.bind("<KeyPress>", self.app.record_touch, add="+")  # 入力中は「操作中」にする
        return entry

    def show_error_text(self, text):
        self.note_label.configure(text=text, text_color=ERROR_TEXT_COLOR, font=make_font(17, True))

    def register(self):
        number = self.number_entry.get().strip()
        name = self.name_entry.get().strip()
        if number == "" or name == "":
            self.show_error_text("社員番号と氏名の両方を入れてください。")
            return

        try:
            self.app.database.add_user(number, name, self.card_id)
        except RentalError as e:
            self.show_error_text(e.message)
            return
        log.info("利用者を登録: %s", number)

        if self.first_admin or self.admin_checkbox.get() == 1:
            set_admin(self.app.database, self.app.database.find_user_by_card(self.card_id), True)
            log.info("管理者にした: %s", number)

        if self.first_admin:
            self.app.show(AdminMenuScreen)
        else:
            self.app.show(RegisterDoneScreen, name=name)


class RegisterDoneScreen(Screen):
    def __init__(self, app, name):
        super().__init__(app)
        self.show_steps(REGISTER_STEPS, 2)
        make_tag(self.top_area, "  登録しました  ", GREEN_TAG).pack(anchor="w", pady=(0, 10))
        make_label(self.top_area, f"{name} さんを登録しました。", 26, True).pack(anchor="w")
        make_label(self.top_area, "この社員証でカメラを借りられます。", 20).pack(anchor="w", pady=(6, 0))
        self.add_left_button("メニュー", lambda: app.show(AdminMenuScreen))
        self.add_right_button("続けて登録", lambda: app.scan_card(REGISTER_STEPS, new_card_read))


# ---- 一覧の表 ----

def make_table(parent, headers, widths):
    # 見出しつきの表(スクロールできる)。widths が 0 の列は残りの幅いっぱい
    table = customtkinter.CTkScrollableFrame(parent, fg_color="transparent")
    table.pack(fill="both", expand=True)
    table._scrollbar.configure(width=28)   # 指で動かせるよう、スクロールバーを太くする
    for i, width in enumerate(widths):
        if width == 0:
            table.grid_columnconfigure(i, weight=1)
        else:
            table.grid_columnconfigure(i, minsize=width)

    for i, header in enumerate(headers):
        make_label(table, header, 16, color=SUB_TEXT_COLOR).grid(row=0, column=i, sticky="w", padx=6, pady=(0, 4))
    make_line(table).grid(row=1, column=0, columnspan=len(headers), sticky="ew")
    return table


def add_table_row(table, row_number, values):
    # row_number は 0 から。値が文字ならラベルにして、部品ならそのまま置く
    grid_row = row_number * 2 + 2   # 見出しと線の下から、行と線を交互に置く
    for i, value in enumerate(values):
        if isinstance(value, str):
            value = make_label(table, value, 17)
        value.grid(row=grid_row, column=i, sticky="w", padx=6, pady=6)
    make_line(table).grid(row=grid_row + 1, column=0, columnspan=len(values), sticky="ew")


def show_empty(table, text, columns):
    make_label(table, text, color=SUB_TEXT_COLOR).grid(row=2, column=0, columnspan=columns, sticky="w", padx=6, pady=16)


class UserListScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.show_steps(ADMIN_STEPS, 1)

        users = []
        for user in app.database.list_users():
            if not user["card_id"].startswith("DELETED-"):
                users.append(user)

        self.show_title(f"利用者の一覧({len(users)} 人)")
        self.add_left_button("メニュー", lambda: app.show(AdminMenuScreen))

        table = make_table(self.content_area, ["社員番号", "氏名", "", ""], [110, 0, 180, 120])
        for i, user in enumerate(users):
            if is_admin(app.database, user):
                admin_button = make_sub_button(table, "管理者をやめる", None, width=170, height=48)
                delete_part = make_tag(table, "  管理者  ", BLUE_TAG)   # 管理者は消せない
            else:
                admin_button = make_sub_button(table, "管理者にする", None, width=170, height=48)
                delete_part = make_sub_button(table, "消す", None, width=110, height=48)
                delete_part.configure(command=lambda b=delete_part, u=user: self.press_delete(b, u))
            admin_button.configure(font=make_font(17), command=lambda u=user: self.press_admin(u))
            add_table_row(table, i, [user["employee_number"], user["name"], admin_button, delete_part])

        if not users:
            show_empty(table, "まだ誰も登録されていません。", 4)

    def press_admin(self, user):
        try:
            if is_admin(self.app.database, user):
                if count_admins(self.app.database) == 1:
                    raise RentalError("やめられません", "管理者がいなくなります。先にほかの人を管理者にしてください。")
                set_admin(self.app.database, user, False)
                log.info("管理者をやめた: %s", user["employee_number"])
            else:
                set_admin(self.app.database, user, True)
                log.info("管理者にした: %s", user["employee_number"])
        except Exception as e:
            self.app.show_error(e, retry=lambda: self.app.show(UserListScreen), retry_text="一覧に戻る")
            return
        self.app.show(UserListScreen)

    def press_delete(self, button, user):
        # 1回目は「本当に消す」に変えるだけ。2回目で消す(指が当たっただけで消えないように)
        if button.cget("text") == "消す":
            button.configure(text="本当に消す", text_color=ERROR_TEXT_COLOR, border_color=ERROR_TEXT_COLOR)
            return

        try:
            delete_user(self.app.database, user)
        except Exception as e:
            self.app.show_error(e, retry=lambda: self.app.show(UserListScreen), retry_text="一覧に戻る")
            return
        log.info("利用者を消した: %s", user["employee_number"])
        self.app.show(UserListScreen)


class HistoryScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.show_steps(ADMIN_STEPS, 1)
        self.show_title("貸出の履歴(新しい 30 件)")
        self.add_left_button("メニュー", lambda: app.show(AdminMenuScreen))
        self.save_button = self.add_right_button("ファイルに保存", self.save_files)

        headers = ["貸出日時", "借りた人", "返した人", "返却日時"]
        widths = [140, 0, 0, 140]
        if config.USE_OVERDUE_RECORD:
            headers.append("延滞")
            widths.append(90)
        table = make_table(self.content_area, headers, widths)

        rentals = app.database.list_rentals()[:30]
        for i, rental in enumerate(rentals):
            if rental["returned_at"] is None:
                returner = "—"
                returned = make_tag(table, "  貸出中  ", BLUE_TAG)
            else:
                returner = rental["returner_name"]
                returned = format_date_time(parse_time(rental["returned_at"]))

            row = [format_date_time(parse_time(rental["rented_at"])), rental["borrower_name"], returner, returned]
            if config.USE_OVERDUE_RECORD:
                late = overdue_record.late_minutes_of(rental)
                if late:
                    row.append(make_tag(table, f" {late}分 ", YELLOW_TAG))
                else:
                    row.append("")
            add_table_row(table, i, row)

        if not rentals:
            show_empty(table, "まだ記録はありません。", len(headers))

    def save_files(self):
        # 全件を Excel と CSV で exports/ に保存する
        try:
            excel_path = export.export_to_excel(self.app.database, config.EXPORT_DIR)
            csv_path = export.export_to_csv(self.app.database, config.EXPORT_DIR)
        except Exception as e:
            self.app.show_error(e)
            return
        log.info("履歴を保存: %s / %s", excel_path.name, csv_path.name)
        disable_button(self.save_button)
        self.save_button.configure(text="保存しました")
        make_label(self.top_area, f"exports/ に保存しました: {excel_path.name} と .csv", 16,
                   color=SUB_TEXT_COLOR).pack(anchor="w")
