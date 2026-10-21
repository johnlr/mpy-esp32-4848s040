# Examples

Every example here needs nothing but `esp32_4848s040.py` and MicroPython's
built-in modules - run them on any board that has the driver, no other repo
files required.

All of them run with:

```sh
mpremote connect /dev/ttyUSB0 run examples/<name>.py
```

Ctrl-C stops the animated ones.

---

## The examples

### demo.py

The "does the panel work" demo: solid primaries, the driver's colour-bar test
pattern, and text drawn with `framebuf`'s built-in 8x8 font. The reference for
what a minimal program looks like.

### hello.py

The smallest complete program: five solid fills, the test pattern, then an info
frame with a border. The info frame names the device (`ESP32-4848S040`), the
panel format and resolution (`480x480 RGB565 16bpp`), the MicroPython version
banner it is running (built at run time from `sys.implementation` and
`os.uname()`, e.g. `MicroPython v1.29.0 on 2026-08-24 /
ESP32_GENERIC_S3-SPIRAM_OCT with ESP32S3`), and the author, over a full
hue/saturation colour wheel (hue by angle, saturation by radius). Stops on the
last frame.

### gradient.py

A full-screen 2D colour gradient (red/blue on one axis, green on the other).
Drawn as 900 solid 16x16 blocks via `fill_rect` rather than a per-pixel Python
loop - the difference between a frame that takes milliseconds and one that
takes seconds.

### plasma.py

An animated plasma. The field is evaluated once per 10x10 block (48x48 samples)
using `math.sin`, double buffered. Smooth enough to watch, cheap enough to run.

### starfield.py

A 3D starfield flying towards the viewer. Each star is a depth-sorted point
projected by dividing by its z; nearer stars are brighter. 220 `pixel()` calls
per frame, double buffered.

### life.py

Conway's Game of Life on a 120x120 toroidal grid (one cell per 4x4 block).
Each generation is drawn whole into the off-screen buffer. Runs at a few fps,
which is the right pace for Life.

### mandelbrot.py

The Mandelbrot set rendered in pure Python. The escape-time loop is evaluated
at a coarse resolution (each sample paints a 3x3 block) and takes a couple of
minutes. Included as the reference that the viper version is compared against.

---

## Viper versions

Both of these compile the hot loop with `@micropython.viper` instead of
interpreting it. Run them back to back with the originals to see the difference.

### plasma_viper.py

Full 480x480 plasma (the original is per-block) at ~11fps vs the original's
~2.7fps. Same picture, same motion.

**Changes and compromises:**

- `math.sin` is not available to viper, so the sine is a 256-entry fixed-point
  lookup table. Angles are quantised to 1.4 degrees, which is invisible in the
  smooth plasma field.
- The table is biased into 0..2048 (non-negative) because `ptr16` loads
  zero-extend - a negative `array('h')` entry reads back as a large positive.
  The bias is removed from the sum.
- The colour is a precomputed LUT indexed by the sine sum, replacing the
  per-pixel red/green/blue arithmetic with one table load.
- The per-x sine is precomputed once per frame (it does not depend on y),
  turning a per-pixel lookup into a single load.
- Colours match the float formula exactly (verified: 0 mismatches over all
  230400 pixels).

### mandelbrot_viper.py

Full 480x480 Mandelbrot in **1.4s** vs the pure Python version's **~208s**
(144x faster).

**Changes and compromises:**

- Viper has **no native float type** on this build: `def f(x: float)` is
  rejected, and passing floats as `object` re-boxes them, making a "float" viper
  version *slower* than pure Python. The escape loop is therefore done in
  Q13.13 fixed point, which viper maps to single 32-bit instructions.
- The shift must stay at 13: `1 << 30` is already a bignum viper cannot use in
  arithmetic, and `zr * zr` overflows a 32-bit register once the scale passes
  2^14. Shift 13 is the largest value that stays inside 32 bits for the whole
  image.
- The shift and limit are written as **literals** inside the function - a
  module global is an *object* to viper, and an int register cannot be compared
  with or shifted by one.
- The entire render (coordinate generation, escape loop, framebuffer writes) is
  a **single viper call**, so the ~10us/call overhead is paid once instead of
  230400 times. The framebuffer is written directly as `ptr16`, bypassing
  `fill_rect`.
- The image is a fixed-point approximation of the float version: ~1% of
  boundary pixels differ, which is invisible. The set's boundary is infinitely
  detailed, so any finite precision eventually disagrees with the true boundary
  at some scale - fixed point just reaches that scale sooner.

### lavalamp_viper.py

Three metaballs heat on the bulb, rise, cool at the top and sink again - a
thermal-convection model rather than sine-driven positions - at full 480x480
and ~9 fps.

Each blob carries a `heat` value that relaxes toward the local ambient
temperature (a steady gradient: hot at the bottom, cold at the top), plus
extra heating while it rests on the bulb. Buoyancy is proportional to
`heat - NEUTRAL`: hotter than neutral rises, cooler sinks. A little drag gives
the fluid viscosity, so blobs carry momentum, overshoot the midpoint and sweep
the full height instead of parking in the middle. The physics is per-blob
(three of them), so it runs in plain Python and costs nothing next to the
render.

**Changes and compromises:**

- **Polynomial falloff instead of 1/d.** A metaball is `max(0, R*R - d)` where
  `d` is the squared distance, rather than the classic `R*R / d`. Division is
  the slow part inside viper, so this trades a little physical accuracy for a
  large speed-up while still merging smoothly.
- **The bounding-box trick needs a distance check.** Clipping each blob to
  `|dx| < R and |dy| < R` skips the multiply for most of the screen, but the
  corners of that square still satisfy the box test while `dx*dx + dy*dy` is
  *larger* than `R*R`. Without re-checking `d < R*R` inside the box those
  corners add a **negative** contribution and carve dark notches out of the
  blob. The full distance test has to stay.
- **Background rows and columns are filled, not evaluated.** A row outside all
  three blobs' vertical bands, and the columns outside the combined bounding
  box, are written straight to `0x0000`. That is most of the frame.
- **`show()` with no arguments.** The whole buffer is redrawn every frame, so
  the driver flushes all of it. With `fbs=2` a narrowed flush is refused (it
  would leave stale pixels), and `d.next_fb()` hands back the buffer to draw
  into each frame.
- **Integer colour index.** The palette is a 20-entry `array('H')` LUT, so the
  per-pixel cost is one table load instead of red/green/blue arithmetic.
- **Physics stays in Python, render in viper.** Only the per-pixel field needs
  viper; the three-blob convection model is a handful of float operations per
  frame, which is far cheaper to write (and read) as plain Python. The blob
  centres cross the boundary as `int(...)` pixel coordinates.
- **Motion is deliberately vertical.** Heat is at the bottom, so a warm blob
  should climb and a cool one should sink - mostly along y. The only horizontal
  drive is a small jitter (walls keep blobs in bounds). There is **no pull
  toward a common centre**: drag is high (`DRAG = 0.972`, a ~35x velocity gain),
  so even a weak centre force both out-shoves buoyancy (blobs dart side to side
  instead of rising) and funnels all three into one column. Removing it makes
  the vertical-to-horizontal motion ratio about 20:1.
