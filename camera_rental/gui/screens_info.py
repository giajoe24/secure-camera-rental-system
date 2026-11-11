"""
確認用の画面(読み取り専用)

    ・HistoryScreen : 貸出・返却の履歴と CSV 出力

この画面は「見るだけ」で、データを変更する操作はありません。
(利用者・カメラの登録などの管理機能は manage_data.py から行います)

※ 現在の貸出状況は、ホーム画面の左側にいつも表示しています。
"""

import customtkinter

from camera_rental import errors
from camera_rental.gui import theme
from camera_rental.gui.widgets import BaseScreen, Pager, horizontal_line, label
from camera_rental.models import format_compact


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
        self.set_title("貸出・返却の履歴", note=f"新しい順に {limit} 件まで表示しています。")

        if export_message:
            color = theme.ERROR_TEXT if export_failed else theme.SUCCESS_TEXT
            result_label = label(self.title_area, export_message, bold=True, color=color)
            result_label.pack(anchor="w", pady=(6, 0))

        self.add_back_button("戻る", self.app.go_home)

        if self.app.settings.ALLOW_CSV_EXPORT_FROM_SCREEN:
            self.add_next_button("CSVに保存する", self._export_csv)

        try:
            rentals = self.app.service.list_recent_rentals(limit)
        except errors.CameraRentalError as error:
            label(self.content_area, f"{error.title}。{error.user_message}", color=theme.ERROR_TEXT).pack(anchor="w")
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

            header_label = label(table, column_name, size=theme.FONT_SIZE_SMALL, color=theme.TEXT_SUB)
            header_label.grid(row=0, column=column_index, sticky="w", pady=(0, 6))

        header_line = horizontal_line(table, thickness=2, color=theme.TEXT_MAIN)
        header_line.grid(row=1, column=0, columnspan=len(self.COLUMNS), sticky="ew")

        for row_index, rental in enumerate(rentals_on_page):
            grid_row = row_index * 2 + 2

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
                value_label.grid(row=grid_row, column=column_index, sticky="w", pady=7)

            line = horizontal_line(table)
            line.grid(row=grid_row + 1, column=0, columnspan=len(self.COLUMNS), sticky="ew")

    def _export_csv(self):
        try:
            saved_path = self.app.service.export_history_csv()
        except errors.CameraRentalError as error:
            self.app.show_screen(HistoryScreen, export_message=f"{error.title}。{error.user_message}",
                                 export_failed=True)
            return

        self.app.show_screen(HistoryScreen, export_message=f"保存しました: {saved_path}")
