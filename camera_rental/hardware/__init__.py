"""
ハードウェア(カードリーダー・電磁ロック)の準備

設定(config)の DEMO_MODE を見て、デモ用か実機用かを選びます。
GUI や貸出処理はここで作られた部品を受け取るだけで、
「デモかどうか」を意識しなくて済むようにしています。
"""

from camera_rental.hardware.card_reader import DemoCardReader, NfcCardReader
from camera_rental.hardware.lock_controller import DemoLockController, GpioLockController


def create_card_reader(config, demo_mode):
    """設定に合わせてカードリーダーを作る"""
    if demo_mode:
        demo_cards = []
        for employee_number, name, card_id in config.DEMO_USERS:
            demo_cards.append((name, card_id))
        demo_cards.append(("未登録カード", config.DEMO_UNREGISTERED_CARD_ID))
        return DemoCardReader(demo_cards)

    return NfcCardReader(
        device_path=config.CARD_READER_DEVICE,
        targets=config.CARD_TARGETS,
    )


def create_lock_controller(config, demo_mode):
    """設定に合わせて電磁ロックの制御部品を作る"""
    if demo_mode:
        return DemoLockController(should_fail=config.DEMO_SIMULATE_UNLOCK_FAILURE)

    return GpioLockController(
        gpio_pin=config.LOCK_GPIO_PIN,
        active_high=config.LOCK_ACTIVE_HIGH,
    )
