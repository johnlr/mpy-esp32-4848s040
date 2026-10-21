"""Render the Mandelbrot set once, into the framebuffer.

A one-shot still image rather than an animation.  The escape-time loop is
pure Python, so it is evaluated at a coarse resolution - each sample paints a
3x3 block - and still takes a couple of seconds.  Every sample is one
``framebuf.fill_rect()``; ``show()`` puts the finished frame on the panel.

For the fast viper version see ``examples/mandelbrot_viper.py``.

    mpremote connect /dev/ttyUSB0 run examples/mandelbrot.py

Only the driver is needed.
"""

import time

try:
    import micropython
    HAVE_VIPER = hasattr(micropython, 'viper')
except Exception:
    micropython = None
    HAVE_VIPER = False

from esp32_4848s040 import DPI

#: Pixels per side of one sample, and the iteration cap.  A larger cap draws
#: more of the filigree around the edge and costs proportionally longer.
BLOCK = 3
MAX_ITER = 40


def rgb565(r, g, b):
    """Pack 0..255 channels into an RGB565 word, the panel's pixel format."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def main():
    d = DPI()
    fb = d.fbuf
    nx = d.width // BLOCK
    ny = d.height // BLOCK

    t0 = time.ticks_ms()

    if HAVE_VIPER:
        @micropython.viper
        def mandel_viper(cr: object, ci: object, max_iter: int) -> int:
            zr = 0.0
            zi = 0.0
            it = 0
            limit = 4.0
            crv = float(cr)
            civ = float(ci)
            while it < max_iter:
                zr2 = zr * zr
                zi2 = zi * zi
                if zr2 + zi2 >= limit:
                    break
                zr, zi = zr2 - zi2 + crv, 2.0 * zr * zi + civ
                it += 1
            if it >= max_iter:
                return 0x0000
            level = (it * 255) // max_iter
            return ((level & 0xF8) << 8) | (((level >> 1) & 0xFC) << 3) | level
        mandel = mandel_viper
    else:
        def mandel(cr, ci, max_iter):
            zr = zi = 0.0
            it = 0
            while it < max_iter and zr * zr + zi * zi < 4.0:
                zr, zi = zr * zr - zi * zi + cr, 2 * zr * zi + ci
                it += 1
            if it >= max_iter:
                return 0x0000
            level = (it * 255) // max_iter
            return rgb565(0, level, 255 - level)

    for by in range(ny):
        ci = (by + 0.5) / ny * 2.6 - 1.3          # imaginary axis, -1.3..1.3
        for bx in range(nx):
            cr = (bx + 0.5) / nx * 3.2 - 2.35     # real axis, -2.35..0.85
            colour = mandel(cr, ci, MAX_ITER)
            fb.fill_rect(bx * BLOCK, by * BLOCK, BLOCK, BLOCK, colour)
    d.show()
    print("mandelbrot: %dx%d samples in %d ms"
          % (nx, ny, time.ticks_diff(time.ticks_ms(), t0)))


if __name__ == "__main__":
    main()
