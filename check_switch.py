# LE-53 のマイクロスイッチの確認(Ctrl+C で終了)
#   python check_switch.py
# つなぎ方: COM → GND、NO → GPIO(外付け 10kΩ で 3.3V にプルアップ)。施錠中だけ導通する。

import time

import config

try:
    from gpiozero import Button
    switch = Button(config.LOCK_SWITCH_GPIO_PIN, pull_up=None, active_state=False, bounce_time=0.05)
except Exception as e:
    print("GPIO が使えません:", e)
    raise SystemExit(1)

print(f"GPIO{config.LOCK_SWITCH_GPIO_PIN} を見ています(Ctrl+C で終了)")
last = None
try:
    while True:
        if switch.is_pressed:
            state = "施錠中"
        else:
            state = "解錠中"
        if state != last:
            print(time.strftime("%H:%M:%S"), state)
            last = state
        time.sleep(0.05)
except KeyboardInterrupt:
    pass
finally:
    switch.close()
