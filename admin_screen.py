# 管理画面
# ホームの「管理者」→ 管理者の社員証 → メニュー(利用者の登録 / 利用者の一覧 / 貸出の履歴)
#   利用者の一覧: 管理者にする・やめる、登録を消す
#   貸出の履歴  : 最近の記録を見る、CSV と Excel に保存する
# 記録を見られるのは管理者だけ。管理者は admins テーブルに入れる。
# 管理者がまだ1人もいないときは、「管理者」から最初の管理者を登録する(初期設定)

import logging
from datetime import datetime, timedelta

import customtkinter

import config
import events
import export
import overdue_record
import user_info
from db import RentalError, check_employee_number, normalize_card_id, parse_time
from gui_parts import (BLUE, BLUE_TAG, BORDER_COLOR, ERROR_TEXT_COLOR, GREEN_TAG, RED_TAG, SUB_TEXT_COLOR,
                       TEXT_COLOR, WHITE, YELLOW_TAG, Screen, disable_button, format_date_time, make_font, make_label,
                       make_line, make_sub_button, make_tag, show_as_selected)

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
    home.show_footer()
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


def back_to_menu(app):
    app.show(AdminMenuScreen)


def scan_new_card(app):
    # 利用者の登録:「戻る」・時間切れ・エラーでも、管理メニューに戻る(ホームまで戻らない)
    app.scan_card(REGISTER_STEPS, new_card_read, back=lambda: back_to_menu(app), back_name="メニュー")


# ---- 画面 ----

class AdminMenuScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.show_steps(ADMIN_STEPS, 1)
        self.show_title("管理メニュー", "使い終わったら「管理を終わる」を押してください。")
        self.add_left_button("管理を終わる", app.go_home)

        buttons = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        buttons.pack(fill="both", expand=True)
        buttons.grid_columnconfigure((0, 1), weight=1, uniform="a")
        buttons.grid_rowconfigure((0, 1), weight=1, uniform="b")

        menu = [
            ("利用者の登録", lambda: scan_new_card(app)),
            ("利用者の一覧", lambda: app.show(UserListScreen)),
            ("貸出の履歴", lambda: app.show(HistoryScreen)),
        ]
        if config.USE_EVENTS:
            menu.append(("できごとの記録", lambda: app.show(EventsScreen)))
        for i, (text, command) in enumerate(menu):
            button = make_sub_button(buttons, text, command)
            button.configure(font=make_font(21, True))
            button.grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)


class RegisterScreen(Screen):
    # first_admin=True: 初期設定(最初の管理者を登録する)
    # 社員番号と氏名は USB キーボードで入れる(氏名は日本語入力。docs/日本語入力の設定.txt)
    # 社員番号は 7 桁の数字だけ(db.py の check_employee_number)
    def __init__(self, app, card_id, first_admin=False):
        super().__init__(app)
        self.card_id = card_id
        self.first_admin = first_admin

        if first_admin:
            self.show_steps(FIRST_ADMIN_STEPS, 1)
            title = "最初の管理者を登録します"
            self.note = f"社員番号と氏名を入れてください。(カードID {card_id})"
            self.add_left_button("◀ ホーム", app.go_home)
        else:
            self.show_steps(REGISTER_STEPS, 1)
            title = "社員番号と氏名を入れてください"
            self.note = f"カードID {card_id}"
            self.add_left_button("◀ メニュー", lambda: back_to_menu(app))
        self.add_right_button("登録する", self.register)

        # 見出しの下の文は、入力にまちがいがあったらエラーの文に変える(画面の高さを変えないため)
        make_label(self.top_area, title, 24, True).pack(anchor="w")
        self.note_label = make_label(self.top_area, self.note, color=SUB_TEXT_COLOR)
        self.note_label.pack(anchor="w", pady=(4, 0))

        form = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        form.pack(fill="x")
        form.grid_columnconfigure(0, minsize=100)
        form.grid_columnconfigure((1, 3), weight=1, uniform="entry")

        make_label(form, "社員番号", color=SUB_TEXT_COLOR).grid(row=0, column=0, sticky="w", pady=6)
        self.number_entry = self.make_entry(form, "7 桁の数字(例: 1234567)")
        self.number_entry.grid(row=0, column=1, sticky="ew", pady=6)

        # 追加機能: 部署(社員番号の右に置いて、画面の高さを増やさない)
        self.department_entry = None
        if config.USE_USER_INFO:
            make_label(form, "部署", color=SUB_TEXT_COLOR).grid(row=0, column=2, sticky="w", padx=(16, 8), pady=6)
            self.department_entry = self.make_entry(form, "例: 総務部(なくてもよい)")
            self.department_entry.grid(row=0, column=3, sticky="ew", pady=6)

        make_label(form, "氏名", color=SUB_TEXT_COLOR).grid(row=1, column=0, sticky="w", pady=6)
        self.name_entry = self.make_entry(form, "例: 山田 太郎(「半角/全角」キーで日本語)")
        self.name_entry.grid(row=1, column=1, columnspan=3, sticky="ew", pady=6)

        # 管理者にするか(初期設定のときは必ず管理者なので出さない)
        self.admin_checkbox = customtkinter.CTkCheckBox(form, text="管理者にする", font=make_font(18),
                                                        text_color=TEXT_COLOR, fg_color=BLUE, hover=False,
                                                        checkbox_width=32, checkbox_height=32)
        if not first_admin:
            self.admin_checkbox.grid(row=2, column=1, columnspan=3, sticky="w", pady=6)

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
        new_user = self.app.database.find_user_by_card(self.card_id)

        if self.department_entry is not None:
            department = self.department_entry.get().strip()
            if department != "":
                user_info.set_department(self.app.database, new_user, department)

        if self.first_admin or self.admin_checkbox.get() == 1:
            set_admin(self.app.database, new_user, True)
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
        self.add_left_button("◀ メニュー", lambda: back_to_menu(app))
        self.add_right_button("続けて登録", lambda: scan_new_card(app))


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
    # 利用者の一覧。直したいときは「編集」から(管理者・停止・削除も編集画面でする)
    def __init__(self, app):
        super().__init__(app)
        self.show_steps(ADMIN_STEPS, 1)

        users = []
        for user in app.database.list_users():
            if not user["card_id"].startswith("DELETED-"):
                users.append(user)

        self.show_title(f"利用者の一覧({len(users)} 人)")
        self.add_left_button("◀ メニュー", lambda: back_to_menu(app))

        table = make_table(self.content_area, ["社員番号", "氏名", "", ""], [110, 0, 130, 120])
        for i, user in enumerate(users):
            name_text = user["name"]
            state = ""
            if is_admin(app.database, user):
                state = make_tag(table, "  管理者  ", BLUE_TAG)
            if config.USE_USER_INFO:
                if user_info.department_of(user) != "":
                    name_text += "\n" + user_info.department_of(user)   # 部署は名前の下に
                if not user_info.is_active(user):
                    state = make_tag(table, "  停止中  ", YELLOW_TAG)

            edit_button = make_sub_button(table, "編集", lambda u=user: app.show(EditUserScreen, user_id=u["id"]),
                                          width=110, height=48)
            add_table_row(table, i, [user["employee_number"], name_text, state, edit_button])

        if not users:
            show_empty(table, "まだ誰も登録されていません。", 4)


def update_user(database, user, employee_number, name):
    # 社員番号と氏名を直す(入力ミスの修正など)。記録(logs)は user_id でつながっているので、そのまま
    employee_number = check_employee_number(employee_number)
    if name == "":
        raise RentalError("直せません", "氏名を入れてください。")
    other = database.select_one("SELECT id FROM users WHERE employee_number = ? AND id != ?",
                                (employee_number, user["id"]))
    if other is not None:
        raise RentalError("直せません", "その社員番号はほかの人が使っています。")
    database.execute("UPDATE users SET employee_number = ?, name = ? WHERE id = ?", (employee_number, name, user["id"]))


def change_card(database, user, card_id):
    # 社員証を取り替える(なくした・新しくなったとき)。前の社員証は使えなくなる
    card_id = normalize_card_id(card_id)
    if database.find_user_by_card(card_id) is not None:
        raise RentalError("変えられません", "この社員証はもうほかの人に登録されています。")
    database.execute("UPDATE users SET card_id = ? WHERE id = ?", (card_id, user["id"]))


class EditUserScreen(Screen):
    # 1 人分の情報を直す画面
    #   上:社員番号・部署・氏名 →「保存する」
    #   下:社員証を変える / 管理者にする・やめる / 停止・再開 / 消す
    def __init__(self, app, user_id, message=None):
        super().__init__(app)
        self.user = app.database.select_one("SELECT * FROM users WHERE id = ?", (user_id,))
        self.admin = is_admin(app.database, self.user)
        self.show_steps(ADMIN_STEPS, 1)

        make_label(self.top_area, f"{self.user['name']} さんの情報", 24, True).pack(anchor="w")
        if message is None:
            message = f"カードID {self.user['card_id']}"
        self.note_label = make_label(self.top_area, message, color=SUB_TEXT_COLOR)
        self.note_label.pack(anchor="w", pady=(4, 0))

        self.add_left_button("◀ 一覧", lambda: app.show(UserListScreen))
        self.add_right_button("保存する", self.save)

        # ---- 入力欄(今の値を入れておく) ----
        form = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        form.pack(fill="x")
        form.grid_columnconfigure(0, minsize=100)
        form.grid_columnconfigure((1, 3), weight=1, uniform="entry")

        make_label(form, "社員番号", color=SUB_TEXT_COLOR).grid(row=0, column=0, sticky="w", pady=6)
        self.number_entry = self.make_filled_entry(form, self.user["employee_number"])
        self.number_entry.grid(row=0, column=1, sticky="ew", pady=6)

        self.department_entry = None
        if config.USE_USER_INFO:
            make_label(form, "部署", color=SUB_TEXT_COLOR).grid(row=0, column=2, sticky="w", padx=(16, 8), pady=6)
            self.department_entry = self.make_filled_entry(form, user_info.department_of(self.user))
            self.department_entry.grid(row=0, column=3, sticky="ew", pady=6)

        make_label(form, "氏名", color=SUB_TEXT_COLOR).grid(row=1, column=0, sticky="w", pady=6)
        self.name_entry = self.make_filled_entry(form, self.user["name"])
        self.name_entry.grid(row=1, column=1, columnspan=3, sticky="ew", pady=6)

        # ---- そのほかの操作 ----
        actions = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        actions.pack(fill="x", pady=(10, 0))

        self.add_action(actions, "社員証を変える", self.start_change_card)
        if self.admin:
            self.add_action(actions, "管理者をやめる", self.press_admin)
        else:
            self.add_action(actions, "管理者にする", self.press_admin)
        if config.USE_USER_INFO and not self.admin:
            if user_info.is_active(self.user):
                self.add_action(actions, "利用停止", self.press_active)
            else:
                self.add_action(actions, "利用再開", self.press_active)
        if not self.admin:   # 管理者は消せない
            self.delete_button = self.add_action(actions, "消す", self.press_delete)

    def make_filled_entry(self, parent, value):
        entry = customtkinter.CTkEntry(parent, height=52, font=make_font(20), fg_color=WHITE, text_color=TEXT_COLOR,
                                       border_width=2, border_color=BORDER_COLOR, corner_radius=8)
        entry.insert(0, value)
        entry.bind("<KeyPress>", self.app.record_touch, add="+")
        return entry

    def add_action(self, parent, text, command):
        button = make_sub_button(parent, text, command, width=160, height=52)
        button.configure(font=make_font(17))
        button.pack(side="left", padx=(0, 10))
        return button

    def show_error_text(self, text):
        self.note_label.configure(text=text, text_color=ERROR_TEXT_COLOR, font=make_font(17, True))

    def again(self, message):
        # 同じ画面を最新の内容で出し直す
        self.app.show(EditUserScreen, user_id=self.user["id"], message=message)

    def save(self):
        number = self.number_entry.get().strip()
        name = self.name_entry.get().strip()
        try:
            update_user(self.app.database, self.user, number, name)
            if self.department_entry is not None:
                user_info.set_department(self.app.database, self.user, self.department_entry.get().strip())
        except RentalError as e:
            self.show_error_text(e.message)
            return
        log.info("利用者の情報を直した: %s", number)
        self.again("保存しました。")

    def start_change_card(self):
        user_id = self.user["id"]

        def card_read(app, card_id):
            change_card(app.database, app.database.select_one("SELECT * FROM users WHERE id = ?", (user_id,)), card_id)
            log.info("社員証を変えた: user_id=%s", user_id)
            app.show(EditUserScreen, user_id=user_id, message="社員証を変えました。前の社員証は使えません。")

        self.app.scan_card(["新しい社員証", "完了"], card_read,
                           back=lambda: self.app.show(EditUserScreen, user_id=user_id), back_name="編集")

    def press_admin(self):
        try:
            if self.admin:
                if count_admins(self.app.database) == 1:
                    raise RentalError("やめられません", "管理者がいなくなります。先にほかの人を管理者にしてください。")
                set_admin(self.app.database, self.user, False)
                message = "管理者をやめました。"
            else:
                if config.USE_USER_INFO and not user_info.is_active(self.user):
                    raise RentalError("管理者にできません", "利用停止中の人は管理者にできません。先に「利用再開」を押してください。")
                set_admin(self.app.database, self.user, True)
                message = "管理者にしました。"
        except RentalError as e:
            self.show_error_text(e.message)
            return
        log.info("%s: %s", message, self.user["employee_number"])
        self.again(message)

    def press_active(self):
        # 利用停止 ⇔ 再開 を切り替える(記録は消えない)
        active = not user_info.is_active(self.user)
        try:
            user_info.set_active(self.app.database, self.user, active, user_is_admin=self.admin)
        except RentalError as e:
            self.show_error_text(e.message)
            return
        log.info("利用停止・再開を切り替えた: %s", self.user["employee_number"])
        if active:
            self.again("利用を再開しました。")
        else:
            self.again("利用停止にしました。この社員証では借りる・返す・延長ができません。")

    def press_delete(self):
        # 1回目は「本当に消す」に変えるだけ。2回目で消す(指が当たっただけで消えないように)
        if self.delete_button.cget("text") == "消す":
            self.delete_button.configure(text="本当に消す", text_color=ERROR_TEXT_COLOR, border_color=ERROR_TEXT_COLOR)
            return
        try:
            delete_user(self.app.database, self.user)
        except RentalError as e:
            self.show_error_text(e.message)
            return
        log.info("利用者を消した: %s", self.user["employee_number"])
        self.app.show(UserListScreen)


PERIODS = [("今日", 1), ("7日", 7), ("30日", 30), ("全部", None)]   # (ボタンの文字, 何日前から)


def search_rentals(rentals, word, days, now):
    # word: 名前か社員番号の一部(借りた人・返した人のどちらかに入っていればよい)。空なら絞らない
    # days: 貸出日時が今から何日以内か。None なら絞らない
    found = []
    for rental in rentals:
        if days is not None:
            start_of_period = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
            if parse_time(rental["rented_at"]) < start_of_period:
                continue
        if word != "":
            names = [rental["borrower_name"], rental["borrower_number"],
                     rental["returner_name"] or "", rental["returner_number"] or ""]
            if not any(word in name for name in names):
                continue
        found.append(rental)
    return found


class HistoryScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.show_steps(ADMIN_STEPS, 1)
        self.show_title("貸出の履歴")
        self.add_left_button("◀ メニュー", lambda: back_to_menu(app))
        self.save_button = self.add_right_button("ファイルに保存", self.save_files)

        self.days = None   # 選んでいる期間(None = 全部)

        # 検索の行:名前・社員番号(キーボード)と、期間のボタン(タッチ)
        search_row = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        search_row.pack(fill="x", pady=(0, 8))
        self.word_entry = customtkinter.CTkEntry(search_row, width=200, height=48, font=make_font(17),
                                                 placeholder_text="名前・社員番号", fg_color=WHITE,
                                                 text_color=TEXT_COLOR, border_width=2, border_color=BORDER_COLOR)
        self.word_entry.pack(side="left")
        self.word_entry.bind("<Return>", lambda event: self.show_rentals())   # Enter でも検索
        self.word_entry.bind("<KeyPress>", self.app.record_touch, add="+")
        make_sub_button(search_row, "検索", self.show_rentals, width=80, height=48).pack(side="left", padx=(6, 16))

        self.period_buttons = {}
        for text, days in PERIODS:
            button = make_sub_button(search_row, text, lambda d=days: self.choose_period(d), width=70, height=48)
            button.configure(font=make_font(17))
            button.pack(side="left", padx=3)
            self.period_buttons[days] = button

        self.table_area = customtkinter.CTkFrame(self.content_area, fg_color="transparent")
        self.table_area.pack(fill="both", expand=True)
        self.choose_period(None)

    def choose_period(self, days):
        self.days = days
        for d, button in self.period_buttons.items():
            show_as_selected(button, d == days)
            button.configure(font=make_font(17, d == days))
        self.show_rentals()

    def show_rentals(self):
        # 表を作り直す(画面全体は作り直さない)
        for widget in self.table_area.winfo_children():
            widget.destroy()

        headers = ["貸出日時", "借りた人", "返した人", "返却日時"]
        widths = [130, 0, 0, 130]
        if config.USE_OVERDUE_RECORD:
            headers.append("延滞")
            widths.append(80)
        table = make_table(self.table_area, headers, widths)

        word = self.word_entry.get().strip()
        found = search_rentals(self.app.database.list_rentals(), word, self.days, datetime.now())
        for i, rental in enumerate(found[:30]):
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

        if not found:
            show_empty(table, "当てはまる記録はありません。", len(headers))
        elif len(found) > 30:
            show_more = make_label(table, f"ほかに {len(found) - 30} 件あります(全部見るときは「ファイルに保存」)",
                                   16, color=SUB_TEXT_COLOR)
            show_more.grid(row=len(found[:30]) * 2 + 2, column=0, columnspan=len(headers), sticky="w", padx=6, pady=8)

    def save_files(self):
        # 全件を Excel と CSV で exports/ に保存する
        try:
            excel_path = export.export_to_excel(self.app.database, config.EXPORT_DIR)
            csv_path = export.export_to_csv(self.app.database, config.EXPORT_DIR)
        except Exception as e:
            self.app.show_error(e, back=lambda: self.app.show(HistoryScreen), back_text="履歴に戻る")
            return
        log.info("履歴を保存: %s / %s", excel_path.name, csv_path.name)
        disable_button(self.save_button)
        self.save_button.configure(text="保存しました")
        make_label(self.top_area, f"exports/ に保存しました: {excel_path.name} と .csv", 16,
                   color=SUB_TEXT_COLOR).pack(anchor="w")


class EventsScreen(Screen):
    # できごと(未登録カード、不正な開放、閉め忘れ、エラー)の新しい 30 件
    def __init__(self, app):
        super().__init__(app)
        self.show_steps(ADMIN_STEPS, 1)
        self.show_title("できごとの記録(新しい 30 件)")
        self.add_left_button("◀ メニュー", lambda: back_to_menu(app))

        table = make_table(self.content_area, ["日時", "種類", "内容"], [140, 130, 0])
        rows = events.list_events(app.database)[:30]
        for i, event in enumerate(rows):
            if event["kind"] in (events.FORCED_OPEN, events.ERROR):
                kind = make_tag(table, f" {event['kind']} ", RED_TAG)
            else:
                kind = make_tag(table, f" {event['kind']} ", YELLOW_TAG)
            detail = make_label(table, event["detail"], 16)
            detail.configure(wraplength=380)   # 長い内容は列の中で折り返す
            add_table_row(table, i, [format_date_time(parse_time(event["time"])), kind, detail])

        if not rows:
            show_empty(table, "まだ何も起きていません。", 3)
