"""
Lava lamp simulator (viper, driver-only)

A tiny thermal-convection model drives three metaballs, so they behave like
the wax in a real lamp: they sit on the bulb at the bottom, get heated, become
buoyant and rise, cool in the upper fluid, get dense, and sink back down to be
reheated. The 480x480 metaball field is drawn by a single
``@micropython.viper`` call with a division-free falloff.

The physics (per blob) is:
    heat  -> relaxes toward the local ambient temperature, which is a steady
             gradient (cold at the top, hot at the bottom), plus extra heating
             while resting on the bulb.
    force -> buoyancy proportional to (heat - NEUTRAL): hotter than neutral
             rises, cooler sinks. A little drag gives it viscosity and
             momentum, so blobs overshoot and sweep the full height instead of
             parking at the midpoint.

Needs nothing but ``esp32_4848s040.py`` and built-in MicroPython modules.

Run on the board:
    mpremote connect /dev/ttyUSB0 run examples/lavalamp_viper.py

Ctrl-C to stop.
"""

import random
import time
from array import array
from micropython import const
from esp32_4848s040 import DPI

WIDTH = const(480)
HEIGHT = const(480)
NBLOBS = const(3)

# ---------------------------------------------------------------------
# metaball field (viper) - per-blob radii in pixels
# ---------------------------------------------------------------------
R0 = const(110)
R1 = const(88)
R2 = const(70)
A0 = const(R0 * R0)
A1 = const(R1 * R1)
A2 = const(R2 * R2)

# Below THRESH the pixel is background; above it the sum maps into the palette
# with a right shift (bigger SHIFT = a longer, softer gradient).
THRESH = const(1000)
SHIFT = const(10)

# Warm glow: black -> deep red -> orange -> yellow -> white.
_PALETTE = array('H', (
    0x0000, 0x1000, 0x2800, 0x4800, 0x7000, 0xA800, 0xD000, 0xF800,
    0xF820, 0xF860, 0xF8C0, 0xF920, 0xF980, 0xFA00, 0xFA60, 0xFB00,
    0xFB40, 0xFB80, 0xFBFF, 0xFFFF,
))


@micropython.viper
def render(fb_ptr: ptr16, cx0: int, cy0: int, cx1: int, cy1: int,
           cx2: int, cy2: int):
    """Render one 480x480 lava frame (RGB565) into ``fb_ptr``.

    Blob centres arrive in pixel coordinates. The frame is clipped to the
    bounding box of all three blobs, so the empty background is filled with a
    cheap run of zeros and the per-pixel field maths only runs where a blob
    can reach.
    """
    pal = ptr16(_PALETTE)

    xmin = cx0 - R0
    if cx1 - R1 < xmin:
        xmin = cx1 - R1
    if cx2 - R2 < xmin:
        xmin = cx2 - R2
    if xmin < 0:
        xmin = 0
    xmax = cx0 + R0
    if cx1 + R1 > xmax:
        xmax = cx1 + R1
    if cx2 + R2 > xmax:
        xmax = cx2 + R2
    if xmax > WIDTH - 1:
        xmax = WIDTH - 1

    idx = 0
    y = 0
    while y < HEIGHT:
        dy = y
        ty0 = dy - cy0
        if ty0 < 0:
            ty0 = -ty0
        ty1 = dy - cy1
        if ty1 < 0:
            ty1 = -ty1
        ty2 = dy - cy2
        if ty2 < 0:
            ty2 = -ty2

        # left background
        x = 0
        while x < xmin:
            fb_ptr[idx] = 0x0000
            idx += 1
            x += 1

        if ty0 >= R0 and ty1 >= R1 and ty2 >= R2:
            # this row is entirely background
            row_end = idx + (WIDTH - xmin)
            while idx < row_end:
                fb_ptr[idx] = 0x0000
                idx += 1
            y += 1
            continue

        while x <= xmax:
            dx = x
            s = 0
            if ty0 < R0:
                tx = dx - cx0
                if tx < 0:
                    tx = -tx
                if tx < R0:
                    d = tx * tx + ty0 * ty0
                    if d < A0:
                        s += A0 - d
            if ty1 < R1:
                tx = dx - cx1
                if tx < 0:
                    tx = -tx
                if tx < R1:
                    d = tx * tx + ty1 * ty1
                    if d < A1:
                        s += A1 - d
            if ty2 < R2:
                tx = dx - cx2
                if tx < 0:
                    tx = -tx
                if tx < R2:
                    d = tx * tx + ty2 * ty2
                    if d < A2:
                        s += A2 - d

            if s < THRESH:
                fb_ptr[idx] = 0x0000
            else:
                p = (s - THRESH) >> SHIFT
                if p > 19:
                    p = 19
                fb_ptr[idx] = int(pal[p])

            idx += 1
            x += 1

        # right background
        while x < WIDTH:
            fb_ptr[idx] = 0x0000
            idx += 1
            x += 1

        y += 1


# ---------------------------------------------------------------------
# thermal convection physics (cheap: only NBLOBS blobs, plain Python)
# ---------------------------------------------------------------------
EXCHANGE = 0.004     # heat relaxes toward ambient this fast (slow = lots of lag)
BUOY      = 1.20    # buoyancy accel per unit heat above/below neutral
NEUTRAL   = 0.50    # heat at which a blob is neutrally buoyant
DRAG      = 0.972   # fluid viscosity: velocity retained each frame
JIT       = 0.10    # lateral wander - the only horizontal drive. Kept small so
                    # motion stays vertical (heat up / cool down). No centre
                    # force: with DRAG=0.972 the velocity gain is ~1/(1-DRAG)
                    # ~ 35x, so even a weak pull toward a common point both
                    # swamps buoyancy (side-to-side darting) and funnels every
                    # blob into one column. Walls keep them in bounds instead.
BOUNCE    = 0.35    # energy kept when a blob hits a wall
BOTTOM_HEAT = 0.008 # extra heating while resting on the bulb
WALL = const(48)    # keep blobs this far from the edges

# Blob state, kept in parallel lists (cheaper than objects in MicroPython).
_bx = [120.0, 240.0, 360.0]
_by = [90.0, 200.0, 330.0]
_bvx = [0.0] * NBLOBS
_bvy = [0.0] * NBLOBS
# start some warm and some cool so they immediately split up
_bheat = [0.42, 0.50, 0.58]


def _step():
    """Advance every blob by one frame of the convection model."""
    for i in range(NBLOBS):
        y = _by[i]

        # 1. heat tracks the local ambient (steady gradient: hot bottom, cold
        #    top). Blobs resting on the bulb get extra heat from the lamp.
        _bheat[i] += (y / HEIGHT - _bheat[i]) * EXCHANGE
        if y > HEIGHT - 90:
            _bheat[i] += BOTTOM_HEAT * (y - (HEIGHT - 90)) / 90
        if _bheat[i] > 1.0:
            _bheat[i] = 1.0
        elif _bheat[i] < 0.0:
            _bheat[i] = 0.0

        # 2. buoyancy drives the vertical motion: hot rises (screen up is -y),
        #    cool sinks. Drag gives the fluid viscosity so blobs carry momentum
        #    and sweep the full height. Horizontal is only a small jitter.
        ay = -BUOY * (_bheat[i] - NEUTRAL)
        ax = (random.random() - 0.5) * JIT
        _bvy[i] = (_bvy[i] + ay) * DRAG
        _bvx[i] = (_bvx[i] + ax) * DRAG

        # 3. integrate
        _bx[i] += _bvx[i]
        _by[i] += _bvy[i]

        # 4. walls
        if _by[i] < WALL:
            _by[i] = WALL
            _bvy[i] = -_bvy[i] * BOUNCE
        elif _by[i] > HEIGHT - WALL:
            _by[i] = HEIGHT - WALL
            _bvy[i] = -_bvy[i] * BOUNCE
        if _bx[i] < WALL:
            _bx[i] = WALL
            _bvx[i] = -_bvx[i] * BOUNCE
        elif _bx[i] > WIDTH - WALL:
            _bx[i] = WIDTH - WALL
            _bvx[i] = -_bvx[i] * BOUNCE


def main():
    d = DPI(fbs=2)
    print("Lava lamp (viper) running. Ctrl-C to stop.")
    try:
        while True:
            _step()
            fb = d.next_fb()
            render(fb,
                   int(_bx[0]), int(_by[0]),
                   int(_bx[1]), int(_by[1]),
                   int(_bx[2]), int(_by[2]))
            d.show()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
