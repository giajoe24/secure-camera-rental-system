# 追加機能: 利用者の部署と、利用停止・再開(config.USE_USER_INFO)
# users テーブルに列を 2 つ足す(今ある DB にも、起動したときに自動で足す)
#   department  部署(空でもよい)
#   active      1 = 使える / 0 = 利用停止中
# 利用停止中の社員証では、借りる・返す・延長ができない。登録と記録はそのまま残る。

import logging

from db import RentalError

log = logging.getLogger(__name__)


def add_columns(database):
    # main.py と register.py から呼ぶ。列がなければ足す
    columns = [row["name"] for row in database.select_all("PRAGMA table_info(users)")]
    if "department" not in columns:
        database.execute("ALTER TABLE users ADD COLUMN department TEXT NOT NULL DEFAULT ''")
        log.info("users に department(部署)の列を足しました")
    if "active" not in columns:
        database.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        log.info("users に active(利用停止)の列を足しました")


def department_of(user):
    return user["department"]


def set_department(database, user, department):
    database.execute("UPDATE users SET department = ? WHERE id = ?", (department, user["id"]))


def is_active(user):
    return user["active"] == 1


def check_active(user):
    # 社員証をかざしたときに呼ぶ。利用停止中ならエラーにする
    if not is_active(user):
        log.info("利用停止中の社員証: %s", user["employee_number"])
        raise RentalError("利用停止中の社員証です", "使えるようにするには、管理者に連絡してください。")


def set_active(database, user, active, user_is_admin=False):
    if not active and user_is_admin:
        raise RentalError("停止できません", "管理者は利用停止にできません。先に「管理者をやめる」を押してください。")
    database.execute("UPDATE users SET active = ? WHERE id = ?", (1 if active else 0, user["id"]))
