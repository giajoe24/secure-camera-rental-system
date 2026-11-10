"""
セキュアカメラ貸出管理システム

フォルダ構成:
    camera_rental/
        errors.py          例外と利用者向けメッセージ
        models.py          データの入れ物(利用者・カメラ・貸出)
        database.py        SQLite の読み書き
        rental_service.py  貸出・返却の手続き(DB記録 → 解錠 の順番を守る)
        app_logging.py     ログ設定
        hardware/          カードリーダー・電磁ロック(デモ用と実機用)
        gui/               CustomTkinter の画面
"""

__version__ = "1.0.0"
