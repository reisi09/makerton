# I2C 1602 LCD(PCF8574 백팩) 최소 HD44780 드라이버. 4비트 모드.
#   lcd = lcd1602.LCD1602(i2c, 0x27)
#   lcd.show("ICE-ZERO", "N12 E11 S12 W10")
# 하드웨어가 없어도 import된다(바이트는 i2c에 넘길 뿐이다). OLED와 같은 I2C0를 쓴다.
import time

if hasattr(time, "sleep_us"):
    def sleep_us(us):
        time.sleep_us(us)
else:
    def sleep_us(us):
        time.sleep(us / 1000000.0)

if hasattr(time, "sleep_ms"):
    def sleep_ms(ms):
        time.sleep_ms(ms)
else:
    def sleep_ms(ms):
        time.sleep(ms / 1000.0)

# PCF8574 백팩 비트 배치(흔한 결선): P0 RS, P1 RW, P2 E, P3 백라이트, P4~P7 D4~D7
_RS = 0x01
_RW = 0x02
_EN = 0x04
_EN_OFF = 0xFB          # ~_EN (& 연산용. MicroPython에서도 음수 보수 없이 쓴다)
_BL = 0x08
_EN_PULSE_US = 50       # HD44780 E 펄스 최소 450ns. 넉넉히 준다

# 줄 시작 주소(2줄·4줄 모듈 공통)
_LINE_ADDR = (0x00, 0x40, 0x14, 0x54)


class LCD1602:
    def __init__(self, i2c, addr=0x27, cols=16, rows=2, backlight=True):
        self.i2c = i2c
        self.addr = addr
        self.cols = cols
        self.rows = rows
        self.bl = _BL if backlight else 0x00
        self.buf = bytearray(1)        # 바이트마다 새로 만들지 않는다
        self.init_display()

    # ── 저수준 ──
    def _write(self, value):
        self.buf[0] = value | self.bl
        self.i2c.writeto(self.addr, self.buf)

    def _pulse(self, value):
        """E를 올렸다 내려 4비트 한 조각을 보낸다."""
        self._write(value | _EN)
        sleep_us(_EN_PULSE_US)
        self._write(value & _EN_OFF)
        sleep_us(_EN_PULSE_US)

    def _send(self, value, rs):
        self._pulse((value & 0xF0) | rs)          # 상위 니블
        self._pulse(((value << 4) & 0xF0) | rs)   # 하위 니블

    def command(self, value):
        self._send(value, 0)

    # ── 공개 API ──
    def init_display(self):
        sleep_ms(20)                  # 전원 인가 뒤 안정화
        self._pulse(0x30)             # 8비트 상태로 세 번(모듈이 놓쳐도 맞도록)
        sleep_ms(5)
        self._pulse(0x30)
        sleep_ms(1)
        self._pulse(0x30)
        sleep_ms(1)
        self._pulse(0x20)             # 4비트 모드로 전환
        sleep_ms(1)
        self.command(0x28)            # 2줄, 5x8 폰트
        self.command(0x0C)            # 화면 켬, 커서·깜박임 끔
        self.command(0x06)            # 글자 쓸 때 커서 오른쪽으로
        self.command(0x01)            # 지움
        sleep_ms(2)                   # 지움 명령은 1.52ms 걸린다

    def clear(self):
        self.command(0x01)
        sleep_ms(2)

    def putstr(self, text, line=0):
        """한 줄에 문자열을 쓴다. ASCII가 아닌 글자는 '?'로 바꾼다."""
        if line < 0 or line >= self.rows:
            line = 0
        self.command(0x80 | _LINE_ADDR[line])
        s = "" if text is None else str(text)
        for ch in s:
            code = ord(ch)
            if code < 32 or code > 126:
                code = 63             # '?'
            self._send(code, _RS)

    def show(self, line1, line2=""):
        """두 줄을 지우고 새로 쓴다(전광판처럼 한 번에 교체)."""
        self.clear()
        self.putstr(line1, 0)
        if self.rows > 1:
            self.putstr(line2, 1)

    def backlight(self, on):
        self.bl = _BL if on else 0x00
        self._write(0x00)
