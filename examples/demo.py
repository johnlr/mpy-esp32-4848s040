"""Pure-MicroPython RGB panel on the Guition ESP32-S3-4848S040.

Copy ``esp32_4848s040.py`` and this file to the board and it runs at boot::

    mpremote connect /dev/ttyUSB0 cp esp32_4848s040.py :esp32_4848s040.py
    mpremote connect /dev/ttyUSB0 cp examples/demo.py :main.py

Or drive it interactively::

    >>> import demo; demo.demo()
"""

import time


def demo(seconds=6):
    import esp32_4848s040 as lcd

    print("creating panel...")
    d = lcd.DPI()

    # 1. solid primaries -------------------------------------------------
    for name, colour in (("red", 0xF800), ("green", 0x07E0),
                         ("blue", 0x001F), ("white", 0xFFFF),
                         ("black", 0x0000)):
        print("fill", name)
        d.fill(colour)
        d.show()
        time.sleep_ms(400)

    # 2. RGB colour bars -------------------------------------------------
    print("test_pattern")
    d.test_pattern()
    d.show()
    time.sleep_ms(1000)

    # 3. framebuf text ---------------------------------------------------
    fb = d.fbuf
    fb.fill(0x0010)
    fb.text("ESP32-S3", 12, 12, 0x07E0)
    fb.text("ST7701 480x480", 12, 32, 0xFFFF)
    fb.text("MicroPython", 12, 52, 0xF800)
    fb.text("no custom C", 12, 72, 0x07FF)
    fb.rect(0, 0, 480, 480, 0x07FF)
    d.show()
    print("done")


if __name__ == "__main__":
    demo()
