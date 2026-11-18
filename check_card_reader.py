# RC-S380 だけの確認。かざすとカードIDを表示する(Ctrl+C で終了)
#   python check_card_reader.py

import threading

import config
from card_reader import CardReaderError, NfcCardReader

card_reader = NfcCardReader(config.CARD_READER_PATH, config.CARD_TARGETS)
never_cancel = threading.Event()

print("社員証をかざしてください(Ctrl+C で終了)")
try:
    while True:
        card_id = card_reader.read_card(60, never_cancel)
        if card_id:
            print("カードID:", card_id)
except CardReaderError as error:
    print(error)
    print("USB の接続と、udev の設定(sudo python3 -m nfc で確認)を見てください。")
except KeyboardInterrupt:
    pass
