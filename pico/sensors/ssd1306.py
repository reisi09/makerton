# 0.91" OLED SSD1306 128×32 I2C 최소 드라이버(framebuf 기반).
#   oled = ssd1306.SSD1306_I2C(128, 32, i2c, 0x3C)
#   oled.fill(0); oled.text("hello", 0, 0); oled.show()
# 맥북 CPython에는 framebuf가 없으므로 이 파일은 import만 되고 그리기는 하지 않는다.
# (문법·API 확인용. 실제 화면은 Pico에서만 나온다.)
try:
    import framebuf
except ImportError:
    framebuf = None

_SET_CONTRAST = 0x81
_SET_ENTIRE_ON = 0xA4
_SET_NORM_INV = 0xA6
_SET_DISP = 0xAE
_SET_MEM_ADDR = 0x20
_SET_COL_ADDR = 0x21
_SET_PAGE_ADDR = 0x22
_SET_DISP_START_LINE = 0x40
_SET_SEG_REMAP = 0xA0
_SET_MUX_RATIO = 0xA8
_SET_COM_OUT_DIR = 0xC0
_SET_DISP_OFFSET = 0xD3
_SET_COM_PIN_CFG = 0xDA
_SET_DISP_CLK_DIV = 0xD5
_SET_PRECHARGE = 0xD9
_SET_VCOM_DESEL = 0xDB
_SET_CHARGE_PUMP = 0x8D


class SSD1306:
    """공통 부분. I2C·SPI는 아래 클래스가 채운다."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.pages = height // 8
        self.buffer = bytearray(self.pages * width)
        self.fb = None
        if framebuf is not None:
            self.fb = framebuf.FrameBuffer(self.buffer, width, height, framebuf.MVLSB)

    # ── 그리기 ──
    def fill(self, col):
        """화면 버퍼를 col(0 또는 1)로 채운다. show() 전까지는 화면에 나오지 않는다."""
        if self.fb is not None:
            self.fb.fill(1 if col else 0)
            return
        self.buffer[:] = b"\xff" * len(self.buffer) if col else b"\x00" * len(self.buffer)

    def text(self, string, x, y):
        """ASCII 한 줄을 (x, y)에 쓴다. 6x8 폰트라 128px 폭에 21자가 들어간다."""
        if self.fb is not None:
            self.fb.text(string, x, y)

    def pixel(self, x, y, col=1):
        if self.fb is not None:
            self.fb.pixel(x, y, col)

    # ── 화면 전송 ──
    def show(self):
        """버퍼 전체를 OLED로 보낸다. 주소 창은 init에서 (0,0)~(W-1, pages-1)로 잡아 두었다."""
        self.write_data(self.buffer)

    def write_cmd(self, cmd):
        raise NotImplementedError

    def write_data(self, buf):
        raise NotImplementedError

    # ── 초기화 ──
    def init_display(self, external_vcc=False):
        for cmd in (
            _SET_DISP,                                   # 화면 끔
            0xD5, 0x80,                                  # 클럭 분주
            _SET_MUX_RATIO, self.height - 1,
            _SET_DISP_OFFSET, 0x00,
            _SET_DISP_START_LINE,
            _SET_CHARGE_PUMP, 0x14,                      # 내장 승압(외부 7.5V면 생략)
            _SET_MEM_ADDR, 0x00,                         # 수평 주소 모드
            _SET_COL_ADDR, 0x00, self.width - 1,         # 주소 창: 가로 전체
            _SET_PAGE_ADDR, 0x00, self.pages - 1,        # 주소 창: 세로 전체(show가 한 번에 보낸다)
            _SET_SEG_REMAP | 0x01,                       # 좌우 반전(모듈 장착 방향)
            _SET_COM_OUT_DIR | 0x08,                     # 위아래 반전(128×32 모듈)
            _SET_COM_PIN_CFG, 0x02 if self.height == 32 else 0x12,
            _SET_CONTRAST, 0x8F,
            _SET_PRECHARGE, 0x22 if external_vcc else 0xF1,
            _SET_VCOM_DESEL, 0x30,
            _SET_ENTIRE_ON,
            _SET_NORM_INV,
            _SET_DISP | 0x01,                            # 화면 켬
        ):
            self.write_cmd(cmd)
        self.fill(0)
        self.show()


class SSD1306_I2C(SSD1306):
    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False):
        self.i2c = i2c
        self.addr = addr
        self.temp = bytearray(2)
        # 프레임마다 버퍼를 복사하지 않도록 제어 바이트와 데이터 버퍼를 따로 보낸다
        self.write_list = [b"\x40", None]
        SSD1306.__init__(self, width, height)
        self.init_display(external_vcc)

    def write_cmd(self, cmd):
        self.temp[0] = 0x80        # Co=1, D/C=0
        self.temp[1] = cmd
        self.i2c.writeto(self.addr, self.temp)

    def write_data(self, buf):
        self.write_list[1] = buf
        self.i2c.writevto(self.addr, self.write_list)
