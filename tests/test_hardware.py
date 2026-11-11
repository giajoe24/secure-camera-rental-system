"""
ハードウェア処理のテスト(実機なし)

    ・デモ用カードリーダー / デモ用ロック
    ・NfcCardReader      : 偽物の nfc モジュールを使って、処理の流れだけ確認
    ・GpioLockController : gpiozero の MockFactory(仮想ピン)で確認
                           (gpiozero が入っていない環境ではスキップ)

※ ここで確認できるのは「プログラムの流れ」までです。
   RC-S380・リレー・電磁ロックの実機動作は確認できません。
"""

import sys
import threading
import time
import types
import unittest

from camera_rental import errors
from camera_rental.hardware.card_reader import DemoCardReader, NfcCardReader
from camera_rental.hardware.lock_controller import DemoLockController, GpioLockController
from camera_rental.hardware.lock_sensor import (
    LOCK_STATE_LOCKED,
    LOCK_STATE_UNKNOWN,
    LOCK_STATE_UNLOCKED,
    DemoLockSensor,
    GpioLockSensor,
    NoLockSensor,
)


class DemoCardReaderTest(unittest.TestCase):

    def test_simulated_touch_returns_card_id(self):
        reader = DemoCardReader(demo_cards=[("デモ", "DEMO1")])
        cancel_event = threading.Event()

        # 0.2秒後に別スレッドから「かざす」
        timer = threading.Timer(0.2, reader.simulate_touch, args=["DEMO1"])
        timer.start()

        card_id = reader.read_card(timeout_seconds=3, cancel_event=cancel_event)
        self.assertEqual(card_id, "DEMO1")

    def test_timeout_returns_none(self):
        reader = DemoCardReader(demo_cards=[])
        card_id = reader.read_card(timeout_seconds=0.3, cancel_event=threading.Event())
        self.assertIsNone(card_id)

    def test_cancel_returns_none(self):
        reader = DemoCardReader(demo_cards=[])
        cancel_event = threading.Event()
        threading.Timer(0.2, cancel_event.set).start()

        start_time = time.monotonic()
        card_id = reader.read_card(timeout_seconds=10, cancel_event=cancel_event)

        self.assertIsNone(card_id)
        self.assertLess(time.monotonic() - start_time, 2)


class DemoLockControllerTest(unittest.TestCase):

    def test_unlock_succeeds(self):
        lock = DemoLockController()
        lock.unlock(10)
        self.assertEqual(lock.unlock_count, 1)

    def test_simulated_failure_alternates(self):
        lock = DemoLockController(should_fail=True)
        with self.assertRaises(errors.UnlockError):
            lock.unlock(10)
        lock.unlock(10)
        with self.assertRaises(errors.UnlockError):
            lock.unlock(10)


# --------------------------------------------------
# nfcpy の偽物
# --------------------------------------------------

class FakeTag:
    type = "Type3Tag"

    def __init__(self, identifier):
        self.identifier = identifier


class FakeFrontend:
    """nfc.ContactlessFrontend の代わり"""

    connect_result = None
    open_error = None
    closed_count = 0

    def __init__(self, path):
        if FakeFrontend.open_error is not None:
            raise FakeFrontend.open_error

    def __bool__(self):
        return True

    def connect(self, rdwr, terminate):
        result = FakeFrontend.connect_result
        if isinstance(result, FakeTag):
            # 本物と同じく on-connect を呼び、False が返れば Tag を返す
            if rdwr["on-connect"](result):
                return True
            return result
        if result is None:
            # 本物と同じく terminate が True になるまで待つ
            while not terminate():
                time.sleep(0.05)
            return None
        return result

    def close(self):
        FakeFrontend.closed_count += 1


class NfcCardReaderTest(unittest.TestCase):
    """偽物の nfc モジュールで、NfcCardReader の処理の流れを確認する"""

    def setUp(self):
        self.original_nfc_module = sys.modules.get("nfc")
        fake_nfc_module = types.ModuleType("nfc")
        fake_nfc_module.ContactlessFrontend = FakeFrontend
        sys.modules["nfc"] = fake_nfc_module

        FakeFrontend.connect_result = None
        FakeFrontend.open_error = None
        FakeFrontend.closed_count = 0

    def tearDown(self):
        if self.original_nfc_module is None:
            del sys.modules["nfc"]
        else:
            sys.modules["nfc"] = self.original_nfc_module

    def test_reads_felica_identifier(self):
        FakeFrontend.connect_result = FakeTag(bytes.fromhex("012e4caa12345678"))
        reader = NfcCardReader()

        card_id = reader.read_card(timeout_seconds=1, cancel_event=threading.Event())

        self.assertEqual(card_id, "012E4CAA12345678")
        self.assertEqual(FakeFrontend.closed_count, 1)

    def test_reader_not_connected(self):
        FakeFrontend.open_error = OSError(19, "No such device")
        reader = NfcCardReader()
        with self.assertRaises(errors.CardReaderNotConnectedError):
            reader.read_card(timeout_seconds=1, cancel_event=threading.Event())

    def test_timeout_returns_none_and_closes(self):
        reader = NfcCardReader()
        card_id = reader.read_card(timeout_seconds=0.3, cancel_event=threading.Event())
        self.assertIsNone(card_id)
        self.assertEqual(FakeFrontend.closed_count, 1)

    def test_communication_error(self):
        FakeFrontend.connect_result = False
        reader = NfcCardReader()
        with self.assertRaises(errors.CardReadError):
            reader.read_card(timeout_seconds=1, cancel_event=threading.Event())
        self.assertEqual(FakeFrontend.closed_count, 1)


# --------------------------------------------------
# gpiozero の仮想ピン
# --------------------------------------------------

def gpiozero_mock_available():
    try:
        import gpiozero  # noqa: F401
        from gpiozero.pins.mock import MockFactory  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(gpiozero_mock_available(), "gpiozero が入っていないためスキップ")
class GpioLockControllerMockTest(unittest.TestCase):
    """gpiozero の MockFactory で GPIO 出力の動きを確認する(実機ではない)"""

    def setUp(self):
        from gpiozero import Device
        from gpiozero.pins.mock import MockFactory

        self.original_factory = Device.pin_factory
        Device.pin_factory = MockFactory()
        self.pin_factory = Device.pin_factory

    def tearDown(self):
        from gpiozero import Device

        Device.pin_factory.reset()
        Device.pin_factory = self.original_factory

    def test_starts_locked(self):
        lock = GpioLockController(gpio_pin=18, active_high=True)
        self.assertTrue(lock.is_ready)
        self.assertEqual(self.pin_factory.pin(18).state, 0)
        lock.close()

    def test_unlock_then_relock_active_high(self):
        lock = GpioLockController(gpio_pin=18, active_high=True)
        lock.unlock(0.3)
        self.assertEqual(self.pin_factory.pin(18).state, 1)

        time.sleep(0.6)
        self.assertEqual(self.pin_factory.pin(18).state, 0)
        lock.close()

    def test_unlock_active_low(self):
        lock = GpioLockController(gpio_pin=18, active_high=False)
        # active low: 施錠中は High、解錠中は Low
        self.assertEqual(self.pin_factory.pin(18).state, 1)
        lock.unlock(0.3)
        self.assertEqual(self.pin_factory.pin(18).state, 0)
        time.sleep(0.6)
        self.assertEqual(self.pin_factory.pin(18).state, 1)
        lock.close()

    def test_close_while_unlocked_relocks(self):
        lock = GpioLockController(gpio_pin=18, active_high=True)
        lock.unlock(10)
        lock.close()
        self.assertFalse(lock.is_ready)

    def test_invalid_pin_is_not_ready(self):
        lock = GpioLockController(gpio_pin=999, active_high=True)
        self.assertFalse(lock.is_ready)
        self.assertNotEqual(lock.not_ready_reason, "")
        with self.assertRaises(errors.UnlockError):
            lock.unlock(1)


class LockSensorWithoutGpioTest(unittest.TestCase):

    def test_no_sensor_is_unknown(self):
        sensor = NoLockSensor()
        self.assertFalse(sensor.is_available)
        self.assertEqual(sensor.read_state(), LOCK_STATE_UNKNOWN)

    def test_demo_sensor_open_and_close(self):
        sensor = DemoLockSensor()
        self.assertEqual(sensor.read_state(), LOCK_STATE_LOCKED)
        sensor.open_door()
        self.assertEqual(sensor.read_state(), LOCK_STATE_UNLOCKED)
        sensor.close_door()
        self.assertEqual(sensor.read_state(), LOCK_STATE_LOCKED)


@unittest.skipUnless(gpiozero_mock_available(), "gpiozero が入っていないためスキップ")
class GpioLockSensorMockTest(unittest.TestCase):
    """gpiozero の MockFactory でカムスイッチの読み取りを確認する(実機ではない)"""

    def setUp(self):
        from gpiozero import Device
        from gpiozero.pins.mock import MockFactory

        self.original_factory = Device.pin_factory
        Device.pin_factory = MockFactory()
        self.pin_factory = Device.pin_factory

    def tearDown(self):
        from gpiozero import Device

        Device.pin_factory.reset()
        Device.pin_factory = self.original_factory

    def test_pull_up_contact_closed_when_locked(self):
        """GPIO と GND の間のスイッチ: 施錠中は Low(接点が閉じる)"""
        sensor = GpioLockSensor(gpio_pin=23, pull_up=True, locked_when_closed=True, bounce_seconds=None)
        pin = self.pin_factory.pin(23)

        pin.drive_low()
        self.assertEqual(sensor.read_state(), LOCK_STATE_LOCKED)

        pin.drive_high()
        self.assertEqual(sensor.read_state(), LOCK_STATE_UNLOCKED)
        sensor.close()

    def test_contact_open_when_locked(self):
        """NC 接点を使う配線: 施錠中は接点が開く(High)"""
        sensor = GpioLockSensor(gpio_pin=23, pull_up=True, locked_when_closed=False, bounce_seconds=None)
        pin = self.pin_factory.pin(23)

        pin.drive_high()
        self.assertEqual(sensor.read_state(), LOCK_STATE_LOCKED)

        pin.drive_low()
        self.assertEqual(sensor.read_state(), LOCK_STATE_UNLOCKED)
        sensor.close()

    def test_close_makes_state_unknown(self):
        sensor = GpioLockSensor(gpio_pin=23, bounce_seconds=None)
        sensor.close()
        self.assertFalse(sensor.is_available)
        self.assertEqual(sensor.read_state(), LOCK_STATE_UNKNOWN)

    def test_invalid_pin_is_not_available(self):
        """初期化に失敗しても例外は出さず「使えない」になる(貸出・返却を止めない)"""
        sensor = GpioLockSensor(gpio_pin=999)
        self.assertFalse(sensor.is_available)
        self.assertNotEqual(sensor.not_available_reason, "")
        self.assertEqual(sensor.read_state(), LOCK_STATE_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
