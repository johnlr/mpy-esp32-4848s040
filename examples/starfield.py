"""A starfield flying towards the viewer - pixel drawing, double buffered.

Every star is a 3D point; each frame its depth shrinks a little and it is
projected onto the screen by dividing by that depth.  Drawing is one
``pixel()`` per star, so what costs is the star count, not the screen size.
``fbs=2`` keeps the motion tear-free; a brighter pixel is used the nearer a
star is, which is what sells the depth.

    mpremote connect /dev/ttyUSB0 run examples/starfield.py

Ctrl-C stops it.  Only the driver is needed.
"""

import random

from esp32_4848s040 import DPI

#: How many stars share the screen, and how far away the farthest starts.
STARS = 220
FAR = 4.0

#: Depth lost per frame; once a star passes the viewer it is respawned.
SPEED = 0.03


def grey(level):
    """An RGB565 word for a 0..255 grey level."""
    level &= 0xFF
    return ((level & 0xF8) << 8) | ((level & 0xFC) << 3) | (level >> 3)


def main():
    d = DPI(fbs=2)
    cx = d.width / 2.0
    cy = d.height / 2.0
    rnd = random.random

    # [x, y, z]: x and y are -1..1 across the view, z is the depth.
    stars = [[rnd() * 2 - 1, rnd() * 2 - 1, rnd() * FAR + 0.2]
             for _ in range(STARS)]

    while True:
        fb = d.fbuf                  # must be re-read: it alternates
        fb.fill(0x0000)              # every frame is drawn whole
        for s in stars:
            s[2] -= SPEED
            if s[2] <= 0.05:         # past the viewer: back to the far end
                s[0] = rnd() * 2 - 1
                s[1] = rnd() * 2 - 1
                s[2] = FAR
            k = 1.0 / s[2]           # perspective: nearer -> larger, brighter
            x = int(cx + s[0] * k * cx)
            y = int(cy + s[1] * k * cy)
            if 0 <= x < d.width and 0 <= y < d.height:
                fb.pixel(x, y, grey(255 - int(s[2] * 56)))
        d.show()


if __name__ == "__main__":
    main()
