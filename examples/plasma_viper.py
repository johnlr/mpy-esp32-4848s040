"""Animated plasma in viper, at full 480x480 resolution.

The same picture and the same motion as ``plasma.py``, two changes:

**Full resolution.**  ``plasma.py`` evaluates the field once per 10x10 block
(48x48 samples) to keep the Python loop cheap; here every one of the 230400
pixels is computed, so the plasma is smooth instead of blocky.

**Viper, batched per frame.**  ``math.sin`` is not available to viper, so the
sine is a fixed-point lookup table and the whole frame - table lookups, colour
maths and the writes into the framebuffer - is a single viper call.  Against
the Python ``math.sin`` loop that is the difference between a slideshow and a
smooth animation.

    mpremote connect /dev/ttyUSB0 run examples/plasma_viper.py

The per-block version is ``examples/plasma.py``.

Ctrl-C stops it.  Only the driver is needed.
"""

import math
import time

import micropython

from array import array

from esp32_4848s040 import DPI

#: Sine lookup table size and its fixed-point scale.  ``SINE[i]`` holds
#: ``sin(2*pi*i/TBL)`` times ``SIN_SCALE``, so the table spans -SIN_SCALE to
#: +SIN_SCALE and is indexed by an angle in "table turns" (0..TBL-1).
TBL = 256
TBL_MASK = TBL - 1
SIN_SCALE = 1024

#: Table index per radian: an angle ``th`` maps to ``int(th * TBL/(2*pi))``.
TBL_2PI = TBL / (2 * math.pi)

#: Sine table in fixed point, biased into 0..2*SIN_SCALE so every entry is
#: non-negative.  ``ptr16`` loads zero-extend, so a negative ``array('h')``
#: entry reads back as a large positive - biasing keeps the reads exact, and
#: the bias is removed from the sum below.
SINE = array('H', [int(math.sin(2 * math.pi * i / TBL) * SIN_SCALE) + SIN_SCALE
                   for i in range(TBL)])

#: Colour lookup, indexed by ``v + 2048`` where ``v`` is the fixed-point sum
#: of the two sines (-2048..2048).  The plasma colour is a pure function of
#: ``v``, so it is precomputed once and the per-pixel work becomes a single
#: load instead of the red/green/blue arithmetic.
COLOUR = array('H', [0] * 4097)
for _v in range(-2048, 2049):
    _a = (_v + 2048) * 255 >> 12                    # red   = 255 * (v+2)/4
    _av = -_v if _v < 0 else _v
    _g = 255 - (255 * _av >> 11)                    # green = 255*(1-|2a-1|)
    _b = 255 - _a                                   # blue  = 255*(1-a)
    COLOUR[_v + 2048] = ((_a & 0xF8) << 8) | ((_g & 0xFC) << 3) | (_b >> 3)


def main():
    d = DPI(fbs=2)
    w = d.width
    h = d.height

    # Pixel -> table-index maps, computed once: the angle of pixel x is
    # (x/w)*2*pi, i.e. index (x*TBL)//w.  Doing this per pixel would mean a
    # division each; as bytes in a table they are a single load.
    ix = array('B', [(x * TBL) // w for x in range(w)])
    iy = array('B', [(y * TBL) // h for y in range(h)])

    # Per-x sine for the current frame's t, filled once and reused across all
    # rows: the x-sine does not depend on y, so this turns a per-pixel table
    # lookup and index calculation into a single load.
    sx = array('H', [0] * w)

    @micropython.viper
    def render(fb: ptr16, w: int, h: int, t_idx: int, t_idx_13: int,
               ix: ptr8, iy: ptr8, tbl: ptr16, lut: ptr16,
               sx: ptr16, tbl_mask: int):
        """Write one plasma frame into ``fb`` (w*h RGB565 words)."""
        for x in range(w):
            sx[x] = tbl[(ix[x] + t_idx) & tbl_mask]
        for y in range(h):
            sy = tbl[(iy[y] + t_idx_13) & tbl_mask]
            base = y * w
            for x in range(w):
                fb[base + x] = lut[sx[x] + sy]

    t0 = time.ticks_ms()
    frame = 0
    while True:
        # Ask for the drawing buffer every frame: with fbs=2 it alternates.
        fb = d.fb
        t = frame / 24.0
        t_idx = int(t * TBL_2PI) & TBL_MASK
        t_idx_13 = int(1.3 * t * TBL_2PI) & TBL_MASK
        render(fb, w, h, t_idx, t_idx_13, ix, iy, SINE, COLOUR, sx, TBL_MASK)
        d.show()
        frame += 1
        if frame % 120 == 0:
            el = time.ticks_diff(time.ticks_ms(), t0)
            print("plasma_viper: %d fps" % (120 * 1000 // el))
            t0 = time.ticks_ms()


if __name__ == "__main__":
    main()
