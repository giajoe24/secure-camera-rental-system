"""
電磁ロックの制御

    ・GpioLockController : 実機用(gpiozero で GPIO を ON/OFF する)
    ・DemoLockController : デモ用(GPIO に何も出力せず、ログに書くだけ)

どちらも同じメソッドを持っているので、GUI や貸出処理からは
「どちらのロックか」を気にせず使えます。

    is_ready              : 使える状態か(初期化に成功したか)
    not_ready_reason      : 使えない場合の理由(ログ・画面用)
    unlock(seconds)       : 指定秒数だけ解錠し、その後自動で施錠に戻す
    close()               : 終了処理(必ず施錠状態に戻す)

【実機の状態】
    GpioLockController は「実装済み・実機未確認」です。
    ※ Raspberry Pi + リレー + LE-53 での動作確認はまだ行っていません。

【安全上の注意】
    電磁ロックを Raspberry Pi の GPIO に直接つないではいけません。
    必ずリレーまたは MOSFET 回路を経由してください(README 参照)。
"""

import logging
import threading

from camera_rental import errors

logger = logging.getLogger(__name__)


class DemoLockController:
    """デモ用のロック(GPIO を一切操作しない)"""

    def __init__(self, should_fail=False):
        # should_fail=True にすると、解錠が「1回おきに」失敗する。
        #   1回目: 失敗 → 2回目(再試行): 成功 → 3回目: 失敗 ...
        # 解錠失敗画面から「再試行して成功する流れ」と
        # 「取り消す流れ」の両方を確認できるようにするためです。
        self.should_fail = should_fail
        self.is_ready = True
        self.not_ready_reason = ""
        self.attempt_count = 0
        self.unlock_count = 0

    def unlock(self, seconds):
        self.attempt_count += 1

        is_odd_attempt = self.attempt_count % 2 == 1
        if self.should_fail and is_odd_attempt:
            raise errors.UnlockError(detail="デモ: 解錠失敗をシミュレートしました")

        self.unlock_count += 1
        logger.info("[デモ] 電磁ロックを %s 秒間解錠したことにします(GPIO出力なし)", seconds)

    def close(self):
        logger.info("[デモ] 電磁ロックの終了処理(GPIO出力なし)")


class GpioLockController:
    """
    gpiozero を使って電磁ロック用のリレーを制御するクラス

    ※ 実装済み・実機未確認
    """

    def __init__(self, gpio_pin, active_high=True):
        self.gpio_pin = gpio_pin
        self.active_high = active_high

        self.is_ready = False
        self.not_ready_reason = ""

        # 解錠中に「○秒後に施錠へ戻す」ためのタイマー
        self._relock_timer = None

        # タイマーのスレッドと画面のスレッドから同時に触られないようにする鍵
        self._device_lock = threading.Lock()

        self._output_device = None
        self._setup_device()

    def _setup_device(self):
        """GPIO 出力を準備する(失敗しても例外は投げず、is_ready=False にする)"""
        try:
            # gpiozero は Raspberry Pi 上でのみ使うので、ここで読み込む
            # (Windows でデモ動作させるときに gpiozero がなくても起動できるように)
            from gpiozero import DigitalOutputDevice

            # initial_value=False : 起動直後は必ず「施錠」(リレーOFF)
            self._output_device = DigitalOutputDevice(
                self.gpio_pin,
                active_high=self.active_high,
                initial_value=False,
            )
        except Exception as error:
            # gpiozero が入っていない / GPIO が使えない / ピンが使用中 など
            self.not_ready_reason = f"{type(error).__name__}: {error}"
            logger.exception("GPIO %s の初期化に失敗しました", self.gpio_pin)
            return

        self.is_ready = True
        logger.info(
            "電磁ロック用 GPIO を準備しました: GPIO%s active_high=%s",
            self.gpio_pin,
            self.active_high,
        )

    def unlock(self, seconds):
        """
        指定秒数だけ解錠し、その後自動で施錠に戻す

        この関数はすぐに戻ります(画面を止めないため)。
        施錠へ戻す処理は、threading.Timer が別スレッドで行います。
        """
        if not self.is_ready:
            raise errors.UnlockError(detail=f"GPIO未初期化: {self.not_ready_reason}")

        try:
            with self._device_lock:
                # 前回のタイマーが残っていれば止める(連続で解錠した場合)
                if self._relock_timer is not None:
                    self._relock_timer.cancel()

                self._output_device.on()

                self._relock_timer = threading.Timer(seconds, self._relock)
                self._relock_timer.daemon = True
                self._relock_timer.start()
        except Exception as error:
            logger.exception("解錠に失敗しました")
            # 失敗時は念のため施錠側に戻しておく
            self._turn_off_safely()
            raise errors.UnlockError(detail=str(error)) from error

        logger.info("電磁ロックを解錠しました: %s 秒後に施錠します", seconds)

    def _relock(self):
        """タイマーから呼ばれる: 施錠に戻す"""
        with self._device_lock:
            self._turn_off_safely()
            self._relock_timer = None
        logger.info("電磁ロックを施錠に戻しました")

    def _turn_off_safely(self):
        """リレーを OFF(施錠)にする。ここでの失敗はログだけ残す"""
        if self._output_device is None:
            return
        try:
            self._output_device.off()
        except Exception:
            logger.exception("施錠への切り替えに失敗しました。配線と電源を確認してください")

    def close(self):
        """アプリ終了時: タイマーを止め、施錠状態にしてから GPIO を解放する"""
        with self._device_lock:
            if self._relock_timer is not None:
                self._relock_timer.cancel()
                self._relock_timer = None

            self._turn_off_safely()

            if self._output_device is not None:
                try:
                    self._output_device.close()
                except Exception:
                    logger.exception("GPIO の解放に失敗しました")
                self._output_device = None

        self.is_ready = False
        logger.info("電磁ロックの GPIO を解放しました")
