"""Pure-MicroPython ST7701 RGB panel driver for the Guition ESP32-S3-4848S040.

Runs on *stock* MicroPython: no custom C module, no extra firmware features.
The LCD_CAM peripheral is programmed directly through ``machine.mem32``.

Typical use::

    from esp32_4848s040 import DPI

    d = DPI()
    d.test_pattern()
    d.show()

See the ``DPI`` class below for the full picture and ``docs/register_map.md``
for the ground truth this port reproduces (a register dump taken from the
working custom C module).
"""

import gc
import struct
import time

import framebuf
import uctypes
from machine import mem32
from micropython import const

__version__ = "0.1.1"
__all__ = ["DPI"]

# ======================================================================
# registers
# ======================================================================
# Register map for the Guition ESP32-S3-4848S040 (ST7701 + RGB LCD).
#
# Everything in here was verified against a register dump taken from the
# *working* custom MicroPython C module (``lcd_binding_micropython``).  The
# captured ground truth lives in ``docs/register_map.md`` (raw dump:
# ``docs/dump_working_c.md``).
#
# The pure-Python port replays exactly that configuration, so every constant
# below is traceable to either the ESP-IDF v5.5.5 sources or to the captured
# dump.

# ---------------------------------------------------------------------------
# Peripheral base addresses (ESP32-S3)
# ---------------------------------------------------------------------------
GPIO_BASE = const(0x60004000)
GDMA_BASE = const(0x6003F000)
LCD_CAM_BASE = const(0x60041000)
SYSTEM_BASE = const(0x600C0000)
EXTMEM_BASE = const(0x600C4000)

# ---------------------------------------------------------------------------
# GPIO registers - soc/gpio_reg.h
# ---------------------------------------------------------------------------
GPIO_OUT_W1TS = GPIO_BASE + 0x08
GPIO_OUT_W1TC = GPIO_BASE + 0x0C
GPIO_OUT1_W1TS = GPIO_BASE + 0x14
GPIO_OUT1_W1TC = GPIO_BASE + 0x18
GPIO_ENABLE_W1TS = GPIO_BASE + 0x24
GPIO_ENABLE_W1TC = GPIO_BASE + 0x28
GPIO_ENABLE1_W1TS = GPIO_BASE + 0x30
GPIO_ENABLE1_W1TC = GPIO_BASE + 0x34

# GPIO_FUNCn_OUT_SEL_CFG is at GPIO_FUNC0_OUT_SEL_CFG + 4 * pin.
GPIO_FUNC0_OUT_SEL_CFG = GPIO_BASE + 0x554

# SIG_GPIO_OUT (0x100) means the pad is driven by the plain GPIO output
# register instead of by a peripheral signal from the GPIO matrix.
SIG_GPIO_OUT = const(0x100)

# IO_MUX pad registers, one per GPIO at IO_MUX_GPIO0_REG + 4 * pin
# (soc/io_mux_reg.h).  MCU_SEL selects what drives the pad: 1 is the GPIO
# function.  FUN_IE enables the input buffer, which the read-back probes and
# the reset defaults use.
IO_MUX_BASE = const(0x60009000)
IO_MUX_GPIO0_REG = IO_MUX_BASE + 0x04
MCU_SEL_MASK = const(0x7 << 12)
MCU_SEL_GPIO = const(0x1 << 12)
FUN_IE = const(1 << 9)

# ---------------------------------------------------------------------------
# LCD_CAM output signals (soc/gpio_sig_map.h)
# ---------------------------------------------------------------------------
LCD_DATA_OUT0_IDX = const(133)          # data bit n -> LCD_DATA_OUT0_IDX + n
LCD_H_ENABLE_IDX = const(150)           # DE
LCD_H_SYNC_IDX = const(151)
LCD_V_SYNC_IDX = const(152)
LCD_PCLK_IDX = const(154)

# ---------------------------------------------------------------------------
# SYSTEM (soc/system_reg.h) - LCD_CAM / GDMA bus clock and reset
# ---------------------------------------------------------------------------
SYSTEM_PERIP_CLK_EN1 = SYSTEM_BASE + 0x1C
SYSTEM_PERIP_RST_EN1 = SYSTEM_BASE + 0x24

SYSTEM_DMA_CLK_EN = 1 << 6       # GDMA (general purpose DMA)
SYSTEM_LCD_CAM_CLK_EN = 1 << 8
SYSTEM_DMA_RST = 1 << 6
SYSTEM_LCD_CAM_RST = 1 << 8

# Both clocks are off at reset on this chip (ESP-IDF turns them on from
# gdma_new_channel() / esp_lcd_new_rgb_panel()).

# ---------------------------------------------------------------------------
# LCD_CAM (soc/lcd_cam_struct.h), offsets from LCD_CAM_BASE
# ---------------------------------------------------------------------------
LCD_CLOCK = const(0x00)
CAM_CTRL = const(0x04)
CAM_CTRL1 = const(0x08)
CAM_RGB_YUV = const(0x0C)
LCD_RGB_YUV = const(0x10)
LCD_USER = const(0x14)
LCD_MISC = const(0x18)
LCD_CTRL = const(0x1C)
LCD_CTRL1 = const(0x20)
LCD_CTRL2 = const(0x24)
LCD_CMD_VAL = const(0x28)
LCD_DLY_MODE = const(0x30)
LCD_DATA_DOUT_MODE = const(0x38)
LC_DMA_INT_ENA = const(0x64)
LC_DMA_INT_RAW = const(0x68)
LC_DMA_INT_ST = const(0x6C)
LC_DMA_INT_CLR = const(0x70)
LC_REG_DATE = const(0xFC)

# LCD_CAM interrupt bits (lc_dma_int_*).  ESP-IDF enables VSYNC_END in
# rgb_panel_init() so its ISR can run the vsync callback / pclk update; the
# bit is inert here because nothing routes the LCD_CAM interrupt to a CPU.
LCD_INT_VSYNC_ENA = 1 << 0
LCD_INT_TRANS_DONE_ENA = 1 << 1

# LCD_USER bits
LCD_USER_ALWAYS_OUT_EN = 1 << 13
LCD_USER_2BYTE_EN = 1 << 23
LCD_USER_DOUT = 1 << 24
LCD_USER_UPDATE = 1 << 20
LCD_USER_START = 1 << 27
LCD_USER_RESET = 1 << 28

# LCD_MISC bits
LCD_MISC_NEXT_FRAME_EN = 1 << 25
LCD_MISC_BK_EN = 1 << 26
LCD_MISC_AFIFO_RST = 1 << 27
LCD_MISC_AFIFO_THRESH_DEFAULT = const(11)  # value the working firmware ends up with

# LCD_CLOCK bits
LCD_CLOCK_CLKCNT_N_SHIFT = const(0)
LCD_CLOCK_EQU_SYSCLK = 1 << 6
LCD_CLOCK_IDLE_EDGE = 1 << 7
LCD_CLOCK_OUT_EDGE = 1 << 8
LCD_CLOCK_DIV_NUM_SHIFT = const(9)
LCD_CLOCK_DIV_B_SHIFT = const(17)
LCD_CLOCK_DIV_A_SHIFT = const(23)
LCD_CLOCK_CLK_SEL_SHIFT = const(29)
LCD_CLOCK_CLK_EN = 1 << 31

LCD_CLK_SRC_XTAL = const(0)
LCD_CLK_SRC_PLL240M = const(2)
LCD_CLK_SRC_PLL160M = const(3)

PLL160M_HZ = const(160_000_000)
LCD_LL_CLK_FRAC_DIV_N_MAX = const(256)   # div_num is 8 bits
LCD_LL_CLK_FRAC_DIV_AB_MAX = const(64)   # div_a / div_b are 6 bits

# ---------------------------------------------------------------------------
# GDMA (soc/gdma_struct.h), channel stride 0xC0
# ---------------------------------------------------------------------------
GDMA_CH_STRIDE = const(0xC0)
GDMA_OUT_CONF0 = const(0x60)
GDMA_OUT_CONF1 = const(0x64)
GDMA_OUT_INT_RAW = const(0x68)
GDMA_OUT_INT_ENA = const(0x70)
GDMA_OUTFIFO_STATUS = const(0x78)
GDMA_OUT_LINK = const(0x80)
GDMA_OUT_STATE = const(0x84)
GDMA_OUT_PERI_SEL = const(0xA8)

# OUT_INT_ENA bit that ESP-IDF enables for the LCD link list (it needs the
# SUC_EOF event to know the frame has been handed to the LCD controller).
GDMA_INT_SUC_EOF = 1 << 1

GDMA_OUT_CONF0_DEFAULT = const(0x30)    # outdscr_burst_en | out_data_burst_en
GDMA_OUT_CONF1_DEFAULT = const(0x4000)  # out_ext_mem_bk_size = 64 bytes

GDMA_PERIPH_LCD_CAM = const(5)
GDMA_DESC_MAX_CHUNK = const(4095)       # LCD_DMA_DESCRIPTOR_BUFFER_MAX_SIZE
GDMA_DESC_SIZE = const(12)

# Byte offsets of the three words inside a descriptor:
#   +0  size (12) | length (12) | owner (31)   <- control word
#   +4  buffer address
#   +8  next descriptor address - a *full* 32-bit pointer, not windowed like
#       OUT_LINK, which is why a hand-off (see gdma.link_to) is a single
#       aligned 32-bit store.
GDMA_DESC_NEXT = const(8)

# Descriptor link addresses are only 20 bits wide; the hardware reconstructs
# the full address as 0x3FC00000 | addr.  Descriptors therefore MUST live in
# internal DRAM.
GDMA_DESC_WINDOW_BASE = const(0x3FC00000)
GDMA_DESC_WINDOW_MASK = const(0x000FFFFF)

# ---------------------------------------------------------------------------
# EXTMEM data-cache sync (soc/extmem_reg.h)
# ---------------------------------------------------------------------------
DCACHE_SYNC_CTRL = EXTMEM_BASE + 0x28
EXTMEM_DCACHE_SYNC_ADDR = EXTMEM_BASE + 0x2C
EXTMEM_DCACHE_SYNC_SIZE = EXTMEM_BASE + 0x30

CACHE_SYNC_INVALIDATE = 1 << 0
CACHE_SYNC_WRITEBACK = 1 << 1
CACHE_SYNC_CLEAN = 1 << 2
CACHE_SYNC_DONE = 1 << 3

# Data-cache block (line) size in bytes, measured on this chip (an invalidate
# of one block at base+16 drops the line holding base, an invalidate at
# base+32 does not).
DCACHE_BLOCK_SIZE = const(32)

# ---------------------------------------------------------------------------
# Board wiring (Guition ESP32-S3-4848S040, from the vendor Arduino demo)
# ---------------------------------------------------------------------------
DATA_PINS = (4, 5, 6, 7, 15, 8, 20, 3, 46, 9, 10, 11, 12, 13, 14, 0)
HSYNC_PIN = const(16)
VSYNC_PIN = const(17)
DE_PIN = const(18)
PCLK_PIN = const(21)
BACKLIGHT_PIN = const(38)

SPI_CS_PIN = const(39)
SPI_SCK_PIN = const(48)
SPI_SDA_PIN = const(47)

# Internal-DRAM window: descriptor lists must live here (see gdma above).
INTERNAL_DRAM_START = const(0x3FC00000)
INTERNAL_DRAM_END = const(0x40000000)


# ======================================================================
# gpio matrix
# ======================================================================
# Route LCD_CAM output signals onto physical GPIOs via the GPIO matrix.

def enable_output(pin):
    """Make `pin` a plain-GPIO output that the output register can drive.

    Two things have to line up for that: the pad's IO_MUX ``MCU_SEL`` field
    has to select the GPIO function (otherwise the pad is wired to whatever
    the IO_MUX's own function is and the GPIO matrix never reaches it), and
    the GPIO ``ENABLE`` bit has to be set.

    ``MCU_SEL`` does *not* reset to the GPIO function on every pin.  GPIO39,
    the ST7701's chip-select, resets to 0, so without this the 3-wire init
    is bit-banged into a pad that ignores it - and the panel only appears to
    work because it kept an earlier (Arduino) configuration across warm
    reboots.  A cold boot then comes up blank.
    """
    reg = IO_MUX_GPIO0_REG + 4 * pin
    mem32[reg] = (mem32[reg] & ~MCU_SEL_MASK) | MCU_SEL_GPIO | FUN_IE
    if pin < 32:
        mem32[GPIO_ENABLE_W1TS] = 1 << pin
    else:
        mem32[GPIO_ENABLE1_W1TS] = 1 << (pin - 32)


def route_output(pin, signal):
    """Connect peripheral `signal` to `pin` as an output, and enable the pad."""
    mem32[GPIO_FUNC0_OUT_SEL_CFG + 4 * pin] = signal
    enable_output(pin)


def disconnect(pin):
    """Drive `pin` from the plain GPIO output register (SIG_GPIO_OUT)."""
    mem32[GPIO_FUNC0_OUT_SEL_CFG + 4 * pin] = SIG_GPIO_OUT
    enable_output(pin)


def set_level(pin, level):
    """Drive a plain-GPIO pin high/low without allocating a machine.Pin."""
    word = 0 if pin < 32 else 1
    bit = pin if word == 0 else pin - 32
    if level:
        reg = GPIO_BASE + (0x08 if word == 0 else 0x14)
    else:
        reg = GPIO_BASE + (0x0C if word == 0 else 0x18)
    mem32[reg] = 1 << bit


# ======================================================================
# st7701
# ======================================================================
class st7701:
    """ST7701S panel bring-up over bit-banged 3-wire (9-bit) SPI.

    The ST7701 command interface is not a normal 8-bit SPI link: each frame
    is one D/C bit followed by 8 data bits (MSB first).  ESP-IDF's SPI master
    cannot send 9-bit frames, which is why Arduino_GFX bit-bangs it on
    GPIOs - and so do we.

    The sequence below is ``st7701_type1_init_operations`` from Arduino_GFX /
    Arduino_ST7701_RGBPanel, byte for byte identical to the working custom C
    module (lcd/hal/esp32/esp32.c).
    """

    INIT_SEQUENCE = (
        # PAGE 0
        (0xFF, (0x77, 0x01, 0x00, 0x00, 0x10)),
        (0xC0, (0x3B, 0x00)),
        (0xC1, (0x0D, 0x02)),
        (0xC2, (0x31, 0x05)),
        (0xCD, (0x00,)),
        (0xB0, (0x00, 0x11, 0x18, 0x0E, 0x11, 0x06, 0x07, 0x08,
                0x07, 0x22, 0x04, 0x12, 0x0F, 0xAA, 0x31, 0x18)),
        (0xB1, (0x00, 0x11, 0x19, 0x0E, 0x12, 0x07, 0x08, 0x08,
                0x08, 0x22, 0x04, 0x11, 0x11, 0xA9, 0x32, 0x18)),
        # PAGE 1
        (0xFF, (0x77, 0x01, 0x00, 0x00, 0x11)),
        (0xB0, (0x60,)),
        (0xB1, (0x32,)),
        (0xB2, (0x07,)),
        (0xB3, (0x80,)),
        (0xB5, (0x49,)),
        (0xB7, (0x85,)),
        (0xB8, (0x21,)),
        (0xC1, (0x78,)),
        (0xC2, (0x78,)),
        (0xE0, (0x00, 0x1B, 0x02)),
        (0xE1, (0x08, 0xA0, 0x00, 0x00, 0x07, 0xA0, 0x00, 0x00, 0x00, 0x44, 0x44)),
        (0xE2, (0x11, 0x11, 0x44, 0x44, 0xED, 0xA0, 0x00, 0x00,
                0xEC, 0xA0, 0x00, 0x00)),
        (0xE3, (0x00, 0x00, 0x11, 0x11)),
        (0xE4, (0x44, 0x44)),
        (0xE5, (0x0A, 0xE9, 0xD8, 0xA0, 0x0C, 0xEB, 0xD8, 0xA0,
                0x0E, 0xED, 0xD8, 0xA0, 0x10, 0xEF, 0xD8, 0xA0)),
        (0xE6, (0x00, 0x00, 0x11, 0x11)),
        (0xE7, (0x44, 0x44)),
        (0xE8, (0x09, 0xE8, 0xD8, 0xA0, 0x0B, 0xEA, 0xD8, 0xA0,
                0x0D, 0xEC, 0xD8, 0xA0, 0x0F, 0xEE, 0xD8, 0xA0)),
        (0xEB, (0x02, 0x00, 0xE4, 0xE4, 0x88, 0x00, 0x40)),
        (0xEC, (0x3C, 0x00)),
        (0xED, (0xAB, 0x89, 0x76, 0x54, 0x02, 0xFF, 0xFF, 0xFF,
                0xFF, 0xFF, 0xFF, 0x20, 0x45, 0x67, 0x98, 0xBA)),
        # VAP & VAN (bank 0x13)
        (0xFF, (0x77, 0x01, 0x00, 0x00, 0x13)),
        (0xE5, (0xE4,)),
        # back to bank 0, then RGB666 (0x60); 0x70 would be RGB888, 0x50 RGB565
        (0xFF, (0x77, 0x01, 0x00, 0x00, 0x00)),
        (0x3A, (0x60,)),
    )

    class Wire:
        """Bit-banged 3-wire (9-bit) SPI on three plain GPIO outputs.

        Frame layout: D/C bit first (0 = command, 1 = data), then 8 data
        bits, MSB first.  Data is driven while SCK is low and sampled by the
        panel on the rising edge, exactly like Arduino_ESP32RGBPanel.
        """

        def __init__(self, cs=SPI_CS_PIN, sck=SPI_SCK_PIN, sda=SPI_SDA_PIN):
            self.cs = cs
            self.sck = sck
            self.sda = sda
            self.cs_set, self.cs_clr, self.m_cs = self._pin(cs)
            self.sck_set, self.sck_clr, self.m_sck = self._pin(sck)
            self.sda_set, self.sda_clr, self.m_sda = self._pin(sda)

            for pin in (cs, sck, sda):
                mem32[GPIO_FUNC0_OUT_SEL_CFG + 4 * pin] = SIG_GPIO_OUT
                enable_output(pin)

            # idle levels: CS high (deselected), SCK low, SDA low
            mem32[self.cs_set] = self.m_cs
            mem32[self.sck_clr] = self.m_sck
            mem32[self.sda_clr] = self.m_sda

        @staticmethod
        def _pin(pin):
            """Return (set-register, clear-register, bit mask) for a GPIO pin."""
            if pin < 32:
                return (GPIO_BASE + 0x08, GPIO_BASE + 0x0C, 1 << pin)
            return (GPIO_BASE + 0x14, GPIO_BASE + 0x18, 1 << (pin - 32))

        def cs_level(self, level):
            mem32[self.cs_set if level else self.cs_clr] = self.m_cs

        def _sda(self, level):
            mem32[self.sda_set if level else self.sda_clr] = self.m_sda

        def _sck_pulse(self):
            mem32[self.sck_set] = self.m_sck
            mem32[self.sck_clr] = self.m_sck

        def write9(self, dc, b):
            """Send one 9-bit frame: the D/C bit followed by 8 data bits."""
            self._sda(dc)
            self._sck_pulse()
            for bit in (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01):
                self._sda(1 if (b & bit) else 0)
                self._sck_pulse()

        def command(self, cmd, data=()):
            self.write9(0, cmd)
            for b in data:
                self.write9(1, b)

        def raw(self, dc, b):
            self.write9(dc, b)

    @classmethod
    def init(cls, cs=SPI_CS_PIN, sck=SPI_SCK_PIN, sda=SPI_SDA_PIN, verbose=False):
        """Run the exact ST7701 bring-up sequence used by the working firmware."""
        wire = cls.Wire(cs, sck, sda)

        # Software reset (the board has no hardware reset line), 120 ms recovery.
        wire.cs_level(0)
        wire.raw(0, 0x01)
        wire.cs_level(1)
        time.sleep_ms(120)

        # The whole init table, CS held low for the duration (batchOperation).
        wire.cs_level(0)
        for cmd, data in cls.INIT_SEQUENCE:
            wire.command(cmd, data)
        time.sleep_ms(10)
        wire.raw(0, 0x11)                 # sleep out
        wire.cs_level(1)
        time.sleep_ms(120)

        wire.cs_level(0)
        wire.raw(0, 0x29)                 # display on
        wire.cs_level(1)

        # invertDisplay(false) on an IPS panel -> 0x20 (inversion off)
        wire.cs_level(0)
        wire.raw(0, 0x20)
        wire.cs_level(1)

        # setRotation(0) with bgr=true: Y-direction bank, C7 = 0, back to
        # bank 0, MADCTL = 0x00 (all in one CS-low block)
        wire.cs_level(0)
        wire.command(0xFF, (0x77, 0x01, 0x00, 0x00, 0x10))
        wire.command(0xC7, (0x00,))
        wire.command(0xFF, (0x77, 0x01, 0x00, 0x00, 0x00))
        wire.command(0x36, (0x00,))
        wire.cs_level(1)

        if verbose:
            print("st7701: init sequence complete")
        return wire


# ======================================================================
# lcd_cam
# ======================================================================
class lcd_cam:
    """LCD_CAM RGB-panel programming for the ESP32-S3.

    Everything here mirrors what ESP-IDF v5.5.5 does in
    ``esp_lcd_new_rgb_panel()`` + ``rgb_panel_init()``
    (``esp_lcd_panel_rgb.c`` and ``lcd_ll.h``), using the LL register layout
    from ``lcd_cam_struct.h``.

    The register values produced by `configure()` were checked field by field
    against a dump taken from the working custom C module - see
    docs/register_map.md.
    """

    # ------------------------------------------------------------------
    # clock tree
    # ------------------------------------------------------------------
    @staticmethod
    def calc_clk_div(src_freq, exp_freq, max_integ, min_integ, max_fract):
        """Approximate ``src_freq / exp_freq`` as ``integer + numerator/denominator``.

        This is the same fractional-divider search ESP-IDF performs in
        ``hal_utils_calc_clk_div_frac_fast()``.  Returns
        ``(integer, denominator, numerator)`` or ``None`` when the ratio
        cannot be represented within the given ranges.
        """
        if not exp_freq:
            return None
        ratio = src_freq / exp_freq
        integer = int(ratio)
        if integer < min_integ or integer >= max_integ:
            return None
        frac = ratio - integer

        num, den, err = 0, 1, abs(frac)
        if frac > 1e-12:
            for d in range(2, max_fract):
                n = int(frac * d + 0.5)
                if n >= max_fract:
                    break
                if n == 0:
                    continue
                e = abs(frac - n / d)
                if e < err - 1e-12:
                    num, den, err = n, d, e
                if err <= 1e-12:
                    break
        return integer, den, num

    @classmethod
    def cal_pclk_div(cls, src_freq, pclk_hz):
        """Return ``(prescale, (integer, denominator, numerator), real_pclk_hz)``.

        Same two-step search as ``lcd_hal_cal_pclk_freq()``: prefer prescale
        2, then unwind to a bigger prescale if the divider cannot express
        the target.
        """
        mo = 2
        res = cls.calc_clk_div(src_freq, pclk_hz * mo,
                               LCD_LL_CLK_FRAC_DIV_N_MAX, 2,
                               LCD_LL_CLK_FRAC_DIV_AB_MAX)
        if res is None:
            mo = src_freq // pclk_hz // LCD_LL_CLK_FRAC_DIV_N_MAX + 1
            res = cls.calc_clk_div(src_freq, pclk_hz * mo,
                                   LCD_LL_CLK_FRAC_DIV_N_MAX, 2,
                                   LCD_LL_CLK_FRAC_DIV_AB_MAX)
        if res is None:
            raise ValueError(f"cannot achieve {pclk_hz} Hz pixel clock")
        integer, den, num = res
        real = src_freq / (integer + num / den)
        return mo, res, real / mo

    # ------------------------------------------------------------------
    # bus clock / reset
    # ------------------------------------------------------------------
    @staticmethod
    def enable_bus_clock(en=True):
        v = mem32[SYSTEM_PERIP_CLK_EN1]
        v = (v | SYSTEM_LCD_CAM_CLK_EN) if en else (v & ~SYSTEM_LCD_CAM_CLK_EN)
        mem32[SYSTEM_PERIP_CLK_EN1] = v & 0xFFFFFFFF

    @staticmethod
    def reset_peripheral():
        """Assert then de-assert the LCD_CAM peripheral reset.

        The peripheral reset also restores the hardware defaults of every
        LCD_CAM register (that is where things like the async-FIFO threshold
        come from), so it has to run before the registers are programmed.
        """
        v = mem32[SYSTEM_PERIP_RST_EN1]
        mem32[SYSTEM_PERIP_RST_EN1] = (v | SYSTEM_LCD_CAM_RST) & 0xFFFFFFFF
        mem32[SYSTEM_PERIP_RST_EN1] = (v & ~SYSTEM_LCD_CAM_RST) & 0xFFFFFFFF

    # ------------------------------------------------------------------
    # individual registers
    # ------------------------------------------------------------------
    @classmethod
    def configure_clock(cls, pclk_hz=11_000_000, src_hz=PLL160M_HZ,
                        clk_sel=LCD_CLK_SRC_PLL160M,
                        pclk_idle_high=False, pclk_active_neg=False):
        """Program LCD_CAM_LCD_CLOCK: source, fractional divider and prescale.

        The LCD clock runs at ``pclk * prescale`` so the panel gets a pixel
        clock of `pclk_hz`; for 16-bit RGB, prescale 2 is the preferred (and
        here, achievable) value.
        """
        prescale, (div_num, div_a, div_b), real = cls.cal_pclk_div(src_hz, pclk_hz)
        val = ((clk_sel & 3) << LCD_CLOCK_CLK_SEL_SHIFT) \
            | ((div_a & 0x3F) << LCD_CLOCK_DIV_A_SHIFT) \
            | ((div_b & 0x3F) << LCD_CLOCK_DIV_B_SHIFT) \
            | ((div_num & 0xFF) << LCD_CLOCK_DIV_NUM_SHIFT)
        if prescale > 1:
            val |= (prescale - 1) & 0x3F
        else:
            val |= LCD_CLOCK_EQU_SYSCLK
        if pclk_idle_high:
            val |= LCD_CLOCK_IDLE_EDGE
        if pclk_active_neg:
            val |= LCD_CLOCK_OUT_EDGE
        val |= LCD_CLOCK_CLK_EN
        mem32[LCD_CAM_BASE + LCD_CLOCK] = val
        return val, real

    @staticmethod
    def configure(width=480, height=480, *,
                  hsync_pulse_width=8, hsync_back_porch=50, hsync_front_porch=10,
                  vsync_pulse_width=8, vsync_back_porch=20, vsync_front_porch=10,
                  hsync_idle_low=False, vsync_idle_low=False, de_idle_high=False):
        """Program the LCD_CAM timing registers and enable RGB mode."""
        hsw, hbp, hfp = hsync_pulse_width, hsync_back_porch, hsync_front_porch
        vsw, vbp, vfp = vsync_pulse_width, vsync_back_porch, vsync_front_porch

        # ll_set_horizontal_timing / lcd_ll_set_vertical_timing: everything
        # is stored "minus one" because the counters are inclusive.
        hb_front = hbp + hsw - 1
        ha_width = width - 1
        ht_width = hsw + hbp + width + hfp - 1
        vb_front = vbp + vsw - 1
        va_height = height - 1
        vt_height = vsw + vbp + height + vfp - 1

        ctrl = (hb_front & 0x7FF) \
            | ((va_height & 0x3FF) << 11) \
            | ((vt_height & 0x3FF) << 21) \
            | (1 << 31)                       # lcd_rgb_mode_en
        mem32[LCD_CAM_BASE + LCD_CTRL] = ctrl

        ctrl1 = (vb_front & 0xFF) \
            | ((ha_width & 0xFFF) << 8) \
            | ((ht_width & 0xFFF) << 20)
        mem32[LCD_CAM_BASE + LCD_CTRL1] = ctrl1

        ctrl2 = (vsw - 1) & 0x7F
        if not vsync_idle_low:
            ctrl2 |= 1 << 7
        if de_idle_high:
            ctrl2 |= 1 << 8
        ctrl2 |= 1 << 9                       # lcd_hs_blank_en
        ctrl2 |= ((hsw - 1) & 0x7F) << 16
        if not hsync_idle_low:
            ctrl2 |= 1 << 23
        # lcd_hsync_position stays 0
        mem32[LCD_CAM_BASE + LCD_CTRL2] = ctrl2

        # LCD_MISC: keep the hardware async-FIFO threshold, enable the blank
        # region and continuous ("next") frames.
        misc = ((LCD_MISC_AFIFO_THRESH_DEFAULT << 1)
                | LCD_MISC_NEXT_FRAME_EN | LCD_MISC_BK_EN)
        mem32[LCD_CAM_BASE + LCD_MISC] = misc

        # pass-through values for the unused camera / YUV-convert paths
        # (these are the values the hardware settles on after the reset)
        mem32[LCD_CAM_BASE + CAM_CTRL] = 0x00000800
        mem32[LCD_CAM_BASE + CAM_RGB_YUV] = 0x00C00000
        mem32[LCD_CAM_BASE + LCD_RGB_YUV] = 0x00C00000

        # LCD_USER: 16-bit data phase that runs as long as DMA has data
        mem32[LCD_CAM_BASE + LCD_USER] = (LCD_USER_ALWAYS_OUT_EN
                                         | LCD_USER_2BYTE_EN
                                         | LCD_USER_DOUT)
        return ctrl, ctrl1, ctrl2

    @staticmethod
    def enable_interrupts(en=True):
        """Enable the LCD_CAM frame-end interrupt, like IDF's rgb_panel_init().

        ESP-IDF installs an ISR here to run the vsync callback and to re-tune
        pclk; a pure driver has no ISR, so the bit is inert (the LCD_CAM's
        interrupt is not routed to a CPU by anything we do).
        """
        if en:
            mem32[LCD_CAM_BASE + LC_DMA_INT_ENA] = LCD_INT_VSYNC_ENA
            mem32[LCD_CAM_BASE + LC_DMA_INT_CLR] = 0xFFFFFFFF
        else:
            mem32[LCD_CAM_BASE + LC_DMA_INT_ENA] = 0
            mem32[LCD_CAM_BASE + LC_DMA_INT_CLR] = 0xFFFFFFFF

    @staticmethod
    def configure_gpio(data_pins, hsync, vsync, de, pclk):
        """Route the 16 data lines + HSYNC/VSYNC/DE/PCLK via the GPIO matrix."""
        for i, pin in enumerate(data_pins):
            route_output(pin, LCD_DATA_OUT0_IDX + i)
        route_output(hsync, LCD_H_SYNC_IDX)
        route_output(vsync, LCD_V_SYNC_IDX)
        route_output(de, LCD_H_ENABLE_IDX)
        route_output(pclk, LCD_PCLK_IDX)

    # ------------------------------------------------------------------
    # transaction control (mirrors lcd_ll_start/stop/reset/fifo_reset)
    # ------------------------------------------------------------------
    @staticmethod
    def stop():
        v = mem32[LCD_CAM_BASE + LCD_USER]
        mem32[LCD_CAM_BASE + LCD_USER] = (v & ~LCD_USER_START) | LCD_USER_UPDATE

    @staticmethod
    def reset():
        v = mem32[LCD_CAM_BASE + LCD_USER]
        mem32[LCD_CAM_BASE + LCD_USER] = v | LCD_USER_RESET

    @staticmethod
    def fifo_reset():
        v = mem32[LCD_CAM_BASE + LCD_MISC]
        mem32[LCD_CAM_BASE + LCD_MISC] = v | LCD_MISC_AFIFO_RST

    @staticmethod
    def start():
        v = mem32[LCD_CAM_BASE + LCD_USER]
        mem32[LCD_CAM_BASE + LCD_USER] = v | LCD_USER_UPDATE | LCD_USER_START

    @staticmethod
    def user_register():
        return mem32[LCD_CAM_BASE + LCD_USER]


# ======================================================================
# gdma
# ======================================================================
class gdma:
    """GDMA "send" channel driving the LCD_CAM peripheral.

    ESP-IDF builds one link-list descriptor per ~4 KB of framebuffer and
    points the LCD_CAM's DMA request at it (``gdma_connect(chan,
    GDMA_TRIG_PERIPH_LCD)`` == ``GDMA_OUT_PERI_SEL = 5``).

    Two hardware details drive the design here:

    * ``OUT_LINK.addr`` is only 20 bits wide; the hardware rebuilds the
      address as ``0x3FC00000 | addr``.  Descriptors therefore *must* live
      in internal DRAM.  (The descriptor's own 32-bit ``next`` pointer is a
      full address.)
    * Each descriptor owns one buffer of at most 4095 bytes
      (``LCD_DMA_DESCRIPTOR_BUFFER_MAX_SIZE``), which is exactly how IDF
      splits a full-screen framebuffer.

    For double buffering there is one such list per framebuffer, each closed
    on itself, and handing the DMA the next frame is a single 32-bit store
    (`link_to`) - the same trick as IDF's ``gdma_link_concat()``.  See
    :func:`build_lists`.
    """

    LINK_STOP = 1 << 20
    LINK_START = 1 << 21

    # ------------------------------------------------------------------
    # bus clock / peripheral reset (gdma_ll_enable_bus_clock / _reset_register)
    # ------------------------------------------------------------------
    @staticmethod
    def enable_bus_clock(en=True):
        v = mem32[SYSTEM_PERIP_CLK_EN1]
        v = (v | SYSTEM_DMA_CLK_EN) if en else (v & ~SYSTEM_DMA_CLK_EN)
        mem32[SYSTEM_PERIP_CLK_EN1] = v & 0xFFFFFFFF

    @staticmethod
    def reset_peripheral():
        """Assert then de-assert the GDMA peripheral reset.

        This is what ESP-IDF's ``gdma_ll_reset_register()`` does, and it
        puts every channel (not just ours) into its hardware default state.
        """
        v = mem32[SYSTEM_PERIP_RST_EN1]
        mem32[SYSTEM_PERIP_RST_EN1] = v | SYSTEM_DMA_RST
        mem32[SYSTEM_PERIP_RST_EN1] = (v & ~SYSTEM_DMA_RST) & 0xFFFFFFFF

    # ------------------------------------------------------------------
    # descriptor link lists
    # ------------------------------------------------------------------
    @staticmethod
    def descriptor_count(fb_len, chunk=GDMA_DESC_MAX_CHUNK):
        return (fb_len + chunk - 1) // chunk

    @classmethod
    def descriptor_bytes(cls, fb_len, chunk=GDMA_DESC_MAX_CHUNK):
        """Bytes of internal RAM needed for the framebuffer's descriptor list."""
        return cls.descriptor_count(fb_len, chunk) * GDMA_DESC_SIZE

    @classmethod
    def build_lists(cls, buf, buf_addr, fb_addrs, fb_len,
                    chunk=GDMA_DESC_MAX_CHUNK):
        """Build one self-circular descriptor list per framebuffer.

        Each list covers the whole framebuffer and ends by pointing back at
        its *own* first descriptor, so on its own a list is a closed ring:
        once the DMA enters it, it keeps re-sending that frame forever with
        no CPU help.

        That self-reference is what makes a frame swap a single store (see
        :func:`link_to`): because every list can stand alone, pointing
        another list's tail at this one's head is always a legal hand-off.

        The lists are laid out one after another inside ``buf``; ``heads``
        and ``tails`` give the byte address of each list's first and last
        descriptor.  Returns ``(n, heads, tails)`` where ``n`` is the number
        of descriptors per list.
        """
        n = cls.descriptor_count(fb_len, chunk)
        stride = n * GDMA_DESC_SIZE
        if len(buf) < stride * len(fb_addrs):
            raise ValueError(f"descriptor buffer too small "
                             f"({len(buf)} < {stride * len(fb_addrs)})")
        if not (GDMA_DESC_WINDOW_BASE <= buf_addr
                <= GDMA_DESC_WINDOW_BASE + GDMA_DESC_WINDOW_MASK):
            raise ValueError(f"descriptor list must be in internal DRAM, "
                             f"got 0x{buf_addr:08x}")

        pack_into = struct.pack_into
        heads = []
        tails = []
        for k, fb_addr in enumerate(fb_addrs):
            base = buf_addr + k * stride                   # this list's head
            off = 0
            for i in range(n):
                size = min(chunk, fb_len - off)
                nxt = base + GDMA_DESC_SIZE * ((i + 1) % n)
                dw0 = (size & 0xFFF) | ((size & 0xFFF) << 12) | (1 << 31)
                if i == n - 1:
                    dw0 |= 1 << 30             # suc_eof: frame fully queued
                pack_into("<III", buf, k * stride + i * GDMA_DESC_SIZE,
                          dw0, fb_addr + off, nxt)
                off += size
            heads.append(base)
            tails.append(base + GDMA_DESC_SIZE * (n - 1))
        return n, heads, tails

    @classmethod
    def build_circular_list(cls, buf, buf_addr, fb_addr, fb_len,
                            chunk=GDMA_DESC_MAX_CHUNK):
        """Fill `buf` (a bytearray living at `buf_addr`) with a circular list.

        The last descriptor is marked ``suc_eof`` and points back at the
        first one, which is what lets the LCD_CAM keep re-sending the frame
        forever without any CPU involvement (``lcd_next_frame_en``).

        Returns the number of descriptors written.
        """
        return cls.build_lists(buf, buf_addr, (fb_addr,), fb_len, chunk)[0]

    @staticmethod
    def link_to(desc_addr, next_addr):
        """Point one descriptor at another by rewriting its ``next`` word.

        ``next`` is a full 32-bit address at byte offset 8 of a 12-byte
        descriptor.  Descriptors are built at a 4-byte-aligned address, so
        this is a single aligned 32-bit store - the only thing the CPU has
        to do to hand the DMA a new frame.  The descriptors live in internal
        DRAM, which is not behind the data cache, so the DMA sees the new
        value immediately without any cache writeback.

        This is ESP-IDF's ``gdma_link_concat(list, -1, other, 0)``.
        """
        mem32[desc_addr + GDMA_DESC_NEXT] = next_addr & 0xFFFFFFFF

    class Channel:
        """The LCD_CAM's GDMA "out" channel (channel 0 on this board)."""

        def __init__(self, channel=0, peri=GDMA_PERIPH_LCD_CAM,
                     conf0=GDMA_OUT_CONF0_DEFAULT, conf1=GDMA_OUT_CONF1_DEFAULT,
                     interrupts=True):
            self.channel = channel
            self.base = GDMA_BASE + channel * GDMA_CH_STRIDE
            self.conf0 = conf0
            self.conf1 = conf1
            mem32[self.base + GDMA_OUT_PERI_SEL] = peri
            self.apply()
            if interrupts:
                # esp_lcd registers a TX callback, which makes the DMA layer
                # enable SUC_EOF.  Nothing consumes the interrupt here (the
                # channel's interrupt is not routed to a CPU), but matching
                # IDF keeps the register dump identical.
                mem32[self.base + GDMA_OUT_INT_ENA] = GDMA_INT_SUC_EOF

        def apply_conf0(self, value):
            self.conf0 = value
            mem32[self.base + GDMA_OUT_CONF0] = value

        def apply(self):
            """Program OUT_CONF1 (external-memory block size) and OUT_CONF0."""
            mem32[self.base + GDMA_OUT_CONF1] = self.conf1
            mem32[self.base + GDMA_OUT_CONF0] = self.conf0

        def reset(self):
            """Pulse ``out_rst`` to clear the channel state and its FIFO."""
            mem32[self.base + GDMA_OUT_CONF0] = 1 << 0
            mem32[self.base + GDMA_OUT_CONF0] = self.conf0

        def start(self, desc_addr):
            mem32[self.base + GDMA_OUT_LINK] = (
                (desc_addr & GDMA_DESC_WINDOW_MASK) | gdma.LINK_START)

        def stop(self):
            mem32[self.base + GDMA_OUT_LINK] = gdma.LINK_STOP

        def link_address(self):
            return mem32[self.base + GDMA_OUT_LINK] & GDMA_DESC_WINDOW_MASK

        def state(self):
            return mem32[self.base + GDMA_OUT_STATE]

        def fifo_status(self):
            return mem32[self.base + GDMA_OUTFIFO_STATUS]


# ======================================================================
# internal_ram
# ======================================================================
# Obtain real internal DRAM from pure MicroPython.
#
# Why this is needed
# ------------------
# The GDMA descriptor link address register is only 20 bits wide: the
# hardware reconstructs a descriptor address as ``0x3FC00000 | addr[19:0]``.
# PSRAM is mapped at ``0x3C000000``, which is simply not reachable from that
# register, so the descriptor list *must* live in internal DRAM
# (``0x3FC00000 .. 0x3FCFFFFF``).
#
# Stock MicroPython gives Python code no API to request internal RAM: the GC
# split-heap is grown with ``malloc()``, and IDF satisfies that from PSRAM
# while PSRAM still has room.
#
# The trick
# ---------
# When PSRAM runs out, MicroPython's ``gc_try_add_heap()`` still tries to
# grow the heap.  By then ``gc_get_max_new_split()`` (the largest free
# block) has become small, so the requested heap area is small too - and
# ``malloc()`` falls back to internal DRAM for it.  Everything allocated in
# that new area lands in internal DRAM.
#
# So: fill the GC heap with big chunks until the allocator gives up on
# PSRAM, then with smaller chunks, and watch the address of every successful
# allocation.  The first allocation that lands inside the internal DRAM
# window is our arena - and it is a normal MicroPython object, so the GC
# keeps it alive and never moves it (MicroPython's GC is non-moving).
#
# The filler allocations are dropped again afterwards; the memory returns to
# the pool once ``gc.collect()`` sweeps it.

# Chunk sizes tried in order.  Big chunks first so PSRAM is consumed
# quickly, small ones last to force the allocator into the internal fallback.
CHUNK_SIZES = (1 << 20, 1 << 16, 1 << 12, 1 << 8)


class internal_ram:
    """Internal-DRAM arena acquisition by exhausting the GC heap."""

    @staticmethod
    def is_internal(addr):
        """True if `addr` points into ESP32-S3 internal DRAM."""
        return INTERNAL_DRAM_START <= addr < INTERNAL_DRAM_END

    @classmethod
    def grab(cls, min_bytes, verbose=False):
        """Allocate at least `min_bytes` of internal DRAM.

        Returns ``(buffer, fillers)``.  `buffer` is a bytearray whose
        *entire* backing store is internal DRAM.  `fillers` is a list of the
        PSRAM allocations that were used to push the GC into the internal
        fallback; the caller must release it (see `release()`) as soon as it
        has finished with the internal buffer, otherwise the rest of the
        heap stays pinned.
        """
        fillers = []
        try:
            for chunk in CHUNK_SIZES:
                if chunk < min_bytes:
                    continue
                while True:
                    try:
                        buf = bytearray(chunk)
                    except MemoryError:
                        break
                    addr = uctypes.addressof(buf)
                    if cls.is_internal(addr):
                        if verbose:
                            print(f"internal_ram: arena {len(buf)} bytes "
                                  f"@ 0x{addr:08x}")
                        return buf, fillers
                    fillers.append(buf)
                if verbose:
                    print(f"internal_ram: filled with {chunk}-byte chunks")
        except BaseException:
            cls.release(fillers)
            raise

        cls.release(fillers)
        raise MemoryError(f"could not obtain {min_bytes} bytes of internal "
                          f"DRAM (is PSRAM enabled?)")

    @staticmethod
    def release(fillers, collect=True):
        """Drop the filler allocations and give the memory back to the heap."""
        del fillers[:]
        if collect:
            gc.collect()

    @staticmethod
    def info():
        """Best-effort report of the internal heap regions (no addresses)."""
        try:
            import esp32
            return esp32.idf_heap_info(esp32.HEAP_DATA)
        except (ImportError, AttributeError):
            return None


# ======================================================================
# writeback
# ======================================================================
# Flush the ESP32-S3 data cache for a PSRAM range.
#
# The RGB panel's GDMA reads the framebuffer out of PSRAM without snooping
# the CPU's L1 data cache, so anything the CPU has written has to be written
# back before the DMA can see it.  ESP-IDF does exactly this in
# ``esp_lcd_panel_rgb.c`` via ``esp_cache_msync(..., DIR_C2M | UNALIGNED)``,
# which ends up in the EXTMEM_DCACHE_SYNC_* registers.
#
# The registers are asynchronous: writing an operation bit kicks off the
# operation and the bit is cleared by hardware when it has finished.

SYNC_ADDR = EXTMEM_DCACHE_SYNC_ADDR
SYNC_SIZE = EXTMEM_DCACHE_SYNC_SIZE


def writeback(addr, nbytes, block_size=DCACHE_BLOCK_SIZE, timeout=100000):
    """Flush `nbytes` starting at `addr` from the data cache back to memory.

    The hardware works in cache blocks, so the range is rounded outwards.
    Over-covering is harmless (it only writes back cache lines that are
    already dirty), under-covering would leave stale pixels behind.
    """
    if nbytes <= 0:
        return
    start = addr & ~(block_size - 1)
    end = (addr + nbytes + block_size - 1) & ~(block_size - 1)
    blocks = (end - start) // block_size

    mem32[SYNC_ADDR] = start
    mem32[SYNC_SIZE] = blocks
    mem32[DCACHE_SYNC_CTRL] = CACHE_SYNC_WRITEBACK

    # The enable bit is cleared by hardware once the operation has finished.
    n = timeout
    while mem32[DCACHE_SYNC_CTRL] & CACHE_SYNC_WRITEBACK:
        n -= 1
        if n <= 0:
            raise OSError("dcache writeback timed out")


def cache_state():
    """Return (ctrl, addr, size) - useful for validation against IDF."""
    return (mem32[DCACHE_SYNC_CTRL],
            mem32[SYNC_ADDR],
            mem32[SYNC_SIZE])


# ======================================================================
# DPI
# ======================================================================
class DPI:
    """480x480 RGB565 panel driven by LCD_CAM + GDMA.

    This runs on *stock* MicroPython with no custom C module.  It
    reproduces, register for register, the configuration that the working C
    firmware (``lcd_binding_micropython``) programs - see
    docs/register_map.md.

    Usage::

        from esp32_4848s040 import DPI
        d = DPI()                 # 480x480 ST7701, RGB565, 11 MHz PCLK
        d.fill(0xF800)            # red
        d.show()

    The framebuffer is a plain ``bytearray`` in PSRAM holding 480x480
    little-endian RGB565 words, so it can be handed straight to
    ``framebuf``::

        import framebuf
        fb = framebuf.FrameBuffer(d.fb, 480, 480, framebuf.RGB565)
        fb.text("hi", 8, 8, 0xFFFF)
        d.show()

    Pass ``fbs=2`` for double buffering: two framebuffers and two descriptor
    lists, with ``show()`` handing the DMA the finished one at a frame
    boundary, so nothing is ever drawn into the frame being scanned::

        d = DPI(fbs=2)
        while True:
            d.fill(0x001F)        # goes to the buffer that is off screen
            d.show()              # ... and this puts it on screen whole

    Layout of the moving parts (all in this file)::

        registers    register addresses / constants (flat, above)
        st7701       bit-banged 9-bit SPI panel init
        lcd_cam      LCD_CAM RGB timing + clock programming
        gdma         GDMA channel + circular descriptor list
        internal_ram internal-DRAM descriptor arena
        writeback    PSRAM data-cache writeback
        gpio matrix  GPIO matrix routing
    """

    def __init__(self,
                 width=480, height=480,
                 pclk_hz=11_000_000,
                 hsync_pulse_width=8, hsync_back_porch=50, hsync_front_porch=10,
                 vsync_pulse_width=8, vsync_back_porch=20, vsync_front_porch=10,
                 hsync_idle_low=False, vsync_idle_low=False, de_idle_high=False,
                 pclk_idle_high=False, pclk_active_neg=False,
                 data_pins=DATA_PINS,
                 hsync=HSYNC_PIN, vsync=VSYNC_PIN,
                 de=DE_PIN, pclk=PCLK_PIN,
                 backlight=BACKLIGHT_PIN,
                 spi_cs=SPI_CS_PIN, spi_sck=SPI_SCK_PIN, spi_sda=SPI_SDA_PIN,
                 panel_init=True, flush=True, verbose=True,
                 fbs=1, idf_interrupts=True):
        self.width = width
        self.height = height
        self.flush = flush
        self._backlight_pin = backlight
        self.verbose = verbose
        self.fb_size = width * height * 2
        self.fbs = max(1, int(fbs))

        # --- framebuffer(s) in PSRAM ---------------------------------
        # Allocated *first*: the internal-RAM trick below deliberately
        # exhausts PSRAM, and we do not want to depend on a contiguous
        # 450 KB run surviving that.
        self._fb = [bytearray(self.fb_size) for _ in range(self.fbs)]
        self._fb_addr = [uctypes.addressof(b) for b in self._fb]
        # Drawing goes through MicroPython's own framebuf: it is C code, so
        # fills take ~1 ms instead of the ~3 s a Python loop over a PSRAM
        # bytearray costs.  framebuf's RGB565 stores the native 16-bit word,
        # i.e. exactly the byte order the LCD_CAM's DMA expects.
        self._fbuf = [framebuf.FrameBuffer(b, width, height,
                                           framebuf.RGB565)
                      for b in self._fb]
        # Which buffer is on the panel, which one we draw into, and when each
        # buffer stops being read by the DMA (see _settle).
        self._shown = 0
        self._back = 0
        self._free_at = [0] * self.fbs
        if verbose:
            print(f"lcd: {self.fbs} framebuffer(s) x {self.fb_size} bytes "
                  f"@ 0x{self._fb_addr[0]:08x}"
                  + ("" if self.fbs == 1
                     else f" .. 0x{self._fb_addr[-1]:08x}"))

        # --- internal DRAM for the DMA descriptor list ---------------
        need = gdma.descriptor_bytes(self.fb_size) * self.fbs
        desc_buf, fillers = internal_ram.grab(need, verbose=verbose)
        self._desc = desc_buf                       # keep the GC off it
        self._desc_addr = uctypes.addressof(desc_buf)
        internal_ram.release(fillers)
        if verbose:
            print(f"lcd: descriptor list {len(desc_buf)} bytes "
                  f"@ 0x{self._desc_addr:08x}")

        # --- ST7701 register init over bit-banged 3-wire SPI ---------
        if panel_init:
            st7701.init(spi_cs, spi_sck, spi_sda, verbose=verbose)

        # --- LCD_CAM: bus clock, reset, clock tree, timings, pins ----
        lcd_cam.enable_bus_clock(True)
        lcd_cam.reset_peripheral()
        clk_val, real_pclk = lcd_cam.configure_clock(
            pclk_hz=pclk_hz, pclk_idle_high=pclk_idle_high,
            pclk_active_neg=pclk_active_neg)
        lcd_cam.configure(
            width=width, height=height,
            hsync_pulse_width=hsync_pulse_width,
            hsync_back_porch=hsync_back_porch,
            hsync_front_porch=hsync_front_porch,
            vsync_pulse_width=vsync_pulse_width,
            vsync_back_porch=vsync_back_porch,
            vsync_front_porch=vsync_front_porch,
            hsync_idle_low=hsync_idle_low, vsync_idle_low=vsync_idle_low,
            de_idle_high=de_idle_high)
        lcd_cam.configure_gpio(data_pins, hsync, vsync, de, pclk)
        lcd_cam.enable_interrupts(idf_interrupts)

        # --- GDMA channel + circular descriptor list -----------------
        gdma.enable_bus_clock(True)
        gdma.reset_peripheral()
        self.dma = gdma.Channel(interrupts=idf_interrupts)
        self.num_desc, self._desc_head, self._desc_tail = gdma.build_lists(
            self._desc, self._desc_addr, self._fb_addr, self.fb_size)

        # One full refresh: htotal * vtotal pixels at the *real* PCLK.  Used
        # to know how long a frame that has just been handed to the DMA is
        # still being read out of its old framebuffer.
        htotal = (hsync_pulse_width + hsync_back_porch + width
                  + hsync_front_porch)
        vtotal = (vsync_pulse_width + vsync_back_porch + height
                  + vsync_front_porch)
        self.refresh_hz = real_pclk / (htotal * vtotal)
        self.frame_us = int(htotal * vtotal / real_pclk * 1e6 + 0.5)
        self.frame_ms = (self.frame_us + 999) // 1000

        if verbose:
            print(f"lcd: {self.num_desc} DMA descriptors"
                  f"{'' if self.fbs == 1 else ' per framebuffer'}, "
                  f"{real_pclk / 1e6:.3f} MHz pclk -> "
                  f"{self.refresh_hz:.2f} Hz (LCD_CLOCK 0x{clk_val:08x})")

        # --- start the DMA first, then the LCD engine ----------------
        self.start()

        if backlight is not None:
            self.backlight(True)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    @property
    def fb(self):
        """The raw PSRAM ``bytearray`` that ``show()`` will put on screen.

        With ``fbs >= 2`` this follows the *drawing* buffer, which changes
        on every :meth:`show`; re-read it instead of caching it.
        """
        self._settle()
        return self._fb[self._back]

    @property
    def fb_addr(self):
        """Address of the buffer returned by :attr:`fb`."""
        self._settle()
        return self._fb_addr[self._back]

    @property
    def fbuf(self):
        """A ``framebuf.FrameBuffer`` view of the buffer to draw into.

        With ``fbs >= 2`` the target alternates between frames, so fetch it
        again for each frame (or use :meth:`framebuffer`); a reference held
        across a :meth:`show` goes on pointing at the old buffer.
        """
        self._settle()
        return self._fbuf[self._back]

    def framebuffers(self):
        """Every framebuffer, indexed by frame (only useful with ``fbs>1``)."""
        return tuple(self._fbuf)

    def _settle(self):
        """Wait until the drawing buffer is no longer being scanned.

        A hand-off only takes effect when the DMA reaches the tail of the
        frame it is in the middle of, so for up to one frame after
        :meth:`show` it can still be reading a buffer that is now the
        drawing target.  Touching it during that window is the one thing
        that can still tear, so every accessor waits it out (and in any
        sane drawing loop finds nothing to wait for).
        """
        at = self._free_at[self._back]
        if not at:
            return
        self._free_at[self._back] = 0
        delay = time.ticks_diff(at, time.ticks_ms())
        if delay > 0:
            time.sleep_ms(delay)

    def start(self):
        """(Re)start the DMA link and the LCD engine.

        The DMA has to be running before the LCD engine starts, otherwise
        the async FIFO underflows on the very first line.  This mirrors
        lcd_rgb_panel_start_transmission().
        """
        self.dma.reset()
        lcd_cam.stop()
        lcd_cam.reset()
        lcd_cam.fifo_reset()
        self.dma.start(self._desc_head[self._shown])
        time.sleep_us(10)
        lcd_cam.start()
        if self.fbs > 1:
            self._free_at = [0] * self.fbs

    def stop(self):
        lcd_cam.stop()

    def backlight(self, on=True):
        pin = self._backlight_pin
        if pin is None:
            return
        disconnect(pin)
        set_level(pin, 1 if on else 0)

    # ------------------------------------------------------------------
    # drawing
    # ------------------------------------------------------------------
    def fill(self, color):
        """Fill the whole framebuffer with a 16-bit RGB565 colour."""
        self.fbuf.fill(color & 0xFFFF)

    def pixel(self, x, y, color):
        self.fbuf.pixel(x, y, color & 0xFFFF)

    def fill_rect(self, x, y, w, h, color):
        self.fbuf.fill_rect(x, y, w, h, color & 0xFFFF)

    def bitmap(self, x, y, w, h, data):
        """Blit raw little-endian RGB565 bytes (row-major, no padding)."""
        self.fbuf.blit(framebuf.FrameBuffer(data, w, h, framebuf.RGB565), x, y)

    def framebuffer(self):
        """A ``framebuf.FrameBuffer`` view of the buffer to draw into.

        With ``fbs >= 2`` that buffer changes on every :meth:`show`, so ask
        for it again each frame rather than caching it.  (``dpi.fbuf`` is
        the same thing; ``dpi.fb`` is the raw bytearray, for callers that
        want to manage their own framebuf.)
        """
        return self.fbuf

    def next_fb(self):
        """Return the framebuffer bytearray to draw into next.

        This is a convenience for double-buffered operation. With ``fbs>=2``,
        it returns the raw bytearray for the back buffer (the one to draw
        into). Call :meth:`show()` after drawing to present it.
        """
        return self._fb[self._back]

    # ------------------------------------------------------------------
    # presenting
    # ------------------------------------------------------------------
    def show(self, addr=None, nbytes=None):
        """Flush the buffer we drew into and put it on the panel.

        The GDMA reads PSRAM without snooping the CPU's L1 data cache, so
        anything just drawn has to be flushed first - exactly what
        ``esp_cache_msync(..., DIR_C2M)`` does in ESP-IDF.  ``addr`` and
        ``nbytes`` narrow that flush to the region that changed.

        With ``fbs >= 2`` a narrowed flush is *unsafe* unless the entire
        drawing buffer has been redrawn (the regions you did not flush still
        contain the old frame's pixels).  If you only drew a rectangle, flush
        the whole buffer or pass ``None``.

        With ``fbs >= 2`` this also hands the DMA the buffer just drawn and
        moves drawing to the next one (see :meth:`_present`).  The switch is
        atomic, so a frame is never half old and half new.
        """
        index = self._back
        if addr is None:
            addr, nbytes = self._fb_addr[index], self.fb_size
        else:
            if self.fbs >= 2 and nbytes != self.fb_size:
                raise ValueError("narrowed show() with fbs>=2 is unsafe: "
                                 "flush the whole buffer or use fbs=1")
        if self.flush:
            writeback(addr, nbytes)
        self._present(index)

    def _present(self, index):
        """Make ``index`` the frame the DMA sends, from the next boundary on.

        Every framebuffer has its own descriptor list, so switching is done
        by pointing a list's *tail* at another list's head: the DMA finishes
        the frame it is in and then walks straight into the new one, and the
        new list is closed on itself so it stays there.  All the lists are
        re-pointed, not just the one in flight, so it does not matter which
        one the DMA happens to be walking - that is IDF's
        ``gdma_link_concat(fb[i], fb[cur])`` loop.

        Each store is a single aligned 32-bit write to internal DRAM and the
        DMA is mid-frame, so this cannot be caught half-done.
        """
        if self.fbs < 2:
            return
        if index != self._shown:
            head = self._desc_head[index]
            for i in range(self.fbs):
                gdma.link_to(self._desc_tail[i], head)
            self._shown = index
            # every other buffer may be in flight until the DMA reaches the
            # new list's head, which is at most one frame away
            until = time.ticks_add(time.ticks_ms(), self.frame_ms)
            for i in range(self.fbs):
                if i != index:
                    self._free_at[i] = until
        self._back = (index + 1) % self.fbs

    def test_pattern(self):
        """Draw vertical colour bars - a quick way to validate the panel."""
        bars = (0xF800, 0x07E0, 0x001F, 0xFFFF, 0xFFE0, 0x07FF, 0xF81F, 0x0000)
        w = self.width // len(bars)
        for i, c in enumerate(bars):
            self.fill_rect(i * w, 0, w, self.height, c)
        rem = self.width - w * len(bars)
        if rem:
            self.fill_rect(w * len(bars), 0, rem, self.height, bars[-1])

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------
    def registers(self):
        """Snapshot the LCD_CAM + GDMA state (for diffing against IDF)."""
        return {
            "lcd_clock": mem32[LCD_CAM_BASE + LCD_CLOCK],
            "cam_ctrl": mem32[LCD_CAM_BASE + CAM_CTRL],
            "cam_rgb_yuv": mem32[LCD_CAM_BASE + CAM_RGB_YUV],
            "lcd_rgb_yuv": mem32[LCD_CAM_BASE + LCD_RGB_YUV],
            "lcd_user": mem32[LCD_CAM_BASE + LCD_USER],
            "lcd_misc": mem32[LCD_CAM_BASE + LCD_MISC],
            "lcd_ctrl": mem32[LCD_CAM_BASE + LCD_CTRL],
            "lcd_ctrl1": mem32[LCD_CAM_BASE + LCD_CTRL1],
            "lcd_ctrl2": mem32[LCD_CAM_BASE + LCD_CTRL2],
            "lc_dma_int_ena": mem32[LCD_CAM_BASE + LC_DMA_INT_ENA],
            "perip_clk_en1": mem32[SYSTEM_PERIP_CLK_EN1],
            "perip_rst_en1": mem32[SYSTEM_PERIP_RST_EN1],
            "out_conf0": mem32[self.dma.base + GDMA_OUT_CONF0],
            "out_conf1": mem32[self.dma.base + GDMA_OUT_CONF1],
            "out_int_ena": mem32[self.dma.base + GDMA_OUT_INT_ENA],
            "out_link": mem32[self.dma.base + GDMA_OUT_LINK],
            "out_peri_sel": mem32[self.dma.base + GDMA_OUT_PERI_SEL],
            "out_state": mem32[self.dma.base + GDMA_OUT_STATE],
        }
