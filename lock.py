# 電磁ロック(LE-53)の制御
# GPIO で MOSFET を ON/OFF する。ロックを GPIO に直接つながないこと。
# 解錠は短いパルスを出すだけ(LE-53 は一度外れれば、扉を閉めると勝手にロックされる)

import logging
import time

import config

log = logging.getLogger(__name__)


class LockError(Exception):
    pass


class GpioLock:
    def __init__(self, pin, active_high, switch_pin):
        self.device = None
        self.switch = None
        self.ready = False
        self.error = ""

        try:
            from gpiozero import Button, DigitalOutputDevice
            self.device = DigitalOutputDevice(pin, active_high=active_high, initial_value=False)
            self.ready = True
        except Exception as e:
            self.error = str(e)
            log.exception("GPIO%s が使えません", pin)
            return

        try:
            # マイクロスイッチ(NO)。施錠中だけ GND とつながる(外付け 10kΩ でプルアップ)
            self.switch = Button(switch_pin, pull_up=None, active_state=False, bounce_time=0.05)
        except Exception:
            # スイッチがなくても解錠はできるので続ける
            log.exception("マイクロスイッチ(GPIO%s)が使えません", switch_pin)

    def is_locked(self):
        # 施錠中なら True。スイッチが使えないときは None
        if self.switch is None:
            return None
        return self.switch.is_pressed

    def open(self):
        if not self.ready:
            raise LockError(self.error)

        try:
            for i in range(config.UNLOCK_PULSE_COUNT):
                if i > 0:
                    time.sleep(config.UNLOCK_PULSE_OFF_SECONDS)
                self.device.on()
                time.sleep(config.UNLOCK_PULSE_ON_SECONDS)
                self.device.off()
        except Exception as e:
            self.device.off()
            raise LockError(str(e))

        log.info("解錠パルスを %s 回出しました", config.UNLOCK_PULSE_COUNT)

    def close(self):
        if self.device is not None:
            self.device.off()
            self.device.close()
        if self.switch is not None:
            self.switch.close()
