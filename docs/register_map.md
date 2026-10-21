# Register map and ground truth

This document is the reference for `lcd/`.  Everything in the pure-Python
driver is derived from, and checked against, a **register dump taken from the
working custom C module** (`lcd_binding_micropython`, the one that talked to
the panel correctly).  That dump is checked in verbatim as
[`dump_working_c.md`](dump_working_c.md), captured on-device.

The port has no access to any C symbol, so the only way to be sure it is
*identical* to the reference is to replay the same registers and diff a fresh
dump - on a workstation against a fake `machine.mem32`, and on the board
itself.  Both were done; the results are in [Sec. 5](#5-verification).

---

## 1. Required firmware

The port must run on **stock** MicroPython, no custom C module.  It needs the
**octal-SPIRAM** build because the framebuffer lives in PSRAM:

| build | PSRAM | works? |
|---|---|---|
| `ESP32_GENERIC_S3-SPIRAM_OCT` (v1.29.0) | 8 MB octal, detected | **yes** |
| `ESP32_GENERIC_S3` (plain) | not detected | no - only ~226 KB `gc.mem_free()`, PSRAM allocations fail |

Download the correct image from
<https://micropython.org/download/ESP32_GENERIC_S3/>, section *"Support for
Octal-SPIRAM"* (v1.29.0), and flash it with `esptool`.

```
MicroPython v1.29.0 on 2026-08-24; Generic ESP32S3 module with Octal-SPIRAM
_build='ESP32_GENERIC_S3-SPIRAM_OCT'
gc.mem_free() == 8318720        # ~8 MB
```

The reference C firmware was `GUITION_4848S040`, MicroPython 1.30.0-preview.
Only the tooling differs; the peripheral programming is what matters.

---

## 2. The panel and the wires

Guition ESP32-S3-4848S040: 480x480 IPS panel with an **ST7701S** controller
driven in **RGB (DPI) parallel mode**, 16 bits/px.

| signal | GPIO | notes |
| --- | --- | --- |
| B0..B4 (`data[0..4]`) | 4, 5, 6, 7, 15 | blue, LSB first |
| G0..G5 (`data[5..10]`) | 8, 20, 3, 46, 9, 10 | green |
| R0..R4 (`data[11..15]`) | 11, 12, 13, 14, 0 | red, MSB last |
| HSYNC | 16 | |
| VSYNC | 17 | |
| DE | 18 | |
| PCLK | 21 | 11 MHz |
| backlight | 38 | plain GPIO, active high |
| SPI CS (ST7701) | 39 | bit-banged, plain GPIO |
| SPI SCK (ST7701) | 48 | bit-banged, plain GPIO |
| SPI SDA (ST7701) | 47 | bit-banged, plain GPIO |

The `DATA_PINS` tuple in `esp32_4848s040.py` is ordered `data[0] .. data[15]`, i.e.
`(4, 5, 6, 7, 15, 8, 20, 3, 46, 9, 10, 11, 12, 13, 14, 0)`; it comes straight
from the vendor Arduino demo `86switch_onoff.ino`:

```cpp
Arduino_ESP32RGBPanel bus(39 CS, 48 SCK, 47 SDA,
    18 DE, 17 VSYNC, 16 HSYNC, 21 PCLK,
    11 R0, 12 R1, 13 R2, 14 R3, 0 R4,
    8 G0, 20 G1, 3 G2, 46 G3, 9 G4, 10 G5,
    4 B0, 5 B1, 6 B2, 7 B3, 15 B4);
```

### 2.1 ST7701 register init: 9-bit 3-wire SPI, bit-banged

The ST7701 3-wire serial interface uses **9-bit frames**: a D/C bit followed by
8 data bits, MSB first.  The ESP-IDF SPI master cannot emit 9-bit frames, which
is why the original bring-up produced a blank panel.  The `st7701` class in
`esp32_4848s040.py` bit-bangs it on CS=39 / SCK=48 / SDA=47:

* D/C = 0 for a command byte, 1 for a data byte (this is the 9th bit).
* one frame = set SDA, pulse SCK high then low.
* per-byte setup/hold delays of ~2 us (`_DELAY_US`), ~50 ns per pulse.

Order of operations (mirrors `Arduino_ST7701_RGBPanel::begin()`):

1. `CS` low *before* the first frame; `panel_init()` runs the full table.
2. Software reset `0x01`, wait 120 ms.
3. Every `(cmd, (data...))` pair of the ST7701 type-1 table.
4. `0x11` (sleep out), wait 120 ms.
5. `0x29` (display on), `0x20` (inversion off), `0xC7 = 0x00`, `0x36 = 0x00`
   (MADCTL).
6. `CS` high (10 ms CS-low hold in the reference).

The exact 33-entry table (165 data bytes) lives in `esp32_4848s040.py::INIT_SEQUENCE`,
byte for byte identical to the `OP(...)` list in `st7701_type1_init_operations`
in the C reference
(`build/micropython/lcd_binding_micropython/lcd/hal/esp32/esp32.c`), and was
checked byte for byte against it.  Note `0x3A = 0x60`
(the panel's own internal pixel format) and `0xFF 0x77 0x01 0x00 0x00 0x13`
selecting the VAP/VAN bank.

---

## 3. Register dump: ground truth vs. this port

Values captured after the C module's `lcd.DPI()` completed, i.e. with the DMA
running.  "replayed" is what `lcd/` writes.

### 3.1 `SYSTEM` @ `0x600C0000` - bus clocks and resets

| offset | register | ground truth | notes |
| --- | --- | --- | --- |
| `0x1C` | `SYSTEM_PERIP_CLK_EN1` | `0x00000540` | bit6 `DMA_CLK_EN`, bit8 `LCD_CAM_CLK_EN`, bit10 `USB_DEVICE_CLK_EN` (boot default) |
| `0x24` | `SYSTEM_PERIP_RST_EN1` | `0x0000028e` | bits 6 and 8 **clear**: both peripherals out of reset |

Both the LCD_CAM and the general-purpose GDMA bus clocks are **off** at reset
on this chip (`SYSTEM_DMA_CLK_EN` / `SYSTEM_LCD_CAM_CLK_EN` both default to
`0`); ESP-IDF turns them on from `lcd_ll_enable_bus_clock()` /
`gdma_ll_enable_bus_clock()`.  Until they are set, every LCD_CAM and GDMA
register reads back as zero, which is exactly what a stock board shows.

`lcd_cam.enable_bus_clock()` / `reset_peripheral()` and
`gdma.enable_bus_clock()` / `reset_peripheral()` do the same
read-modify-write so the bits arm this port does not own are preserved.

> The peripheral reset bits are *asserted then de-asserted* (not just cleared).
> On a stock board the LCD_CAM and GDMA resets are already released, but
> asserting them first restores every register to its hardware default, which
> is what makes the rest of the dump reproducible.

### 3.2 `GPIO` @ `0x60004000` - matrix routing

`GPIO_FUNCn_OUT_SEL_CFG = 0x60004554 + 4*n`:

| GPIO | signal | index | ground truth | note |
| --- | --- | --- | --- | --- |
| 0 | `LCD_DATA_OUT15` | 148 | `0x00000094` | |
| 1, 2 | - | `SIG_GPIO_OUT` | `0x00000100` | |
| 3 | `LCD_DATA_OUT7` | 140 | `0x0000008c` | |
| 4 | `LCD_DATA_OUT0` | 133 | `0x00000085` | |
| 5 | `LCD_DATA_OUT1` | 134 | `0x00000086` | |
| 6 | `LCD_DATA_OUT2` | 135 | `0x00000087` | |
| 7 | `LCD_DATA_OUT3` | 136 | `0x00000088` | |
| 8 | `LCD_DATA_OUT5` | 138 | `0x0000008a` | |
| 9 | `LCD_DATA_OUT9` | 142 | `0x0000008e` | |
| 10 | `LCD_DATA_OUT10` | 143 | `0x0000008f` | |
| 11 | `LCD_DATA_OUT11` | 144 | `0x00000090` | |
| 12 | `LCD_DATA_OUT12` | 145 | `0x00000091` | |
| 13 | `LCD_DATA_OUT13` | 146 | `0x00000092` | |
| 14 | `LCD_DATA_OUT14` | 147 | `0x00000093` | |
| 15 | `LCD_DATA_OUT4` | 137 | `0x00000089` | |
| 16 | `LCD_H_SYNC` | 151 | `0x00000097` | |
| 17 | `LCD_V_SYNC` | 152 | `0x00000098` | |
| 18 | `LCD_H_ENABLE` | 150 | `0x00000096` | DE |
| 19 | - | `SIG_GPIO_OUT` | `0x00000100` | USB D-, left alone |
| 20 | `LCD_DATA_OUT6` | 139 | `0x0000008b` | |
| 21 | `LCD_PCLK` | 154 | `0x0000009a` | |
| 22..38 | - | `SIG_GPIO_OUT` | `0x00000100` | |
| 39 | - | `SIG_GPIO_OUT` | `0x00000100` | ST7701 CS, plain GPIO |
| 46 | `LCD_DATA_OUT8` | 141 | `0x0000008d` | |
| 47 | - | `SIG_GPIO_OUT` | `0x00000100` | ST7701 SDA, plain GPIO |
| 48 | - | `SIG_GPIO_OUT` | `0x00000100` | ST7701 SCK, plain GPIO |

The `out_sel` field is bits `[9:0]`, so writing the whole register with the
signal index leaves `oen_sel` / `oen_inv_sel` / `out_inv_sel` at 0 - output
enable then comes from the plain `GPIO_ENABLE`/`GPIO_ENABLE1` bits, exactly as
the ground truth shows.

Output enables:

| register | ground truth | meaning |
| --- | --- | --- |
| `GPIO_ENABLE` (`+0x20`) | `0x0037fff9` | GPIO 0,3..18,20,21 = 15 data + HSYNC + VSYNC + DE + PCLK |
| `GPIO_ENABLE1` (`0x6000402C`) | `0x0001C0C0` | GPIO38 (BL), 39 (CS), 46 (data8), 47 (SDA), 48 (SCK) |
| `GPIO_OUT1` (`0x60004010`) | `0x000000C0` | GPIO38 and 39 high: backlight on, CS idle |

`esp32_4848s040.py` writes the `_W1TS` aliases (`0x24`/`0x30`) rather than
doing read-modify-write on the status registers, which is safe and idempotent.

The GPIO matrix is only half of the routing. Each pad's **IO_MUX** register
(`IO_MUX_GPIO0_REG + 4*n` @ `0x60009004`) `MCU_SEL` field (`bits [14:12]`)
selects what drives the pad: `1` = GPIO function, `0` = the pad's own IOMUX
function. This reset value is not `1` on every pin - GPIO39 (CS) resets to `0` -
and the GPIO output register only reaches the pad when `MCU_SEL` selects the GPIO
function. The reference firmware uses `pinMode()`, which sets it; the pure
driver therefore writes `MCU_SEL_GPIO | FUN_IE` in `enable_output()` too. Omitting
it leaves CS undriven, so the bit-banged ST7701 init is silently discarded and
the panel only survives until the next cold boot.

### 3.3 `LCD_CAM` @ `0x60041000`

| offset | register | ground truth | replayed | |
| --- | --- | --- | --- | --- |
| `0x00` | `LCD_CLOCK` | `0xE5860E01` | `0xE5860E01` | yes |
| `0x04` | `CAM_CTRL` | `0x00000800` | `0x00000800` | yes |
| `0x0C` | `CAM_RGB_YUV` | `0x00C00000` | `0x00C00000` | yes |
| `0x10` | `LCD_RGB_YUV` | `0x00C00000` | `0x00C00000` | yes |
| `0x14` | `LCD_USER` | `0x09802000` | `0x09802000` | yes |
| `0x18` | `LCD_MISC` | `0x06000016` | `0x06000016` | yes |
| `0x1C` | `LCD_CTRL` | `0xC0AEF839` | `0xC0AEF839` | yes |
| `0x20` | `LCD_CTRL1` | `0x2231DF1B` | `0x2231DF1B` | yes |
| `0x24` | `LCD_CTRL2` | `0x00870287` | `0x00870287` | yes |
| `0x64` | `LC_DMA_INT_ENA` | `0x00000001` | `0x00000001` | yes (inert, see Sec. 6) |
| `0xFC` | `LCD_REG_DATE` | `0x02003020` | (RO) | silicon date |

`CAM_CTRL`, `CAM_RGB_YUV` and `LCD_RGB_YUV` are the values the peripheral
settles on after reset (the camera path is unused); they are written
explicitly so a dump diff stays clean.

#### Clock (`0xE5860E01`)

| field | bits | value | meaning |
| --- | --- | --- | --- |
| `clk_en` | 31 | 1 | on |
| `clk_sel` | 30:29 | 3 | `PLL_F160M` (160 MHz) |
| `div_a` | 28:23 | 11 | fractional divider denominator |
| `div_b` | 22:17 | 3 | fractional divider numerator |
| `div_num` | 16:9 | 7 | integer divider |
| `ck_out_edge` | 8 | 0 | `pclk_active_neg = 0` |
| `ck_idle_edge` | 7 | 0 | `pclk_idle_high = 0` |
| `equ_sysclk` | 6 | 0 | not used |
| `clkcnt_n` | 5:0 | 1 | prescale 2 (`clkcnt_n + 1`) |

```
f_lcd_clk = 160 MHz / (7 + 3/11)           = 22.000 MHz
f_pclk    = 22.000 MHz / (1 + 1)           = 11.000 MHz
```

`lcd_cam.calc_clk_div()` / `cal_pclk_div()` reproduce ESP-IDF's
`hal_utils_calc_clk_div_frac_fast()` + `lcd_hal_cal_pclk_freq()` two-step
search (try prescale 2, unwind if the fraction will not fit).  For 160 MHz ->
11 MHz it returns `(prescale=2, div_num=7, div_a=11, div_b=3)`, exactly the
ground truth.

#### Timings (`LCD_CTRL`/`1`/`2`)

The counters are inclusive, so everything is stored "minus one"
(`lcd_ll_set_horizontal_timing()` etc.):

| quantity | formula | value |
| --- | --- | --- |
| `hb_front` [10:0] | `hbp + hsw - 1` = 50 + 8 - 1 | 57 = `0x39` |
| `va_height` | 20:11 | `height - 1` = 479 | `0x1DF` |
| `vt_height` | 30:21 | `8+20+480+10-1` | 517 |
| `rgb_mode_en` | 31 | 1 | RGB mode |
| `vb_front` | 7:0 | `vbp + vsw - 1` = 20+8-1 | 27 |
| `ha_width` | 19:8 | 479 | |
| `ht_width` | 31:20 | `8+50+480+10-1` = 547 | |
| `vsync_width` | 6:0 | `vsw - 1` = 7 | |
| `vsync_idle_pol` | 7 | 1 | `vsync_idle_low = 0` -> idle high |
| `de_idle_pol` | 8 | 0 | `de_idle_high = 0` |
| `hs_blank_en` | 9 | 1 | always set by IDF |
| `hsync_width` | 22:16 | 7 | `hsync_pulse_width - 1` |
| `hsync_idle_pol` | 23 | 1 | `hsync_idle_low = 0` |
| `hsync_position` | 31:24 | 0 | |

These come from the Arduino panel constructor
`Arduino_ST7701_RGBPanel(..., 10, 8, 50, 10, 8, 20)` - i.e. 480x480 with
`hsync_front_porch=10`, `hsync_pulse_width=8`, `hsync_back_porch=50`,
`vsync_front_porch=10`, `vsync_pulse_width=8`, `vsync_back_porch=20` - and from
the polarity flags the C binding feeds to `esp_lcd_rgb_panel_config_t`
(`hsync_idle_low=0`, `vsync_idle_low=0`, `de_idle_high=0`,
`pclk_active_neg=0`, `pclk_idle_high=0`).

#### `LCD_MISC` (`0x06000016`) and `LCD_USER` (`0x09802000`)

| field | value | meaning |
| --- | --- | --- |
| `lcd_afifo_threshold_num` | 11 (bits 5:1) | `0x16` - the value the reference leaves |
| `lcd_next_frame_en` | 1 (bit 25) | keep streaming frames |
| `lcd_bk_en` | 26 | blank-region generation on |
| `lcd_vbk_cyclelen` | 0 | |

`LCD_USER` before the start bit: `0x01802000`

* bit 13 `always_out_en` - output continuously, not just when a command runs
* bit 23 `2byte_en` - 16-bit data phase
* bit 24 `dout` - data (not command) output

and after `lcd_ll_start()` (`0x09802000`): `update` (bit 20) self-clears and
`start` (bit 27) is set by us and self-cleared by hardware once the DMA is
feeding, exactly as the ground-truth dump shows (it reads `0x09802000` with
DMA running).

#### Start-up sequence

`DPI.start()` mirrors
`esp_lcd_panel_rgb.c::lcd_rgb_panel_start_transmission()`:

```c
gdma_reset(chan);                 //  gdma.Channel.reset()
lcd_ll_stop();                    //  LCD_USER.start = 0
lcd_ll_reset();                   //  LCD_USER.lcd_reset = 1 (WO)
lcd_ll_fifo_reset();              //  LCD_MISC.lcd_afifo_reset = 1
gdma_start(chan);                 //  OUT_LINK = desc | start
delay_us(1);
lcd_ll_start();                   //  LCD_USER.start = 1
```

### 3.4 `GDMA` @ `0x6003F000`, channel 0

| offset | register | ground truth | replayed | |
| --- | --- | --- | --- | --- |
| `0x60` | `OUT_CONF0` | `0x00000030` | `0x00000030` | yes `outdscr_burst_en` + `out_data_burst_en` |
| `0x64` | `OUT_CONF1` | `0x00004000` | `0x00004000` | yes `out_ext_mem_bk_size` = 64 B |
| `0x68` | `OUT_INT_RAW` | `0x00000001` | (status) | runtime |
| `0x70` | `OUT_INT_ENA` | `0x00000002` | `0x00000002` | yes suc-EOF (inert, Sec. 6) |
| `0x78` | `OUTFIFO_STATUS` | runtime | runtime | |
| `0x80` | `OUT_LINK` | `0x000aebf8` | `0x000ba0a0` | desc address, see below |
| `0x84` | `OUT_STATE` | runtime | runtime | |
| `0x88` | `OUT_SUC_EOF_DES_ADDR` | runtime | runtime | |
| `0x8C` | `OUT_EOF_DES_ADDR` | runtime | runtime | |
| `0xA8` | `OUT_PERI_SEL` | `0x00000005` | `0x00000005` | yes `GDMA_PERIPH_LCD_CAM` |

`OUT_LINK` is `(desc_addr & 0xFFFFF) | (1 << 21)`.  The peripheral only stores
20 address bits - the hardware ORs the upper bits back on as
`0x3FC00000 | addr[19:0]`, which is why the descriptor list **must** live in
internal DRAM.  The start bit (21) is self-clearing, so after the DMA is
running `OUT_LINK` reads back as just the low 20 address bits (ground truth
`0x000aebf8` -> descriptor at `0x3FCAEBF8`).

The two addresses differ from the ground truth simply because the descriptor
arena is placed wherever `internal_ram.grab()` lands; what matters is that
`OUT_LINK & 0xFFFFF == desc_addr & 0xFFFFF` and that
`(desc_addr & 0xFFF00000) == 0x3FC00000`.

### 3.4.1 Descriptor format

12 bytes per node, little-endian:

| word | bits | field |
| --- | --- | --- |
| `dw0` | `11:0` | `size` (bytes in this buffer, <= 4095) |
| | `23:12` | `length` (= size) |
| | `29:24` | reserved |
| | `30` | `suc_eof` (raise the EOF interrupt after this buffer) |
| | `31` | `owner` - 1 = owned by DMA |
| `dw1` | `31:0` | `buffer` - full 32-bit address |
| `dw2` | `31:0` | `next` - full 32-bit pointer to the next node |

`LCD_DMA_DESCRIPTOR_BUFFER_MAX_SIZE` is 4095, so a 460800-byte framebuffer is
split into 112 chunks of 4095 bytes plus a final 2160-byte chunk:

```
112 * 4095 + 2160 = 460800      ->  113 descriptors  ->  113 * 12 = 1356 bytes
```

Ground truth node 0: `dw0 = 0x80FFFFFF` ... node 112:
`dw0 = 0xC0870870` (`size = length = 2160`, `owner = 1`, `suc_eof = 1`),
`next = 0x3FCAEBF8` - i.e. it wraps back to the head, making the list
circular so the panel refreshes forever without CPU help.

`dw2` is also where double buffering lives. With `fbs=2` there is one such list
per framebuffer, each closed on itself, and `show()` re-points **every** list's
`dw2` at the head of the frame being presented - which is
`gdma_link_concat(list, -1, other, 0)` in ESP-IDF, from
`rgb_panel_draw_bitmap()`. One aligned 32-bit store per list, into internal DRAM,
so no cache write-back is involved.

### 3.5 `EXTMEM` @ `0x600C4000` - cache write-back

The GDMA reads PSRAM *without* snooping the CPU's L1 data cache, so anything
just drawn has to be flushed to external RAM first.  ESP-IDF does this with
`esp_cache_msync(..., ESP_CACHE_MSYNC_FLAG_DIR_C2M | ..._UNALIGNED)`.

| offset | register | bits |
| --- | --- | --- |
| `0x28` | `EXTMEM_DCACHE_SYNC_CTRL` | bit0 invalidate, bit1 writeback, bit2 clean, bit3 `done` (RO) |
| `0x2C` | `EXTMEM_DCACHE_SYNC_ADDR` | 32-bit start address |
| `0x30` | `EXTMEM_DCACHE_SYNC_SIZE` | 23-bit **cache-block count** |

Ground truth `0x28 = 0x00000008`, i.e. only the read-only `done` bit is set
(the reference's last `msync` was a small partial update,
`SYNC_SIZE = 30` blocks = 960 bytes = one 480-px row; the address is the start
of the framebuffer).  This port flushes the *whole* framebuffer at once:

```
SYNC_ADDR = fb_addr & ~31
SYNC_SIZE = (460800 + 31 + 31) / 32 = 14400 blocks
CTRL      = 0b0010 (writeback);  poll until bit1 clears
```

The **cache block size is 32 bytes**, measured empirically (invalidate one
block at increasing offsets and see when the dirty line containing `base`
stops being hit) - not documented in the TRM.

Cache write-back is **required**: without it the panel shows the previous
frame.  Most of the time it appears to work anyway, because the DMA is far
slower than the cache eviction rate, but it is not guaranteed.

---

## 4. The internal-DRAM descriptor arena

Descriptors are not in the "normal" heap because MicroPython cannot tell you
the *physical* address (and hence the cache/PSRAM attributes) of an arbitrary
allocation.  What is needed is a `bytes`/`bytearray` whose storage is in
internal DRAM *and* still alive in the GC graph.

`internal_ram` gets one by exhausting the GC heap until MicroPython's
`MICROPY_GC_SPLIT_HEAP_AUTO` mechanism grows a fresh heap area, which lands in
internal DRAM (this was verified empirically: the arena address is always
`0x3FC...`).  Concretely:

1. Allocate 1 MiB `bytearray` fillers in a loop, keeping references, until
   `gc.collect()` no longer frees anything and a new 1 MiB allocation fails.
2. Allocate the arena (`bytearray(n)`), which now comes from the freshly grown
   internal-DRAM area.
3. Drop the fillers and `gc.collect()`.
4. `uctypes.addressof(arena)` -> check it is in `0x3FC00000..0x40000000`.

The framebuffer (460800 bytes) is allocated **before** this, so the trick never
has to find a contiguous ~450 KB run afterwards.  If the arena does not land
in internal DRAM the function raises rather than silently using PSRAM.

---

## 5. Verification

### 5.1 Host

Runs the real `lcd.lcd_cam` / `lcd.gdma` code against a fake `machine.mem32`
and compares the written values with the ground truth:

```
OK  lcd_clock    got e5860e01 want e5860e01
OK  lcd_ctrl     got c0aef839 want c0aef839
OK  lcd_ctrl1    got 2231df1b want 2231df1b
OK  lcd_ctrl2    got 00870287 want 00870287
OK  lcd_misc     got 06000016 want 06000016
OK  lcd_rgb_yuv  got 00c00000 want 00c00000
OK  cam_rgb_yuv  got 00c00000 want 00c00000
OK  cam_ctrl     got 00000800 want 00000800
OK  lcd_user     got 09802000 want 09802000
OK  lc_dma_int_ena got 00000001 want 00000001
OK  out_conf0    got 00000030 want 00000030
OK  out_conf1    got 00004000 want 00004000
OK  out_int_ena  got 00000002 want 00000002
OK  out_peri_sel got 00000005 want 00000005
```

plus the descriptor layout: 113 nodes summing to 460800 bytes and summing to
the head again, the same for two lists laid out back to back (double
buffering), and `link_to()` writing exactly one aligned word - the tail's
`dw2` - and nothing else.

### 5.2 Device

On the board the driver printed exactly the same values, plus:

```
# perip_clk_en1  00000540
# perip_rst_en1  0000028e
# lcd_user       09802000
# out_link       000ba0a0        (desc addr 0x3fcba0a0 -> low 20 bits)
# out_state      002fa268
```

and the panel showed the 8 colour bars (red, green, blue, white, yellow, cyan,
magenta, black) with correct colours.

### 5.3 Device, double buffered

A frame swap is not visible in any register, so this reads the lists back
instead.  `tail` is a list's last node and its `dw2` (offset +8) is the word
`show()` rewrites:

```
### double_buffer_test
# free before: 7097920
lcd: 2 framebuffer(s) x 460800 bytes @ 0x3c5debd0 .. 0x3c64f3d0
internal_ram: arena 65536 bytes @ 0x3fcc72f0
lcd: descriptor list 65536 bytes @ 0x3fcc72f0
lcd: 113 DMA descriptors per framebuffer, 11.000 MHz pclk -> 38.75 Hz
# init took 1961 ms
# framebuffers 0x3c5debd0 and 0x3c64f3d0 (460800 apart)
# 113 descriptors per list, 38.75 Hz, frame 26 ms (head0 0x3fcc72f0 head1 0x3fcc783c)
# at rest: tails are self-rings (0x3fcc72f0, 0x3fcc783c), back = 0
# show #1 (frame 0, already on screen): tails unchanged, back = 1
# show #2 (frame 1 -> screen): both tails -> head[1], back = 0
# show #3 (frame 0 -> screen): both tails -> head[0], back = 1
# first access to the new drawing buffer waited 26 ms (frame is 26 ms)
# second access waited 0 ms
# drew 24 bars stepping across both buffers
# free end: 7280144
### END
```

The two framebuffers are exactly `460800` bytes apart and the two lists are
exactly `1356` bytes apart, both inside the one 64 KiB arena.  Each hand-off
re-points **both** lists' tails, and the guard costs at most one frame - here it
waited the full 26 ms and then nothing.

---

## 6. Differences from ESP-IDF that are deliberate

| item | IDF / C reference | this port | why |
| --- | --- | --- | --- |
| `LCD_CAM lc_dma_int_ena` (vsync) | enabled | enabled (parity) | IDF installs an ISR; nothing routes the LCD_CAM interrupt to a CPU here, so the bit is inert. Set only so a dump diff is clean. |
| `GDMA OUT_INT_ENA` (suc-EOF) | enabled | enabled (parity) | same; `esp_lcd` registers a TX callback, we have none. |
| framebuffers | `heap_caps_malloc(PSRAM)`, 1 or 2 fbs, `fb_in_psram` flag | one plain `bytearray` each, `fbs=2` for double buffering | same memory, no allocator |
| frame swap | `gdma_link_concat(fb[i], -1, fb[cur], 0)` for all `i`, from `rgb_panel_draw_bitmap()` | the same loop (`gdma.link_to`) from `DPI.show()` | identical mechanism, driven from Python |
| frame-complete notification | `on_vsync` / `on_frame_buf_complete` from the DMA ISR | none | the LCD_CAM interrupt is not routed to a CPU, so the reuse guard is a time window |
| cache flush | `esp_cache_msync` on the touched region | one full-framebuffer `writeback()` | simpler, still correct |
| panel id / `lcd_com_register_device` | used to share LCD_CAM between panels | not needed | only one panel |
| camera / YUV YUV2RGB path | left at reset | written explicitly | keeps the dump diff clean |
| backlight | driven by LVGL/Arduino code | `DPI.backlight()` | convenience |

Everything else - the clock tree, the timing registers, the AFIFO threshold,
the polarity flags, the GPIO matrix, the descriptor layout and the cache
maintenance - is bit-identical to the working C module.
