# Ground-truth register dump from the working C module

Captured on-device from the working custom C module
[`lcd_binding_micropython`](https://github.com/lbuque/lcd_binding_micropython)
after it had brought the panel up correctly.  This is the ground truth
every constant in `esp32_4848s040.py` is derived from and is checked
against; the analysis lives in [`register_map.md`](register_map.md).

Addresses and values are reproduced from the capture.  Values are
32-bit words read back through `machine.mem32`; the signed values the
module printed are shown here in their unsigned 32-bit form.  The register
names are the ESP32-S3 `*_reg.h` definitions from ESP-IDF.

## Session

The board ran MicroPython v1.30.0-preview, built for this board
(`_build='GUITION_4848S040'`), on 2026-10-14:

```
MicroPython 3843e4a0e3 on 2026-10-14; Guition ESP32-S3-4848S040 with ESP32-S3
```

## Before init

Every `LCD_CAM` register reads back `0` before the driver runs - the
peripheral is left untouched:

| address | register | value | notes |
| --- | --- | --- | --- |
| `0x60041000` | `LCD_CLOCK` | `0x00000000` |  |
| `0x60041004` | `CAM_CTRL` | `0x00000000` |  |
| `0x60041008` | `CAM_CTRL1` | `0x00000000` |  |
| `0x6004100c` | `CAM_RGB_YUV` | `0x00000000` |  |
| `0x60041010` | `LCD_RGB_YUV` | `0x00000000` |  |
| `0x60041014` | `LCD_USER` | `0x00000000` |  |
| `0x60041018` | `LCD_MISC` | `0x00000000` |  |
| `0x6004101c` | `LCD_CTRL` | `0x00000000` |  |
| `0x60041020` | `LCD_CTRL1` | `0x00000000` |  |
| `0x60041024` | `LCD_CTRL2` | `0x00000000` |  |
| `0x60041028` | `LCD_CMD_VAL` | `0x00000000` |  |
| `0x6004102c` |  | `0x00000000` |  |
| `0x60041030` | `LCD_DLY_MODE` | `0x00000000` |  |
| `0x60041034` |  | `0x00000000` |  |
| `0x60041038` | `LCD_DATA_DOUT_MODE` | `0x00000000` |  |
| `0x6004103c` |  | `0x00000000` |  |
| `0x60041064` | `LC_DMA_INT_ENA` | `0x00000000` |  |
| `0x60041068` | `LC_DMA_INT_RAW` | `0x00000000` |  |
| `0x6004106c` | `LC_DMA_INT_ST` | `0x00000000` |  |
| `0x60041070` | `LC_DMA_INT_CLR` | `0x00000000` |  |
| `0x600410fc` | `LC_REG_DATE` | `0x00000000` |  |

## Creating the panel

```
### CREATING lcd.DPI ...
# lcd.DPI created OK
```

## After init: decoded `LCD_CAM`

The capture's own decode of the post-init `LCD_CAM` registers, field by field:

| register | decoded fields |
| --- | --- |
| `lcd_clock` | `raw=e5860e01` clk_en=1 clk_sel=3 div_num=7 div_a=11 div_b=3 equ_sysclk=0 clkcnt_n=1 idle_edge=0 out_edge=0 |
| `lcd_user` | `raw=09802000` start=1 reset=0 dout=1 2byte_en=1 update=0 always_out_en=1 byte_order=0 bit_order=0 |
| `lcd_misc` | `raw=06000016` next_frame_en=1 bk_en=1 vbk_cyclelen=0 afifo_thresh=11 |
| `lcd_ctrl` | `raw=c0aef839` hb_front=57 va_height=479 vt_height=517 rgb_mode_en=1 |
| `lcd_ctrl1` | `raw=2231df1b` vb_front=27 ha_width=479 ht_width=547 |
| `lcd_ctrl2` | `raw=00870287` vsync_width=7 vsync_idle_pol=1 de_idle_pol=0 hs_blank_en=1 hsync_width=7 hsync_idle_pol=1 hsync_position=0 |

## After init: active GDMA channel

Channel 0 is the one the panel's descriptor list is parked on:

| field | value |
| --- | --- |
| `ch` | `0` |
| `out_conf0` | `00000030` |
| `out_conf1` | `00004000` |
| `out_peri_sel` | `00000005` |
| `out_state` | `002ef0e4` |
| `outfifo` | `00205a00` |

### Descriptors

First six nodes and the last one; the chain is circular.

| descriptor | decoded |
| --- | --- |
| `desc[0]` @ `0x3fcaebf8` | dw0=80ffffff size=4095 length=4095 err_eof=0 suc_eof=0 owner=1 buffer=3c1b0c20 next=3fcaec04 |
| `desc[1]` @ `0x3fcaec04` | dw0=80ffffff size=4095 length=4095 err_eof=0 suc_eof=0 owner=1 buffer=3c1b1c1f next=3fcaec10 |
| `desc[2]` @ `0x3fcaec10` | dw0=80ffffff size=4095 length=4095 err_eof=0 suc_eof=0 owner=1 buffer=3c1b2c1e next=3fcaec1c |
| `desc[3]` @ `0x3fcaec1c` | dw0=80ffffff size=4095 length=4095 err_eof=0 suc_eof=0 owner=1 buffer=3c1b3c1d next=3fcaec28 |
| `desc[4]` @ `0x3fcaec28` | dw0=80ffffff size=4095 length=4095 err_eof=0 suc_eof=0 owner=1 buffer=3c1b4c1c next=3fcaec34 |
| `desc[5]` @ `0x3fcaec34` | dw0=80ffffff size=4095 length=4095 err_eof=0 suc_eof=0 owner=1 buffer=3c1b5c1b next=3fcaec40 |
| `desc[112]` @ `0x3fcaf138` | dw0=c0870870 size=2160 length=2160 err_eof=0 suc_eof=0 owner=1 buffer=3c220bb0 next=3fcaebf8 |
| _(109 more)_ | ... chain circular, total 113 descriptors |

## Raw dumps (post-init)

### LCD_CAM

| address | register | value | notes |
| --- | --- | --- | --- |
| `0x60041000` | `LCD_CLOCK` | `0xe5860e01` |  |
| `0x60041004` | `CAM_CTRL` | `0x00000800` |  |
| `0x60041008` | `CAM_CTRL1` | `0x00000000` |  |
| `0x6004100c` | `CAM_RGB_YUV` | `0x00c00000` |  |
| `0x60041010` | `LCD_RGB_YUV` | `0x00c00000` |  |
| `0x60041014` | `LCD_USER` | `0x09802000` |  |
| `0x60041018` | `LCD_MISC` | `0x06000016` |  |
| `0x6004101c` | `LCD_CTRL` | `0xc0aef839` |  |
| `0x60041020` | `LCD_CTRL1` | `0x2231df1b` |  |
| `0x60041024` | `LCD_CTRL2` | `0x00870287` |  |
| `0x60041028` | `LCD_CMD_VAL` | `0x00000000` |  |
| `0x6004102c` |  | `0x00000000` |  |
| `0x60041030` | `LCD_DLY_MODE` | `0x00000000` |  |
| `0x60041034` |  | `0x00000000` |  |
| `0x60041038` | `LCD_DATA_DOUT_MODE` | `0x00000000` |  |
| `0x6004103c` |  | `0x00000000` |  |
| `0x60041064` | `LC_DMA_INT_ENA` | `0x00000001` |  |
| `0x60041068` | `LC_DMA_INT_RAW` | `0x00000000` |  |
| `0x6004106c` | `LC_DMA_INT_ST` | `0x00000000` |  |
| `0x60041070` | `LC_DMA_INT_CLR` | `0x00000000` |  |
| `0x600410fc` | `LC_REG_DATE` | `0x02003020` |  |

### GDMA

| address | register | value | notes |
| --- | --- | --- | --- |
| `0x6003f000` | `IN_CONF0` | `0x00000000` |  |
| `0x6003f004` | `IN_CONF1` | `0x0000000c` |  |
| `0x6003f008` | `IN_INT_RAW` | `0x00000000` |  |
| `0x6003f00c` | `IN_INT_ST` | `0x00000000` |  |
| `0x6003f010` | `IN_INT_ENA` | `0x00000000` |  |
| `0x6003f014` | `IN_INT_CLR` | `0x00000000` |  |
| `0x6003f018` | `INFIFO_STATUS` | `0x0f00003a` |  |
| `0x6003f01c` | `IN_POP` | `0x00000800` |  |
| `0x6003f020` | `IN_LINK` | `0x01100000` |  |
| `0x6003f024` | `IN_STATE` | `0x00000000` |  |
| `0x6003f028` | `IN_SUC_EOF_DES_ADDR` | `0x00000000` |  |
| `0x6003f02c` | `IN_ERR_EOF_DES_ADDR` | `0x00000000` |  |
| `0x6003f030` | `IN_DSCR` | `0x00000000` |  |
| `0x6003f034` | `IN_DSCR_BF0` | `0x00000000` |  |
| `0x6003f038` | `IN_DSCR_BF1` | `0x00000000` |  |
| `0x6003f03c` | `IN_WEIGHT` | `0x00000f00` |  |
| `0x6003f040` |  | `0x00000000` |  |
| `0x6003f044` | `IN_PRI` | `0x00000000` |  |
| `0x6003f048` | `IN_PERI_SEL` | `0x0000003f` |  |
| `0x6003f04c` |  | `0x00000000` |  |
| `0x6003f050` |  | `0x00000000` |  |
| `0x6003f060` | `OUT_CONF0` | `0x00000030` |  |
| `0x6003f064` | `OUT_CONF1` | `0x00004000` |  |
| `0x6003f068` | `OUT_INT_RAW` | `0x00000001` |  |
| `0x6003f06c` | `OUT_INT_ST` | `0x00000000` |  |
| `0x6003f070` | `OUT_INT_ENA` | `0x00000002` |  |
| `0x6003f074` | `OUT_INT_CLR` | `0x00000000` |  |
| `0x6003f078` | `OUTFIFO_STATUS` | `0x00405812` |  |
| `0x6003f07c` | `OUT_PUSH` | `0x00000000` |  |
| `0x6003f080` | `OUT_LINK` | `0x000aebf8` | channel 0 descriptor list head |
| `0x6003f084` | `OUT_STATE` | `0x002eef7c` |  |
| `0x6003f088` | `OUT_EOF_DES_ADDR` | `0x3fcaf138` |  |
| `0x6003f08c` | `OUT_EOF_BFR_DES_ADDR` | `0x3fcaf12c` |  |
| `0x6003f0a8` | `OUT_PERI_SEL` | `0x00000005` |  |
| `0x6003f0ac` |  | `0x00000000` |  |
| `0x6003f0b0` |  | `0x00000000` |  |
| `0x6003f120` | `OUT_CONF0_CH1` | `0x00000008` | channel 1 |
| `0x6003f124` | `OUT_CONF1_CH1` | `0x00000000` | channel 1 |
| `0x6003f128` | `OUT_INT_RAW_CH1` | `0x00000000` | channel 1 |
| `0x6003f12c` | `OUT_INT_ST_CH1` | `0x00000000` | channel 1 |
| `0x6003f130` | `OUT_INT_ENA_CH1` | `0x00000000` | channel 1 |
| `0x6003f134` | `OUT_INT_CLR_CH1` | `0x00000000` | channel 1 |
| `0x6003f138` | `OUTFIFO_STATUS_CH1` | `0x0780002a` | channel 1 |
| `0x6003f13c` | `OUT_PUSH_CH1` | `0x00000000` | channel 1 |
| `0x6003f140` | `OUT_LINK_CH1` | `0x00800000` | channel 1 |
| `0x6003f144` | `OUT_STATE_CH1` | `0x00000000` | channel 1 |
| `0x6003f148` | `OUT_EOF_DES_ADDR_CH1` | `0x00000000` | channel 1 |
| `0x6003f14c` | `OUT_EOF_BFR_DES_ADDR_CH1` | `0x00000000` | channel 1 |
| `0x6003f168` | `OUT_PERI_SEL_CH1` | `0x0000003f` | channel 1 |
| `0x6003f16c` |  | `0x00000000` |  |
| `0x6003f170` |  | `0x00000000` |  |
| `0x6003f1e0` | `OUT_CONF0_CH2` | `0x00000008` | channel 2 |
| `0x6003f1e4` | `OUT_CONF1_CH2` | `0x00000000` | channel 2 |
| `0x6003f1e8` | `OUT_INT_RAW_CH2` | `0x00000000` | channel 2 |
| `0x6003f1ec` | `OUT_INT_ST_CH2` | `0x00000000` | channel 2 |
| `0x6003f1f0` | `OUT_INT_ENA_CH2` | `0x00000000` | channel 2 |
| `0x6003f1f4` | `OUT_INT_CLR_CH2` | `0x00000000` | channel 2 |
| `0x6003f1f8` | `OUTFIFO_STATUS_CH2` | `0x0780002a` | channel 2 |
| `0x6003f1fc` | `OUT_PUSH_CH2` | `0x00000000` | channel 2 |
| `0x6003f200` | `OUT_LINK_CH2` | `0x00800000` | channel 2 |
| `0x6003f204` | `OUT_STATE_CH2` | `0x00000000` | channel 2 |
| `0x6003f208` | `OUT_EOF_DES_ADDR_CH2` | `0x00000000` | channel 2 |
| `0x6003f20c` | `OUT_EOF_BFR_DES_ADDR_CH2` | `0x00000000` | channel 2 |
| `0x6003f228` | `OUT_PERI_SEL_CH2` | `0x0000003f` | channel 2 |
| `0x6003f22c` |  | `0x00000000` |  |
| `0x6003f230` |  | `0x00000000` |  |
| `0x6003f2a0` | `OUT_CONF0_CH3` | `0x00000008` | channel 3 |
| `0x6003f2a4` | `OUT_CONF1_CH3` | `0x00000000` | channel 3 |
| `0x6003f2a8` | `OUT_INT_RAW_CH3` | `0x00000000` | channel 3 |
| `0x6003f2ac` | `OUT_INT_ST_CH3` | `0x00000000` | channel 3 |
| `0x6003f2b0` | `OUT_INT_ENA_CH3` | `0x00000000` | channel 3 |
| `0x6003f2b4` | `OUT_INT_CLR_CH3` | `0x00000000` | channel 3 |
| `0x6003f2b8` | `OUTFIFO_STATUS_CH3` | `0x0780002a` | channel 3 |
| `0x6003f2bc` | `OUT_PUSH_CH3` | `0x00000000` | channel 3 |
| `0x6003f2c0` | `OUT_LINK_CH3` | `0x00800000` | channel 3 |
| `0x6003f2c4` | `OUT_STATE_CH3` | `0x00000000` | channel 3 |
| `0x6003f2c8` | `OUT_EOF_DES_ADDR_CH3` | `0x00000000` | channel 3 |
| `0x6003f2cc` | `OUT_EOF_BFR_DES_ADDR_CH3` | `0x00000000` | channel 3 |
| `0x6003f2e8` | `OUT_PERI_SEL_CH3` | `0x0000003f` | channel 3 |
| `0x6003f2ec` |  | `0x00000000` |  |
| `0x6003f2f0` |  | `0x00000000` |  |
| `0x6003f360` | `OUT_CONF0_CH4` | `0x00000008` | channel 4 |
| `0x6003f364` | `OUT_CONF1_CH4` | `0x00000000` | channel 4 |
| `0x6003f368` | `OUT_INT_RAW_CH4` | `0x00000000` | channel 4 |
| `0x6003f36c` | `OUT_INT_ST_CH4` | `0x00000000` | channel 4 |
| `0x6003f370` | `OUT_INT_ENA_CH4` | `0x00000000` | channel 4 |
| `0x6003f374` | `OUT_INT_CLR_CH4` | `0x00000000` | channel 4 |
| `0x6003f378` | `OUTFIFO_STATUS_CH4` | `0x0780002a` | channel 4 |
| `0x6003f37c` | `OUT_PUSH_CH4` | `0x00000000` | channel 4 |
| `0x6003f380` | `OUT_LINK_CH4` | `0x00800000` | channel 4 |
| `0x6003f384` | `OUT_STATE_CH4` | `0x00000000` | channel 4 |
| `0x6003f388` | `OUT_EOF_DES_ADDR_CH4` | `0x00000000` | channel 4 |
| `0x6003f38c` | `OUT_EOF_BFR_DES_ADDR_CH4` | `0x00000000` | channel 4 |
| `0x6003f3a8` | `OUT_PERI_SEL_CH4` | `0x0000003f` | channel 4 |
| `0x6003f3ac` |  | `0x00000000` |  |
| `0x6003f3b0` |  | `0x00000000` |  |

### SYSTEM

| address | register | value | notes |
| --- | --- | --- | --- |
| `0x600c0000` | `CORE_1_CONTROL_0` | `0x00000002` |  |
| `0x600c0004` | `CORE_1_CONTROL_1` | `0x00000000` |  |
| `0x600c0008` | `CPU_PERI_CLK_EN` | `0x00000040` |  |
| `0x600c000c` | `CPU_PERI_RST_EN` | `0x00000080` |  |
| `0x600c0010` | `CPU_PER_CONF` | `0x00000005` |  |
| `0x600c0014` | `MEM_PD_MASK` | `0x00000000` |  |
| `0x600c0018` | `PERIP_CLK_EN0` | `0x6180e007` |  |
| `0x600c001c` | `PERIP_CLK_EN1` | `0x00000540` |  |
| `0x600c0020` | `PERIP_RST_EN0` | `0x9e7f1ff8` |  |
| `0x600c0024` | `PERIP_RST_EN1` | `0x0000028e` |  |
| `0x600c0028` | `BT_LPCK_DIV_INT` | `0x00000000` |  |
| `0x600c002c` | `BT_LPCK_DIV_FRAC` | `0x01001001` |  |
| `0x600c0030` | `CPU_INTR_FROM_CPU_0` | `0x00000000` |  |
| `0x600c0034` | `CPU_INTR_FROM_CPU_1` | `0x00000000` |  |
| `0x600c0038` | `CPU_INTR_FROM_CPU_2` | `0x00000000` |  |
| `0x600c003c` | `CPU_INTR_FROM_CPU_3` | `0x00000000` |  |

### EXTMEM

| address | register | value | notes |
| --- | --- | --- | --- |
| `0x600c4000` | `DCACHE_CTRL` | `0x00000009` |  |
| `0x600c4004` | `DCACHE_CTRL1` | `0x00000000` |  |
| `0x600c4008` | `DCACHE_TAG_POWER_CTRL` | `0x00000004` |  |
| `0x600c400c` | `DCACHE_PRELOCK_CTRL` | `0x00000000` |  |
| `0x600c4010` | `DCACHE_PRELOCK_SCT0_ADDR` | `0x00000000` |  |
| `0x600c4014` | `DCACHE_PRELOCK_SCT1_ADDR` | `0x00000000` |  |
| `0x600c4018` | `DCACHE_PRELOCK_SCT_SIZE` | `0x00000000` |  |
| `0x600c401c` | `DCACHE_LOCK_CTRL` | `0x00000004` |  |
| `0x600c4020` | `DCACHE_LOCK_ADDR` | `0x00000000` |  |
| `0x600c4024` | `DCACHE_LOCK_SIZE` | `0x00000000` |  |
| `0x600c4028` | `DCACHE_SYNC_CTRL` | `0x00000008` |  |
| `0x600c402c` | `DCACHE_SYNC_ADDR` | `0x3c1b0c20` |  |
| `0x600c4030` | `DCACHE_SYNC_SIZE` | `0x0000001e` |  |
| `0x600c4034` | `DCACHE_OCCUPY_CTRL` | `0x00000002` |  |
| `0x600c4038` | `DCACHE_OCCUPY_ADDR` | `0x00000000` |  |
| `0x600c403c` | `DCACHE_OCCUPY_SIZE` | `0x00000000` |  |

### GPIO

| address | register | value | notes |
| --- | --- | --- | --- |
| `0x60004000` | `BT_SELECT` | `0x00000000` |  |
| `0x60004004` | `OUT` | `0x00000000` |  |
| `0x60004008` | `OUT_W1TS` | `0x00000000` |  |
| `0x6000400c` | `OUT_W1TC` | `0x00000000` |  |
| `0x60004010` | `OUT1` | `0x000000c0` |  |
| `0x60004014` | `OUT1_W1TS` | `0x00000000` |  |
| `0x60004020` | `ENABLE` | `0x0037fff9` | output drivers enabled on the LCD pads |
| `0x60004024` | `ENABLE_W1TS` | `0x00000000` |  |
| `0x60004028` | `ENABLE_W1TC` | `0x00000000` |  |
| `0x6000402c` | `ENABLE1` | `0x0001c0c0` |  |
| `0x60004030` | `ENABLE1_W1TS` | `0x00000000` |  |
| `0x60004034` | `ENABLE1_W1TC` | `0x00000000` |  |
| `0x60004554` | `FUNC0_OUT_SEL_CFG` | `0x00000094` |  |
| `0x60004558` | `FUNC1_OUT_SEL_CFG` | `0x00000100` |  |
| `0x6000455c` | `FUNC2_OUT_SEL_CFG` | `0x00000100` |  |
| `0x60004560` | `FUNC3_OUT_SEL_CFG` | `0x0000008c` |  |
| `0x60004564` | `FUNC4_OUT_SEL_CFG` | `0x00000085` |  |
| `0x60004568` | `FUNC5_OUT_SEL_CFG` | `0x00000086` |  |
| `0x6000456c` | `FUNC6_OUT_SEL_CFG` | `0x00000087` |  |
| `0x60004570` | `FUNC7_OUT_SEL_CFG` | `0x00000088` |  |
| `0x60004574` | `FUNC8_OUT_SEL_CFG` | `0x0000008a` |  |
| `0x60004578` | `FUNC9_OUT_SEL_CFG` | `0x0000008e` |  |
| `0x6000457c` | `FUNC10_OUT_SEL_CFG` | `0x0000008f` |  |
| `0x60004580` | `FUNC11_OUT_SEL_CFG` | `0x00000090` |  |
| `0x60004584` | `FUNC12_OUT_SEL_CFG` | `0x00000091` |  |
| `0x60004588` | `FUNC13_OUT_SEL_CFG` | `0x00000092` |  |
| `0x6000458c` | `FUNC14_OUT_SEL_CFG` | `0x00000093` |  |
| `0x60004590` | `FUNC15_OUT_SEL_CFG` | `0x00000089` |  |
| `0x60004594` | `FUNC16_OUT_SEL_CFG` | `0x00000097` |  |
| `0x60004598` | `FUNC17_OUT_SEL_CFG` | `0x00000098` |  |
| `0x6000459c` | `FUNC18_OUT_SEL_CFG` | `0x00000096` |  |
| `0x600045a0` | `FUNC19_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045a4` | `FUNC20_OUT_SEL_CFG` | `0x0000008b` |  |
| `0x600045a8` | `FUNC21_OUT_SEL_CFG` | `0x0000009a` |  |
| `0x600045ac` | `FUNC22_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045b0` | `FUNC23_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045b4` | `FUNC24_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045b8` | `FUNC25_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045bc` | `FUNC26_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045c0` | `FUNC27_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045c4` | `FUNC28_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045c8` | `FUNC29_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045cc` | `FUNC30_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045d0` | `FUNC31_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045d4` | `FUNC32_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045d8` | `FUNC33_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045dc` | `FUNC34_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045e0` | `FUNC35_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045e4` | `FUNC36_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045e8` | `FUNC37_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045ec` | `FUNC38_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045f0` | `FUNC39_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045f4` | `FUNC40_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045f8` | `FUNC41_OUT_SEL_CFG` | `0x00000100` |  |
| `0x600045fc` | `FUNC42_OUT_SEL_CFG` | `0x00000100` |  |
| `0x60004600` | `FUNC43_OUT_SEL_CFG` | `0x00000100` |  |
| `0x60004604` | `FUNC44_OUT_SEL_CFG` | `0x00000100` |  |
| `0x60004608` | `FUNC45_OUT_SEL_CFG` | `0x00000100` |  |
| `0x6000460c` | `FUNC46_OUT_SEL_CFG` | `0x0000008d` |  |
| `0x60004610` | `FUNC47_OUT_SEL_CFG` | `0x00000100` |  |
| `0x60004614` | `FUNC48_OUT_SEL_CFG` | `0x00000100` |  |
| `0x60004530` | `FUNC247_IN_SEL_CFG` | `0x00000000` |  |
| `0x60004534` | `FUNC248_IN_SEL_CFG` | `0x00000000` |  |
| `0x60004538` | `FUNC249_IN_SEL_CFG` | `0x00000000` |  |
| `0x6000453c` | `FUNC250_IN_SEL_CFG` | `0x00000000` |  |
| `0x60004540` | `FUNC251_IN_SEL_CFG` | `0x0000003c` |  |
| `0x60004544` | `FUNC252_IN_SEL_CFG` | `0x0000003c` |  |
| `0x60004548` | `FUNC253_IN_SEL_CFG` | `0x0000003c` |  |
| `0x6000454c` | `FUNC254_IN_SEL_CFG` | `0x0000003c` |  |
| `0x60004550` | `FUNC255_IN_SEL_CFG` | `0x0000003c` |  |
| `0x60004620` | `FUNC51_OUT_SEL_CFG` | `0x00000100` |  |
| `0x60004624` | `FUNC52_OUT_SEL_CFG` | `0x00000100` |  |
| `0x60004628` | `FUNC53_OUT_SEL_CFG` | `0x00000100` |  |
| `0x6000462c` | `CLOCK_GATE` | `0x00000001` |  |
