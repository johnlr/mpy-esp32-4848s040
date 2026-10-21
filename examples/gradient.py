"""Paint a full-screen colour gradient the fast way.

Computed a pixel at a time in Python, this frame would take a second or more
(see the performance table in the README).  It is drawn as a grid of solid
rectangles instead: 30x30 blocks of 16x16 pixels, each filled with one
``framebuf.fill_rect()``.  That is 900 C calls for the whole screen.

    mpremote connect /dev/ttyUSB0 run examples/gradient.py

Only the driver is needed.
"""

import time

from esp32_4848s040 import DPI

#: Pixels per side of one block.  The grid is width/BLOCK by height/BLOCK.
BLOCK = 16


def rgb565(r, g, b):
    """Pack 0..255 channels into an RGB565 word, the panel's pixel format."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def main():
    d = DPI()
    fb = d.fbuf

    nx = d.width // BLOCK
    ny = d.height // BLOCK

    t0 = time.ticks_ms()
    for by in range(ny):
        for bx in range(nx):
            # Two independent ramps: the blue/red axis runs left to right and
            # the green axis top to bottom, so the corners are pure red,
            # blue, yellow and cyan.
            fx = (bx * 255) // (nx - 1)
            fy = (by * 255) // (ny - 1)
            colour = rgb565(255 - fx, fy, fx)
            fb.fill_rect(bx * BLOCK, by * BLOCK, BLOCK, BLOCK, colour)
    d.show()
    print("gradient: %d blocks in %d ms"
          % (nx * ny, time.ticks_diff(time.ticks_ms(), t0)))


if __name__ == "__main__":
    main()
