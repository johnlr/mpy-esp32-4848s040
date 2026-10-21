"""Conway's Game of Life, one cell per 4x4 block of the panel.

A torus-wrapped 120x120 grid, so the edges wrap around instead of dying off.
Counting the eight neighbours is a Python loop over the grid - 14400 cells a
frame - so this runs a few frames a second, which is the right pace for Life
anyway.  The panel is double buffered, and each generation is drawn whole
into the buffer that is off screen.

    mpremote connect /dev/ttyUSB0 run examples/life.py

Ctrl-C stops it.  Only the driver is needed.
"""

import random

from esp32_4848s040 import DPI

#: Pixels per side of one cell, so the grid is (480/CELL) x (480/CELL).
CELL = 4
COLS = 480 // CELL
ROWS = 480 // CELL

ALIVE = 0x07E0            # green cells against the black background


def step(grid, cols, rows):
    """Return the next generation of a torus-wrapped grid of 0/1 bytes."""
    out = bytearray(cols * rows)
    for y in range(rows):
        ym = (y - 1) % rows
        yp = (y + 1) % rows
        row = y * cols
        rowm = ym * cols
        rowp = yp * cols
        for x in range(cols):
            xm = (x - 1) % cols
            xp = (x + 1) % cols
            n = (grid[rowm + xm] + grid[rowm + x] + grid[rowm + xp]
                 + grid[row + xm] + grid[row + xp]
                 + grid[rowp + xm] + grid[rowp + x] + grid[rowp + xp])
            if grid[row + x]:
                out[row + x] = 1 if n == 2 or n == 3 else 0
            else:
                out[row + x] = 1 if n == 3 else 0
    return out


def main():
    d = DPI(fbs=2)
    grid = bytearray(1 if random.random() < 0.28 else 0
                     for _ in range(COLS * ROWS))

    while True:
        fb = d.fbuf                  # must be re-read: it alternates
        fb.fill(0x0000)
        for y in range(ROWS):
            base = y * COLS
            py = y * CELL
            for x in range(COLS):
                if grid[base + x]:
                    fb.fill_rect(x * CELL, py, CELL, CELL, ALIVE)
        d.show()
        grid = step(grid, COLS, ROWS)


if __name__ == "__main__":
    main()
