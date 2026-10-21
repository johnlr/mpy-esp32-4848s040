"""Render the Mandelbrot set in viper, to show what it buys.

This is the same picture as ``mandelbrot.py``, but the escape-time loop is
compiled to machine code by MicroPython's ``@micropython.viper`` instead of
being interpreted.  Run them back to back and compare the timings::

    mpremote connect /dev/ttyUSB0 run examples/mandelbrot.py
    mpremote connect /dev/ttyUSB0 run examples/mandelbrot_viper.py

The pure Python version is ``examples/mandelbrot.py``.

Two things make it fast, and both are worth understanding.

**Fixed point, not float.**  Viper has no native float type in this build:
``def f(x: float)`` is rejected with ``ViperTypeError: unknown type 'float'``,
and passing floats as ``object`` boxes them again, so a "float" viper version
is no faster than pure Python - on this device it is measurably *slower*.  The
escape loop is therefore done in Q13.13 fixed point, which viper maps to
single 32-bit instructions.  The shift must stay small: ``1 << 30`` is already
a Python bignum viper cannot use in arithmetic, and ``zr * zr`` overflows a
32-bit register once the scale passes 2^14.  Shift 13 is the largest value
that stays inside 32 bits for the whole image; it agrees with the float
version to within one iteration, differing only on about 1% of boundary
pixels, which is invisible.

**One call for the whole image.**  Calling a viper function per pixel costs
~10 us each, so a 480x480 image spent ~2.4 s just on call overhead before any
math.  Here the entire render - coordinate generation, escape loop and the
write into the framebuffer - is a single viper call, so that overhead is paid
once.  The framebuffer is handed over as a ``ptr16`` and written directly,
which also removes the per-pixel ``fill_rect`` dispatch.  Against the
per-pixel viper version this is another ~8x; overall roughly 140x the pure
Python original.

Only the driver is needed.
"""

import time

import micropython

from esp32_4848s040 import DPI

#: Pixels per side of one sample (1 = the full 480x480), and the iteration cap.
#: The cap is the whole cost of the picture: every pixel runs until it escapes,
#: so the edge, where escape takes longest, dominates the render.  It barely
#: moves the time, because almost all pixels escape within ten iterations.
BLOCK = 1
MAX_ITER = 50

#: The region of the complex plane to draw, as (min, max) on each axis.
#: These are the values the original float version uses.
RE_MIN, RE_MAX = -2.35, 0.85
IM_MIN, IM_MAX = -1.3, 1.3

#: The fixed-point scale, 2**13.  Coordinates are held as integers scaled by
#: this, and the products are shifted back down by the same amount.
SCALE = 1 << 13

#: Per-axis integer step constants, so the pixel-to-complex mapping is pure
#: integer arithmetic inside viper (``cr = B_RE + ((2*x+1)*A_RE) // (2*W)``).
A_RE = int((RE_MAX - RE_MIN) * SCALE)
B_RE = int(RE_MIN * SCALE)
A_IM = int((IM_MAX - IM_MIN) * SCALE)
B_IM = int(IM_MIN * SCALE)


def main():
    d = DPI()
    fb = d.fb                       # the framebuffer bytearray, RGB565
    w = d.width
    h = d.height

    @micropython.viper
    def render(fb: ptr16, w: int, h: int, max_iter: int,
               a_re: int, b_re: int, a_im: int, b_im: int):
        """Fill ``fb`` (w*h RGB565 words) with the Mandelbrot set."""
        sh = 13
        limit = 4 * (1 << 26)       # 4.0 in fixed point, escape radius squared
        two_w = 2 * w
        two_h = 2 * h
        for y in range(h):
            ci = b_im + ((2 * y + 1) * a_im) // two_h
            base = y * w
            for x in range(w):
                cr = b_re + ((2 * x + 1) * a_re) // two_w
                zr = 0
                zi = 0
                it = 0
                while it < max_iter:
                    zr2 = zr * zr
                    zi2 = zi * zi
                    if zr2 + zi2 >= limit:
                        break
                    # update from the old zr, zi: the imaginary part first,
                    # while zr is still the old one
                    zi = ((2 * zr * zi) >> sh) + ci
                    zr = ((zr2 - zi2) >> sh) + cr
                    it += 1
                if it >= max_iter:
                    fb[base + x] = 0                      # inside: black
                else:
                    # a blue-to-green wash that brightens with escape time
                    level = (it * 255) // max_iter
                    fb[base + x] = ((level & 0xFC) << 3) | ((255 - level) >> 3)

    t0 = time.ticks_ms()
    render(fb, w, h, MAX_ITER, A_RE, B_RE, A_IM, B_IM)
    d.show()                        # flush the framebuffer to the panel
    print("mandelbrot_viper: %dx%d samples in %d ms"
          % (w, h, time.ticks_diff(time.ticks_ms(), t0)))


if __name__ == "__main__":
    main()
