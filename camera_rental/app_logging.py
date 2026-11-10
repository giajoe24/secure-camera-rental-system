"""
ログ出力の設定

    ・コンソール(PowerShell / ターミナル)
    ・ログファイル(logs/camera_rental.log)
の両方に出力します。

画面には Python の例外文を出さない代わりに、
詳しい内容(スタックトレース)はここで記録します。

ログファイルは 1MB を超えると自動で切り替え、古いものを5つまで残します。
(Raspberry Pi の SD カードがログでいっぱいにならないように)
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(log_directory, level=logging.INFO):
    """ログの出力先を設定する(アプリ起動時に1回だけ呼ぶ)"""
    log_directory = Path(log_directory)
    log_directory.mkdir(parents=True, exist_ok=True)
    log_file_path = log_directory / "camera_rental.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 2回呼ばれても同じ出力先が重複しないように、既存の設定を外す
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return log_file_path
