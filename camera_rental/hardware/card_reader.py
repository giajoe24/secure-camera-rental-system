"""
社員証(ICカード)の読み取り

    ・NfcCardReader  : 実機用(RC-S380 + nfcpy)
    ・DemoCardReader : デモ用(画面のボタンで「かざした」ことにする)

どちらも次のメソッドを持っています。

    read_card(timeout_seconds, cancel_event) -> カードID(文字列)

read_card() はカードがかざされるまで「待ち続ける(ブロックする)」関数です。
そのため GUI からは、必ず別スレッドで呼び出してください。
(GUI 側の処理は gui/screens_flow.py の CardScanScreen を参照)

戻り値:
    ・カードID(大文字16進数の文字列) : 読み取り成功
    ・None                             : タイムアウト または キャンセル

例外:
    ・CardReaderNotConnectedError : リーダーが見つからない
    ・CardReadError               : 読み取り中のエラー

【カードIDについての注意】
    nfcpy の tag.identifier は、カードの種類によって中身が違います。
        ・FeliCa          : IDm(8バイト)
        ・MIFARE など Type A : UID(4 / 7 / 10 バイト)
        ・Type B          : PUPI(4バイト)
    スマートフォンのタッチ決済など、読むたびに値が変わる(ランダムUID)
    カードもあります。社員証の種類は実機で必ず確認してください。

    また、IDm / UID は「カードを区別する番号」であり、暗号的な本人確認ではありません。
    複製(なりすまし)対策が必要な場合は、カード発行元の仕様に沿った
    認証方式の採用を検討してください(docs/DESIGN.md「9. リスク」参照)。

【実機の状態】
    NfcCardReader は「実装済み・実機未確認」です。
"""

import logging
import queue
import threading
import time

from camera_rental import errors

logger = logging.getLogger(__name__)


def identifier_to_card_id(identifier):
    """nfcpy の tag.identifier(bytes)を "012E4CAA..." の形の文字列にする"""
    return identifier.hex().upper()


class DemoCardReader:
    """
    デモ用のカードリーダー

    画面のデモボタンが simulate_touch(card_id) を呼ぶと、
    待っている read_card() がそのカードIDを返します。
    """

    def __init__(self, demo_cards):
        # demo_cards: [(ボタンに表示する名前, カードID), ...]
        self.demo_cards = demo_cards

        # スレッド間でカードIDを受け渡すための待ち行列
        self._touched_cards = queue.Queue()

    def simulate_touch(self, card_id):
        """デモボタンから呼ばれる: カードがかざされたことにする"""
        self._touched_cards.put(card_id)

    def read_card(self, timeout_seconds, cancel_event):
        # 前回の残りがあれば捨てる
        self._clear_old_touches()

        start_time = time.monotonic()
        while not cancel_event.is_set():
            elapsed_seconds = time.monotonic() - start_time
            if elapsed_seconds >= timeout_seconds:
                return None

            try:
                # 0.2秒ごとにキャンセルされていないか確認しながら待つ
                card_id = self._touched_cards.get(timeout=0.2)
            except queue.Empty:
                continue

            logger.info("[デモ] カードを読み取りました: %s", card_id)
            return card_id

        return None

    def _clear_old_touches(self):
        while True:
            try:
                self._touched_cards.get_nowait()
            except queue.Empty:
                return


class NfcCardReader:
    """
    RC-S380 から nfcpy で社員証を読み取るクラス

    ※ 実装済み・実機未確認
    """

    def __init__(self, device_path="usb", targets=None):
        self.device_path = device_path
        self.targets = targets or ["212F", "106A", "106B"]

        # 同時に2つのスレッドからリーダーを開かないようにする
        self._reader_lock = threading.Lock()

    def read_card(self, timeout_seconds, cancel_event):
        # nfcpy は実機モードでのみ使うので、ここで読み込む
        try:
            import nfc
        except ImportError as error:
            raise errors.CardReaderNotConnectedError(
                detail="nfcpy がインストールされていません",
            ) from error

        with self._reader_lock:
            frontend = self._open_frontend(nfc)
            try:
                return self._wait_for_card(frontend, timeout_seconds, cancel_event)
            finally:
                # 読み取りが終わったら必ずリーダーを閉じる
                frontend.close()

    def _open_frontend(self, nfc_module):
        """リーダーを開く。見つからなければ CardReaderNotConnectedError"""
        try:
            frontend = nfc_module.ContactlessFrontend(self.device_path)
        except OSError as error:
            # 例: [Errno 19] No such device (未接続)
            #     [Errno 13] Permission denied (権限不足: udev ルール未設定)
            #     [Errno 16] Device or resource busy (別プロセスが使用中)
            logger.error("カードリーダーを開けませんでした: %s", error)
            raise errors.CardReaderNotConnectedError(detail=str(error)) from error

        if not frontend:
            raise errors.CardReaderNotConnectedError(detail="ContactlessFrontend が空です")

        logger.info("カードリーダーを開きました: %s", frontend)
        return frontend

    def _wait_for_card(self, frontend, timeout_seconds, cancel_event):
        """カードがかざされるまで待ち、カードIDを返す"""
        start_time = time.monotonic()

        def should_stop():
            # nfcpy が定期的に呼ぶ関数。True を返すと待つのをやめる
            if cancel_event.is_set():
                return True
            elapsed_seconds = time.monotonic() - start_time
            return elapsed_seconds >= timeout_seconds

        def on_connect(tag):
            # False を返すと、カードを検出した時点ですぐ connect() が戻る
            return False

        reader_options = {
            "targets": self.targets,
            "on-connect": on_connect,
            # nfcpy は「iterations 回探すごと」に should_stop を確認します。
            # 初期値(5回 × 0.5秒間隔)だと「やめる」を押してから止まるまで
            # 最大2秒以上かかるため、2回 × 0.2秒間隔にしています。
            "iterations": 2,
            "interval": 0.2,
        }

        try:
            tag = frontend.connect(rdwr=reader_options, terminate=should_stop)
        except Exception as error:
            logger.exception("社員証の読み取り中にエラーが発生しました")
            raise errors.CardReadError(detail=str(error)) from error

        # connect() の戻り値:
        #   None  : terminate が True を返した(タイムアウト / キャンセル)
        #   False : 通信エラーなどで中断
        #   Tag   : 読み取り成功
        if tag is None:
            return None
        if tag is False:
            raise errors.CardReadError(detail="connect() が False を返しました")

        identifier = getattr(tag, "identifier", None)
        if not identifier:
            raise errors.CardReadError(detail=f"識別子を取得できないカードです: {tag}")

        card_id = identifier_to_card_id(identifier)
        logger.info("社員証を読み取りました: 種別=%s", getattr(tag, "type", "不明"))
        return card_id
