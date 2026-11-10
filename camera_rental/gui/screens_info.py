"""
確認用の画面(読み取り専用)

    ・StatusScreen  : 現在の貸出状況(カメラごとの状態・借りている人・返却予定)
    ・HistoryScreen : 貸出・返却の履歴と CSV 出力

どちらも「見るだけ」の画面で、データを変更する操作はありません。
(利用者・カメラの登録などの管理機能は manage_data.py から行います)
"""

import customtkinter

from camera_rental import errors
from camera_rental.gui import theme
from camera_rental.gui.widgets import (
    CAMERA_STATUS_BADGE_KIND,
    BaseScreen,
    MessagePanel,
    Pager,
    StatusBadge,
    label,
    primary_button,
    secondary_button,
)
from camera_rental.models import format_compact, format_for_display


# ======================================================
# 貸出状況
# ======================================================

class StatusScreen(BaseScreen):
    """現在の貸出状況"""

    ROWS_PER_PAGE = 5

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.set_title("現在の貸出状況")

        home_button = secondary_button(self.bottom_area, "ホームに戻る", self.app.go_home)
        home_button.pack(side="left")

        refresh_button = secondary_button(self.bottom_area, "最新の状態にする",
                                          lambda: self.app.show_screen(StatusScreen))
        refresh_button.pack(side="right")

        try:
            status_rows = self.app.service.list_camera_statuses()
        except errors.CameraRentalError as error:
            MessagePanel(self.content_area, "error", error.title, error.user_message).pack(fill="x")
            return

        if not status_rows:
            label(self.content_area, "カメラが登録されていません。", color=theme.TEXT_SUB).pack(anchor="w")
            return

        self.now = self.app.service.now()
        pager = Pager(self.content_area, status_rows, self.ROWS_PER_PAGE, self._render_rows)
        pager.pack(fill="both", expand=True)

    def _render_rows(self, list_frame, rows_on_page):
        for status_row in rows_on_page:
            self._add_row(list_frame, status_row)

    def _add_row(self, list_frame, status_row):
        camera = status_row.camera
        rental = status_row.rental

        row_frame = customtkinter.CTkFrame(
            list_frame,
            fg_color=theme.WHITE,
            border_color=theme.BORDER,
            border_width=1,
            corner_radius=12,
        )
        row_frame.pack(fill="x", pady=4)
        row_frame.grid_columnconfigure(2, weight=1)

        name_label = label(row_frame, camera.name, bold=True)
        name_label.configure(width=230)
        name_label.grid(row=0, column=0, sticky="w", padx=(16, 8), pady=12)

        # 色だけでなく「貸出可能」などの文字を必ず表示する
        badge = StatusBadge(row_frame, camera.status_label, CAMERA_STATUS_BADGE_KIND.get(camera.status, "neutral"))
        badge.grid(row=0, column=1, sticky="w", padx=8)

        if rental is not None:
            detail_text = f"{rental.user_name} さん  /  返却予定 {format_for_display(rental.due_at)}"
            detail_label = label(row_frame, detail_text, color=theme.TEXT_SUB, size=theme.FONT_SIZE_SMALL)
            detail_label.grid(row=0, column=2, sticky="w", padx=8)

            if rental.is_overdue(self.now):
                overdue_badge = StatusBadge(row_frame, "延滞", "error")
                overdue_badge.grid(row=0, column=3, sticky="e", padx=(8, 16))


# ======================================================
# 履歴
# ======================================================

class HistoryScreen(BaseScreen):
    """貸出・返却の履歴"""

    ROWS_PER_PAGE = 7

    # (列名, 幅の比率)
    # 固定幅ではなく比率にして、ウィンドウの幅に合わせて列が伸び縮みするようにしています。
    COLUMNS = [
        ("貸出日時", 3),
        ("氏名", 3),
        ("カメラ", 4),
        ("返却予定", 3),
        ("返却日時", 3),
        ("状態", 3),
    ]

    def __init__(self, parent, app, export_message=None, export_failed=False):
        super().__init__(parent, app)

        limit = self.app.settings.HISTORY_DISPLAY_LIMIT
        self.set_title("貸出・返却の履歴", subtitle=f"新しい順に最大 {limit} 件を表示しています。")

        home_button = secondary_button(self.bottom_area, "ホームに戻る", self.app.go_home)
        home_button.pack(side="left")

        if self.app.settings.ALLOW_CSV_EXPORT_FROM_SCREEN:
            export_button = primary_button(self.bottom_area, "CSVに出力する", self._export_csv, width=240)
            export_button.pack(side="right")

        if export_message:
            kind = "error" if export_failed else "success"
            title = "CSVを保存できませんでした" if export_failed else "CSVを保存しました"
            MessagePanel(self.content_area, kind, title, export_message).pack(fill="x", pady=(0, 8))

        try:
            rentals = self.app.service.list_recent_rentals(limit)
        except errors.CameraRentalError as error:
            MessagePanel(self.content_area, "error", error.title, error.user_message).pack(fill="x")
            return

        if not rentals:
            label(self.content_area, "まだ履歴はありません。", color=theme.TEXT_SUB).pack(anchor="w")
            return

        pager = Pager(self.content_area, rentals, self.ROWS_PER_PAGE, self._render_rows)
        pager.pack(fill="both", expand=True)

    def _render_rows(self, list_frame, rentals_on_page):
        """
        見出し行と履歴の行を、1つの表(grid)に並べる

        見出しと中身を同じ grid に置くことで、列の位置が必ずそろいます。
        """
        table = customtkinter.CTkFrame(list_frame, fg_color="transparent")
        table.pack(fill="x")

        for column_index, (column_name, column_weight) in enumerate(self.COLUMNS):
            table.grid_columnconfigure(column_index, weight=column_weight, uniform="history")

            # 先頭の空白は、下の行(padx=4)と文字の位置をそろえるため
            header_label = label(table, f" {column_name}", size=theme.FONT_SIZE_SMALL,
                                 bold=True, color=theme.TEXT_SUB)
            header_label.configure(fg_color=theme.APP_BACKGROUND)
            header_label.grid(row=0, column=column_index, sticky="ew", pady=(0, 4))

        for row_index, rental in enumerate(rentals_on_page, start=1):
            # 画面幅が狭くても収まるよう、日時は短い形式(年は下2桁)で表示する
            values = [
                format_compact(rental.rented_at),
                rental.user_name,
                rental.camera_name,
                format_compact(rental.due_at),
                format_compact(rental.returned_at),
                rental.state_label,
            ]
            for column_index, value in enumerate(values):
                # 「未返却」は青の太字で目立たせる(文字でも分かる)
                is_not_returned_cell = column_index == 5 and not rental.is_returned
                color = theme.INFO_TEXT if is_not_returned_cell else theme.TEXT_MAIN
                value_label = label(table, value, size=theme.FONT_SIZE_SMALL, color=color,
                                    bold=is_not_returned_cell)
                value_label.grid(row=row_index, column=column_index, sticky="w", padx=(4, 0), pady=6)

    def _export_csv(self):
        try:
            saved_path = self.app.service.export_history_csv()
        except errors.CameraRentalError as error:
            self.app.show_screen(HistoryScreen, export_message=error.user_message, export_failed=True)
            return

        self.app.show_screen(HistoryScreen, export_message=f"保存先: {saved_path}")
