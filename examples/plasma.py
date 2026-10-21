"""Animated plasma, drawn into the buffer that is off screen.

``DPI(fbs=2)`` double buffers: ``show()`` hands the DMA the frame just drawn
and moves drawing to the other buffer, so a frame is never caught half
finished (see the double buffering chapter of the README).  The field is
evaluated once per 10x10 block rather than per pixel - 2304 ``fill_rect()``
calls a frame instead of a 230400-iteration Python loop, which is the
difference between a smooth animation and a slideshow.

    mpremote connect /dev/ttyUSB0 run examples/plasma.py

Ctrl-C stops it.  Only the driver is needed.
"""

import math

from esp32_4848s040 import DPI

#: Pixels per side of one block (480 / 10 = 48 blocks across).  Smaller is
#: smoother and slower: this is the knob to turn if it stutters.
BLOCK = 10


def rgb565(r, g, b):
    """Pack 0..255 channels into an RGB565 word, the panel's pixel format."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def main():
    d = DPI(fbs=2)
    nx = d.width // BLOCK
    ny = d.height // BLOCK
    sin = math.sin                    # bound once; two calls per block
    tau = math.pi * 2
    frame = 0

    while True:
        # Ask for the drawing buffer every frame: with fbs=2 it alternates.
        fb = d.fbuf
        t = frame / 24.0
        for by in range(ny):
            yv = by / ny * tau
            for bx in range(nx):
                xv = bx / nx * tau
                v = sin(xv + t) + sin(yv + t * 1.3)     # roughly -2..2
                a = (v + 2) / 4                          # 0..1
                colour = rgb565(int(255 * a),
                                int(255 * (1 - abs(2 * a - 1))),
                                int(255 * (1 - a)))
                fb.fill_rect(bx * BLOCK, by * BLOCK, BLOCK, BLOCK, colour)
        d.show()
        frame += 1


if __name__ == "__main__":
    main()
