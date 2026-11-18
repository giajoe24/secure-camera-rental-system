# 電磁ロックをパルスで外せるか試す(パルスは config.py の UNLOCK_PULSE_...)
#   python check_lock_pulse.py

import time

import config

print(f"GPIO{config.LOCK_GPIO_PIN} に ON {config.UNLOCK_PULSE_ON_SECONDS * 1000}ms × {config.UNLOCK_PULSE_COUNT} 回を出します。")
if input("よければ y を入力: ").strip() != "y":
    raise SystemExit

try:
    from gpiozero import DigitalOutputDevice
    output = DigitalOutputDevice(config.LOCK_GPIO_PIN, active_high=config.LOCK_ACTIVE_HIGH, initial_value=False)
except Exception as e:
    print("GPIO が使えません:", e)
    raise SystemExit(1)

try:
    for i in range(config.UNLOCK_PULSE_COUNT):
        if i > 0:
            time.sleep(config.UNLOCK_PULSE_OFF_SECONDS)
        output.on()
        time.sleep(config.UNLOCK_PULSE_ON_SECONDS)
        output.off()
        print(f"{i + 1} 回目")
finally:
    output.off()
    output.close()

print("終わり。ラッチが外れたか確認してください。")
