"""
データ管理ツール(管理者用・コマンドライン)

一般利用者がタッチ画面から誤って操作できないよう、
登録・変更系の機能はこのコマンドだけにしています。

使い方の例(PowerShell / ターミナル):

    python manage_data.py add-user 10002 "森 航太郎" 012E4CAA12345678
    python manage_data.py add-camera "セキュアカメラ2号機"
    python manage_data.py list-users
    python manage_data.py list-cameras

その他のコマンド:

    python manage_data.py disable-user 10002          利用停止にする
    python manage_data.py enable-user 10002           利用可能に戻す
    python manage_data.py set-camera-status 2 maintenance   点検中にする
    python manage_data.py set-camera-status 2 available     貸出可能に戻す
    python manage_data.py list-rentals                履歴を表示
    python manage_data.py list-rentals --active       未返却だけ表示
    python manage_data.py force-return 15             貸出ID 15 を管理者返却にする
    python manage_data.py export-history              履歴を CSV に出力
    python manage_data.py unlock-logs                 解錠の成功・失敗ログを表示
    python manage_data.py check                       カメラ状態と貸出記録の食い違いを確認

対象のデータベース:
    何も指定しなければ config.py の DEMO_MODE に合わせて選びます。
    明示したい場合は --demo / --real を付けてください(コマンド名の前に書きます)。

        python manage_data.py --real list-users
"""

import argparse
import sys
import unicodedata
from datetime import datetime

import config
from camera_rental import errors
from camera_rental.database import Database
from camera_rental.hardware.lock_controller import DemoLockController
from camera_rental.models import (
    CAMERA_STATUS_AVAILABLE,
    CAMERA_STATUS_MAINTENANCE,
    format_for_display,
)
from camera_rental.rental_service import RentalService


# ==================================================
# 表示の補助
# ==================================================

def display_width(text):
    """
    画面上の文字幅を数える(全角は2、半角は1)

    日本語を含む表の列をそろえるために使います。
    """
    width = 0
    for character in str(text):
        if unicodedata.east_asian_width(character) in ("F", "W"):
            width += 2
        else:
            width += 1
    return width


def pad_right(text, width):
    """全角を考慮して、右側を空白で埋める"""
    text = str(text)
    return text + " " * (width - display_width(text))


def print_table(headers, rows):
    """見出しと行のリストを、列をそろえて表示する"""
    column_widths = [display_width(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            column_widths[index] = max(column_widths[index], display_width(value))

    header_line = "  ".join(pad_right(header, column_widths[index]) for index, header in enumerate(headers))
    print(header_line)
    print("-" * display_width(header_line))

    for row in rows:
        print("  ".join(pad_right(value, column_widths[index]) for index, value in enumerate(row)))

    print(f"({len(rows)} 件)")


# ==================================================
# 各コマンド
# ==================================================

def command_add_user(database, arguments):
    user = database.add_user(
        employee_number=arguments.employee_number,
        name=arguments.name,
        card_id=arguments.card_id,
        created_at=datetime.now(),
        is_active=not arguments.disabled,
    )
    print(f"利用者を登録しました: 社員番号 {user.employee_number} / {user.name} / カードID {user.card_id}")


def command_add_camera(database, arguments):
    camera = database.add_camera(arguments.name, created_at=datetime.now())
    print(f"カメラを登録しました: ID {camera.id} / {camera.name} / {camera.status_label}")


def command_list_users(database, arguments):
    users = database.list_users()
    rows = []
    for user in users:
        rows.append([user.id, user.employee_number, user.name, user.card_id, user.active_label])
    print_table(["ID", "社員番号", "氏名", "カードID", "利用可否"], rows)


def command_list_cameras(database, arguments):
    rows = []
    for status_row in database.list_camera_statuses():
        camera = status_row.camera
        rental = status_row.rental
        borrower = rental.user_name if rental else ""
        due_text = format_for_display(rental.due_at) if rental else ""
        rows.append([camera.id, camera.name, camera.status_label, borrower, due_text])
    print_table(["ID", "カメラ名", "状態", "貸出中の利用者", "返却予定"], rows)


def command_set_user_active(database, arguments, is_active):
    database.set_user_active(arguments.employee_number, is_active)
    state_text = "利用可" if is_active else "利用停止"
    print(f"社員番号 {arguments.employee_number} を「{state_text}」にしました")


def command_set_camera_status(database, arguments):
    database.set_camera_status(arguments.camera_id, arguments.status)
    camera = database.get_camera(arguments.camera_id)
    print(f"カメラ「{camera.name}」を「{camera.status_label}」にしました")


def command_list_rentals(database, arguments):
    rentals = database.list_rentals(limit=arguments.limit)
    if arguments.active:
        rentals = [rental for rental in rentals if not rental.is_returned]

    now = datetime.now()
    rows = []
    for rental in rentals:
        overdue_text = "延滞" if rental.is_overdue(now) else ""
        rows.append([
            rental.id,
            rental.employee_number,
            rental.user_name,
            rental.camera_name,
            format_for_display(rental.rented_at),
            format_for_display(rental.due_at),
            format_for_display(rental.returned_at),
            rental.state_label,
            overdue_text,
        ])
    print_table(["ID", "社員番号", "氏名", "カメラ", "貸出日時", "返却予定", "返却日時", "状態", ""], rows)


def command_force_return(service, arguments):
    rental = service.force_return(arguments.rental_id)
    print(f"貸出ID {rental.id}({rental.user_name} / {rental.camera_name})を管理者返却にしました")
    print("※ 電磁ロックは解錠していません。カメラの所在を確認してください。")


def command_export_history(service, arguments):
    saved_path = service.export_history_csv(output_path=arguments.output)
    print(f"CSV を保存しました: {saved_path}")


def command_unlock_logs(database, arguments):
    logs = database.list_unlock_logs(limit=arguments.limit)
    rows = []
    for log in logs:
        rows.append([
            log["id"],
            log["created_at"],
            log["rental_id"] if log["rental_id"] is not None else "",
            log["action"],
            "成功" if log["result"] == "success" else "失敗",
            log["message"],
        ])
    print_table(["ID", "日時", "貸出ID", "操作", "結果", "詳細"], rows)


def command_check(database, arguments):
    problems = database.find_inconsistencies()
    if not problems:
        print("問題は見つかりませんでした。")
        return
    print("次の食い違いが見つかりました:")
    for problem in problems:
        print(f"  ・{problem}")


# ==================================================
# 引数の定義
# ==================================================

def build_parser():
    parser = argparse.ArgumentParser(
        description="セキュアカメラ貸出管理システム データ管理ツール",
    )

    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument("--demo", action="store_true", help="デモ用データベースを対象にする")
    target_group.add_argument("--real", action="store_true", help="実機用データベースを対象にする")

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="コマンド")

    add_user_parser = subparsers.add_parser("add-user", help="利用者を登録する")
    add_user_parser.add_argument("employee_number", help="社員番号")
    add_user_parser.add_argument("name", help="氏名(空白を含む場合は \" \" で囲む)")
    add_user_parser.add_argument("card_id", help="社員証のカードID(tools/check_card_reader.py で確認)")
    add_user_parser.add_argument("--disabled", action="store_true", help="利用停止の状態で登録する")

    add_camera_parser = subparsers.add_parser("add-camera", help="カメラを登録する")
    add_camera_parser.add_argument("name", help="カメラ名")

    subparsers.add_parser("list-users", help="利用者の一覧を表示する")
    subparsers.add_parser("list-cameras", help="カメラの一覧を表示する")

    enable_parser = subparsers.add_parser("enable-user", help="利用者を利用可能にする")
    enable_parser.add_argument("employee_number", help="社員番号")

    disable_parser = subparsers.add_parser("disable-user", help="利用者を利用停止にする")
    disable_parser.add_argument("employee_number", help="社員番号")

    camera_status_parser = subparsers.add_parser("set-camera-status", help="カメラの状態を変更する")
    camera_status_parser.add_argument("camera_id", type=int, help="カメラID(list-cameras で確認)")
    camera_status_parser.add_argument(
        "status",
        choices=[CAMERA_STATUS_AVAILABLE, CAMERA_STATUS_MAINTENANCE],
        help="available(貸出可能) または maintenance(点検中)",
    )

    rentals_parser = subparsers.add_parser("list-rentals", help="貸出履歴を表示する")
    rentals_parser.add_argument("--active", action="store_true", help="未返却だけ表示する")
    rentals_parser.add_argument("--limit", type=int, default=50, help="表示件数(初期値 50)")

    force_return_parser = subparsers.add_parser("force-return", help="貸出を管理者返却にする")
    force_return_parser.add_argument("rental_id", type=int, help="貸出ID(list-rentals で確認)")

    export_parser = subparsers.add_parser("export-history", help="履歴を CSV に出力する")
    export_parser.add_argument("--output", help="保存先のファイル名(省略時は exports フォルダ)")

    unlock_logs_parser = subparsers.add_parser("unlock-logs", help="解錠ログを表示する")
    unlock_logs_parser.add_argument("--limit", type=int, default=50, help="表示件数(初期値 50)")

    subparsers.add_parser("check", help="カメラ状態と貸出記録の食い違いを確認する")

    return parser


def choose_database_path(arguments):
    if arguments.demo:
        return config.DEMO_DATABASE_PATH, "デモ用"
    if arguments.real:
        return config.DATABASE_PATH, "実機用"
    if config.DEMO_MODE:
        return config.DEMO_DATABASE_PATH, "デモ用(config.DEMO_MODE = True)"
    return config.DATABASE_PATH, "実機用(config.DEMO_MODE = False)"


def main():
    parser = build_parser()
    arguments = parser.parse_args()

    database_path, database_label = choose_database_path(arguments)
    # どのデータベースを操作しているか、毎回はっきり表示する(取り違え防止)
    print(f"対象データベース: {database_label}  {database_path}")
    print()

    database = Database(database_path)

    # CSV出力・強制返却は RentalService の処理を使う
    # (管理ツールからは解錠しないので、ロックはデモ用を渡しています)
    service = RentalService(
        database=database,
        lock_controller=DemoLockController(),
        rental_hours_options=config.RENTAL_HOURS_OPTIONS,
        unlock_seconds=config.UNLOCK_SECONDS,
        export_directory=config.EXPORT_DIRECTORY,
    )

    try:
        database.initialize()

        if arguments.command == "add-user":
            command_add_user(database, arguments)
        elif arguments.command == "add-camera":
            command_add_camera(database, arguments)
        elif arguments.command == "list-users":
            command_list_users(database, arguments)
        elif arguments.command == "list-cameras":
            command_list_cameras(database, arguments)
        elif arguments.command == "enable-user":
            command_set_user_active(database, arguments, is_active=True)
        elif arguments.command == "disable-user":
            command_set_user_active(database, arguments, is_active=False)
        elif arguments.command == "set-camera-status":
            command_set_camera_status(database, arguments)
        elif arguments.command == "list-rentals":
            command_list_rentals(database, arguments)
        elif arguments.command == "force-return":
            command_force_return(service, arguments)
        elif arguments.command == "export-history":
            command_export_history(service, arguments)
        elif arguments.command == "unlock-logs":
            command_unlock_logs(database, arguments)
        elif arguments.command == "check":
            command_check(database, arguments)

    except errors.CameraRentalError as error:
        print(f"エラー: {error.title}")
        print(error.user_message)
        if error.detail:
            print(f"(詳細: {error.detail})")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
