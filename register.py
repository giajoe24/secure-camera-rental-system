# 利用者の登録
#   python register.py
# 社員証をかざして、社員番号と氏名をキーボードで入れる。続けて何人でも登録できる。
# 終わるときは Ctrl+C。
# カードリーダーは同時に1つのプログラムしか使えないので、main.py は止めてから使う。
# (管理画面の「利用者の登録」でも同じことができる)

import threading

import config
from card_reader import CardReaderError, NfcCardReader
from db import Database, RentalError


def ask(question):
    # 空のまま Enter を押したら聞き直す
    while True:
        answer = input(question).strip()
        if answer != "":
            return answer


def register_one(database, card_reader):
    print()
    print("登録する社員証をかざしてください(Ctrl+C で終了)")
    card_id = None
    while card_id is None:
        card_id = card_reader.read_card(60, threading.Event())
    print("カードID:", card_id)

    user = database.find_user_by_card(card_id)
    if user is not None:
        print(f"この社員証はもう登録されています: {user['employee_number']} {user['name']}")
        return

    employee_number = ask("社員番号: ")
    name = ask("氏名: ")
    if input(f"{employee_number} {name} さんを登録します。よければ y: ").strip() != "y":
        print("登録しませんでした")
        return

    try:
        database.add_user(employee_number, name, card_id)
        print("登録しました")
    except RentalError as e:
        print(f"{e.title}: {e.message}")


def main():
    database = Database(config.DB_PATH)
    database.create_tables()
    card_reader = NfcCardReader(config.CARD_READER_PATH, config.CARD_TARGETS)

    print("登録されている人:", len(database.list_users()), "人")
    try:
        while True:
            register_one(database, card_reader)
    except CardReaderError as e:
        print(e)
        print("main.py が動いていたら止めてから、もう一度実行してください。")
    except KeyboardInterrupt:
        print()
        print("終わります")


if __name__ == "__main__":
    main()
