"""
電磁ロックの施錠状態センサー(LE-53 のカムスイッチ)

タキゲン LE-53 には「カムスイッチ」が付いていて、
製品ページには「カムが施錠状態のときカムスイッチが ON」と書かれています。
スナッチロックは「扉を押して閉めると自動で施錠される」仕組みなので、
カムスイッチが ON = 扉が閉まって施錠されている、と判断できます。

    ・NoLockSensor   : センサーを使わない(初期設定)
    ・DemoLockSensor : デモ用(画面のボタンで扉の開け閉めを再現する)
    ・GpioLockSensor : 実機用(gpiozero でカムスイッチの ON/OFF を読む)

どれも次のメソッドを持っています。

    is_available  : センサーが使えるか
    read_state()  : LOCK_STATE_LOCKED / LOCK_STATE_UNLOCKED / LOCK_STATE_UNKNOWN
    close()       : 終了処理

【センサーは補助の機能です】
    センサーが使えなくても、貸出・返却は止めません。
    (センサーの故障で、カメラを借りられない・返せない状態にしないため)
    状態が分からないときは LOCK_STATE_UNKNOWN を返し、画面では何も言いません。

【実機の状態】
    GpioLockSensor は「実装済み・実機未確認」です。
    カムスイッチの接点形式(NO/NC)・定格・線の色は公開ページでは確認できていません。
    仕様書で確認してから、config.py の LOCK_SENSOR_* を設定してください。
"""

import logging

logger = logging.getLogger(__name__)


LOCK_STATE_LOCKED = "locked"
LOCK_STATE_UNLOCKED = "unlocked"
LOCK_STATE_UNKNOWN = "unknown"


class NoLockSensor:
    """センサーを使わない場合(状態はいつも「分からない」)"""

    is_available = False
    not_available_reason = "センサーを使わない設定です"

    def read_state(self):
        return LOCK_STATE_UNKNOWN

    def close(self):
        pass


class DemoLockSensor:
    """
    デモ用のセンサー

    画面のデモボタンから open_door() / close_door() を呼んで、
    扉の開け閉めを再現します。最初は「閉まって施錠されている」状態です。
    """

    is_available = True
    not_available_reason = ""

    def __init__(self):
        self.is_locked = True

    def open_door(self):
        self.is_locked = False
        logger.info("[デモ] 扉を開けたことにします")

    def close_door(self):
        self.is_locked = True
        logger.info("[デモ] 扉を閉めたことにします")

    def read_state(self):
        return LOCK_STATE_LOCKED if self.is_locked else LOCK_STATE_UNLOCKED

    def close(self):
        pass


class GpioLockSensor:
    """
    gpiozero でカムスイッチの状態を読むクラス

    配線の例(locked_when_closed=True、pull_up=True の場合):
        GPIO ── カムスイッチ(施錠時に閉じる接点) ── GND
        内部プルアップを使うので、施錠中は Low、解錠中は High になります。

    ※ 実装済み・実機未確認
    """

    def __init__(self, gpio_pin, pull_up=True, locked_when_closed=True, bounce_seconds=0.05):
        self.gpio_pin = gpio_pin
        self.pull_up = pull_up

        # True : 施錠中にスイッチの接点が閉じる(NO 接点を使う配線)
        # False: 施錠中にスイッチの接点が開く(NC 接点を使う配線)
        self.locked_when_closed = locked_when_closed

        self.is_available = False
        self.not_available_reason = ""
        self._input_device = None

        try:
            # gpiozero は Raspberry Pi 上でのみ使うので、ここで読み込む
            from gpiozero import Button

            # Button の is_pressed は「接点が閉じている」を意味します
            # (pull_up=True なら Low、pull_up=False なら High のとき True)
            self._input_device = Button(gpio_pin, pull_up=pull_up, bounce_time=bounce_seconds)
        except Exception as error:
            self.not_available_reason = f"{type(error).__name__}: {error}"
            logger.exception("施錠センサー GPIO %s の初期化に失敗しました(貸出・返却は続けます)", gpio_pin)
            return

        self.is_available = True
        logger.info(
            "施錠センサーを準備しました: GPIO%s pull_up=%s 施錠時に接点が閉じる=%s",
            gpio_pin,
            pull_up,
            locked_when_closed,
        )

    def read_state(self):
        if not self.is_available or self._input_device is None:
            return LOCK_STATE_UNKNOWN
        try:
            contact_is_closed = self._input_device.is_pressed
        except Exception:
            logger.exception("施錠センサーを読めませんでした")
            return LOCK_STATE_UNKNOWN

        is_locked = contact_is_closed == self.locked_when_closed
        return LOCK_STATE_LOCKED if is_locked else LOCK_STATE_UNLOCKED

    def close(self):
        if self._input_device is not None:
            try:
                self._input_device.close()
            except Exception:
                logger.exception("施錠センサーの GPIO の解放に失敗しました")
            self._input_device = None
        self.is_available = False
