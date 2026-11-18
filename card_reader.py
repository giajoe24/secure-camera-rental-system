# 社員証の読み取り(RC-S380 / nfcpy)
# read_card() はカードがかざされるまで待つので、画面からは別スレッドで呼ぶ。
# 読めたらカードID(16進の文字列)、時間切れや中止なら None を返す。

import time


class CardReaderError(Exception):
    pass


class NfcCardReader:
    def __init__(self, path, targets):
        self.path = path
        self.targets = targets

    def read_card(self, timeout, cancel_event):
        try:
            import nfc
        except ImportError:
            raise CardReaderError("nfcpy がインストールされていません")

        try:
            reader = nfc.ContactlessFrontend(self.path)
        except OSError as e:
            raise CardReaderError(f"カードリーダーを開けません: {e}")

        self.timeout = timeout
        self.cancel_event = cancel_event
        self.start_time = time.monotonic()

        try:
            tag = reader.connect(
                rdwr={
                    "targets": self.targets,
                    "on-connect": lambda tag: False,  # 読めたらすぐ戻る
                    "iterations": 2,
                    "interval": 0.2,
                },
                terminate=self.should_stop,
            )
        finally:
            reader.close()

        if tag is None:
            return None
        if tag is False:
            raise CardReaderError("読み取り中に通信が切れました")
        return tag.identifier.hex().upper()

    def should_stop(self):
        # nfcpy が待っている間に何度も呼ばれる。True で待つのをやめる
        if self.cancel_event.is_set():
            return True
        return time.monotonic() - self.start_time > self.timeout
