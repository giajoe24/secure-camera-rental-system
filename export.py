# 記録をファイルにして exports/ に保存する(管理画面から使う)
#   Excel : シート「貸出一覧」と「操作の記録」(logs テーブルの中身そのまま)
#   CSV   : 貸出一覧だけ(Excel がない PC でも開ける)
# exports/rental_log.xlsx は、貸出・返却が終わるたびに自動で作り直す(update_excel)

import csv
import logging
import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import config
import overdue_record
from db import minutes_past, parse_time

log = logging.getLogger(__name__)

HEADER_FILL = PatternFill("solid", fgColor="1E4FA3")
HEADER_FONT = Font(bold=True, color="FFFFFF")
LATE_FILL = PatternFill("solid", fgColor="FFF1CC")   # 延滞した行(薄い黄色)
DATE_FORMAT = "yyyy/mm/dd hh:mm"

RENTAL_HEADERS = ["借りた人(社員番号)", "借りた人", "貸出日時", "返却予定", "返した人(社員番号)", "返した人", "返却日時", "状態"]
RENTAL_WIDTHS = [18, 16, 18, 18, 18, 16, 18, 10]


def to_time(text):
    # 文字の日時を Excel の日時にする(空なら空のまま)
    if text is None:
        return None
    return parse_time(text)


def is_late(rental, now):
    # 遅れて返した、または今まさに期限切れ
    if rental["returned_at"] is None:
        end = now
    else:
        end = parse_time(rental["returned_at"])
    return minutes_past(parse_time(rental["due_at"]), end) > 0


def rental_headers():
    headers = list(RENTAL_HEADERS)
    if config.USE_OVERDUE_RECORD:
        headers.append("延滞(分)")
    return headers


def rental_row(rental, for_excel):
    if rental["returned_at"] is None:
        state = "貸出中"
    else:
        state = "返却済み"

    times = [rental["rented_at"], rental["due_at"], rental["returned_at"]]
    if for_excel:
        times = [to_time(t) for t in times]

    row = [rental["borrower_number"], rental["borrower_name"], times[0], times[1],
           rental["returner_number"], rental["returner_name"], times[2], state]
    if config.USE_OVERDUE_RECORD:
        row.append(overdue_record.late_minutes_of(rental))
    return row


def add_sheet(book, title, headers, widths, rows):
    sheet = book.create_sheet(title)
    sheet.append(headers)
    for i in range(len(headers)):
        cell = sheet.cell(row=1, column=i + 1)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        sheet.column_dimensions[get_column_letter(i + 1)].width = widths[i]

    for row in rows:
        sheet.append(row)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, datetime):
                cell.number_format = DATE_FORMAT

    sheet.freeze_panes = "A2"   # 見出しを固定
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"   # 絞り込みできるように
    return sheet


def export_to_excel(database, output_dir, file_name=None):
    # file_name を指定しなければ、日時入りの名前で保存する
    now = datetime.now()
    rentals = database.list_rentals()

    book = Workbook()
    book.remove(book.active)   # 最初からある空のシートは使わない

    widths = list(RENTAL_WIDTHS)
    if config.USE_OVERDUE_RECORD:
        widths.append(10)
    sheet = add_sheet(book, "貸出一覧", rental_headers(), widths,
                      [rental_row(rental, for_excel=True) for rental in rentals])

    # 延滞した行に色をつける(色だけでなく「延滞(分)」の列にも数字が出る)
    for i, rental in enumerate(rentals):
        if is_late(rental, now):
            for cell in sheet[i + 2]:
                cell.fill = LATE_FILL

    log_rows = []
    for log in database.list_logs():
        log_rows.append([log["id"], to_time(log["time"]), log["action"], log["step"], log["employee_number"],
                         log["name"], to_time(log["due_at"]), log["note"]])
    add_sheet(book, "操作の記録", ["番号", "日時", "操作", "段階", "社員番号", "氏名", "返却予定", "メモ"],
              [8, 18, 8, 10, 12, 16, 18, 30], log_rows)

    if file_name is None:
        file_name = now.strftime("rental_log_%Y%m%d_%H%M%S.xlsx")
    output_dir.mkdir(exist_ok=True)
    path = output_dir / file_name

    # いったん別の名前で保存してから置き換える(途中で止まっても、壊れたファイルが残らないように)
    temp_path = path.with_suffix(".tmp")
    book.save(temp_path)
    os.replace(temp_path, path)
    return path


def update_excel(database):
    # 失敗しても貸出・返却は止めない(ログに残すだけ)
    try:
        export_to_excel(database, config.EXPORT_DIR, "rental_log.xlsx")
    except Exception:
        log.exception("Excel の記録を更新できませんでした")


def export_to_csv(database, output_dir):
    output_dir.mkdir(exist_ok=True)
    path = output_dir / datetime.now().strftime("rental_log_%Y%m%d_%H%M%S.csv")

    # utf-8-sig にすると Excel で開いても文字化けしない
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(rental_headers())
        for rental in database.list_rentals():
            writer.writerow(rental_row(rental, for_excel=False))
    return path
