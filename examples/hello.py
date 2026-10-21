"""The smallest complete program that lights up the panel.

This is the standalone counterpart of ``examples/demo.py``: it imports the
driver and nothing else from this project, so it runs on a board whose
filesystem holds only ``esp32_4848s040.py``::

    mpremote connect /dev/ttyUSB0 run examples/hello.py

Drawing is MicroPython's own ``framebuf``, which the driver already hands you
as ``d.fbuf``.  ``framebuf`` carries an 8x8 font of its own, so the text below
needs nothing beyond the driver.

The last frame is an info screen: the board, the panel format and resolution,
the MicroPython build actually running - the same version banner the board
prints at startup - and the author, over a full hue/saturation colour wheel.
"""

import math
import sys
import time

from esp32_4848s040 import DPI

#: Full turn in radians, for the colour wheel's hue axis.
TAU = math.pi * 2

#: Who wrote this, matching the MIT ``LICENSE`` in the repo root.
AUTHOR = "John La Rooy"

#: The board this driver targets.
DEVICE = "ESP32-4848S040"


def rgb565(r, g, b):
    """Pack 0..255 channels into an RGB565 word, the panel's pixel format."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def hsv_to_rgb(h, s, v):
    """Hue/saturation/value in 0..1 to 0..255 r, g, b.  Hue wraps at 1.0."""
    h = h - math.floor(h)                   # normalise into 0..1 (h may be < 0)
    h *= 6.0                                # 0..6 sectors
    i = int(h)
    if i > 5:
        i = 5
    f = h - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    if i == 0:
        rf, gf, bf = v, t, p
    elif i == 1:
        rf, gf, bf = q, v, p
    elif i == 2:
        rf, gf, bf = p, v, t
    elif i == 3:
        rf, gf, bf = p, q, v
    elif i == 4:
        rf, gf, bf = t, p, v
    else:
        rf, gf, bf = v, p, q
    return int(rf * 255), int(gf * 255), int(bf * 255)


def _uname(index):
    """Field ``index`` of ``os.uname()``, or ``""`` if unavailable."""
    try:
        import os
        return str(os.uname()[index])
    except Exception:
        return ""


def _version():
    """The version as the startup banner shows it.

    ``os.uname().release`` is authoritative and keeps suffixes such as
    ``-preview`` (e.g. ``1.30.0-preview`` on a daily build).  Fall back to
    ``sys.implementation.version``, which is the numeric tuple instead.
    """
    release = _uname(2)
    if release:
        return "v" + release
    ver = getattr(getattr(sys, "implementation", None), "version", None)
    if ver and len(ver) >= 3:
        return "v{}.{}.{}".format(ver[0], ver[1], ver[2])
    return ""


def _banner_lines():
    """Reproduce the line MicroPython prints at startup, as a list of lines.

    The banner is::

        MicroPython v<version> on <date>; <build> with <machine>

    for example::

        MicroPython v1.29.0 on 2026-08-24; ESP32_GENERIC_S3-SPIRAM_OCT with ESP32S3

    The pieces come from ``os.uname()`` (release = version, version = build
    date and git hash, machine = the full board description) plus
    ``sys.implementation._build`` for the build name.  Split across lines
    here because the whole banner is too wide for a 480-pixel row at the 8x8
    framebuf font.

    Field meanings differ between a stock build (where ``release`` is the
    bare version and ``uname().version`` carries the date) and a custom one
    (where ``release`` may be ``1.30.0-preview`` and ``machine`` already
    names the board), so each part is included only if it adds something.
    """
    impl = getattr(sys, "implementation", None)

    version = _version()
    build = getattr(impl, "_build", None) or _uname(1)
    build = str(build) if build else ""

    # os.uname().version is "<git-hash> on <date>" on stock builds; the date
    # is the last whitespace-separated token.
    date = ""
    version_field = _uname(3)
    if version_field and " on " in version_field:
        date = version_field.rsplit(" on ", 1)[1].strip()

    machine = _uname(4)

    head = "MicroPython"
    if version:
        head += " " + version
    if date and date not in version:
        head += " on " + date

    # The build name and the machine description often overlap (a custom
    # build's _build is already the board name), so only append the machine
    # when it is not already implied.
    tail = build
    if machine and machine not in build and build.split("_")[0] not in machine:
        tail = (tail + " with " + machine) if tail else machine

    lines = [head]
    if tail:
        lines.append(tail)
    return lines


def main():
    d = DPI()                       # 480x480, RGB565, one framebuffer

    # 1. solid colours, one per frame -------------------------------------
    for colour in (0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000):
        d.fill(colour)
        d.show()                    # flush the frame and put it on the panel
        time.sleep_ms(300)

    # 2. the driver's own test pattern ------------------------------------
    d.test_pattern()                # 8 vertical colour bars
    d.show()
    time.sleep_ms(500)

    # 3. framebuf text and shapes -----------------------------------------
    # With fbs=1 there is only one framebuffer, so it is safe to hold on to
    # d.fbuf.  With fbs=2 it alternates on every show() - ask again each
    # frame instead (see plasma.py).
    fb = d.fbuf
    fb.fill(0x0010)

    fb.text(DEVICE, 8, 8, 0x07E0)
    fb.text("MicroPython RGB panel", 8, 24, 0xFFFF)
    fb.text("480x480  RGB565  16bpp", 8, 40, 0x07FF)

    fb.text("build:", 8, 72, 0x8410)
    y = 88
    for line in _banner_lines():
        fb.text(line, 8, y, 0xFFFF)
        y += 16

    fb.text("author:", 8, 120, 0x8410)
    fb.text(AUTHOR, 8, 136, 0xFFFF)

    # A colour wheel: hue by angle, full saturation at the rim, darkening to
    # black at the centre.  framebuf has no arcs, so it is rasterised per
    # pixel with fb.pixel().  Only the rows that the circle occupies are
    # visited, and each row only from the left edge to the right edge, so
    # the work is the wheel's area rather than the whole screen.
    cx = 240
    cy = 285
    radius = 140
    r2max = radius * radius
    for y in range(cy - radius, cy + radius):
        dy = y - cy
        half = int(math.sqrt(r2max - dy * dy))      # circle half-width here
        for x in range(cx - half, cx + half + 1):
            dx = x - cx
            rr = dx * dx + dy * dy
            if rr > r2max:
                continue
            angle = math.atan2(dy, dx) / TAU        # hue around the rim
            sat = math.sqrt(rr) / radius            # saturation by radius
            r, g, b = hsv_to_rgb(angle, sat, 1.0)
            fb.pixel(x, y, rgb565(r, g, b))

    fb.rect(0, 0, d.width, d.height, 0x07FF)
    d.show()

    print("hello: done (the panel keeps this frame)")


if __name__ == "__main__":
    main()
