"""공용 실물 부품. 1단위 = 1mm, 원점은 부품 왼쪽 위. Part를 돌려준다.

핀 이름은 아래 표를 따른다(계약 6·7절의 배선표와 같은 이름).
    pico2wh()          "1".."40", "GP0","GP1","GP2".., "GND3","GND8","GND13","GND18",
                       "GND23","GND28","GND38","AGND33","VBUS","VSYS","3V3","3V3_EN","RUN","ADC_VREF"
    sg90()             "GND","5V","SIG"
    tact_switch()      "A1","A2","B1","B2"
    rgb_led_module()   "R","G","B","GND"
    buzzer_module()    "S","VCC","GND"
    resistor(ohm)      "1","2"
    micro_usb_plug()   "tip"
    phone_charger()    "usb"
    rail_strip(mm)     "+1".."+n", "-1".."-n"

그림 안의 색은 실물 색이다. 제목·주석만 팔레트를 쓴다.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core import (  # noqa: E402
    Part, rect, circle, line, path, text, mount_hole, pin_header, place, size_px,
    text_px, wire, svg_doc, esc,
    FONT, MONO, PCB_GREEN, PCB_BLUE, PCB_BLACK, PCB_RED, GOLD, SILVER, HEADER, SILK, WIRE,
)

# 실물 부품 색(그림 안에서만 쓴다)
PICO_PCB = "#2e6b46"
PICO_PCB_EDGE = "#1d4a2f"
CAN_METAL = "#b9c0c8"
CHIP_BLACK = "#1b1e22"
SERVO_BLUE = "#2b6cb8"
SERVO_BLUE_D = "#1e4f8a"
HORN_WHITE = "#eceff2"
BUZZER_BLACK = "#24272b"
WOOD_FOAM = "#f3f1ea"
WOOD_FOAM_D = "#d9d5c7"
CAP_BLUE = "#2f6fd6"


# ── 라즈베리파이 피코 2 W ─────────────────────────────────────────────
_PICO_LEFT = [
    ("GP0", 1), ("GP1", 2), ("GND3", 3), ("GP2", 4), ("GP3", 5), ("GP4", 6), ("GP5", 7),
    ("GND8", 8), ("GP6", 9), ("GP7", 10), ("GP8", 11), ("GP9", 12), ("GND13", 13),
    ("GP10", 14), ("GP11", 15), ("GP12", 16), ("GP13", 17), ("GND18", 18), ("GP14", 19), ("GP15", 20),
]
_PICO_RIGHT = [
    ("VBUS", 40), ("VSYS", 39), ("GND38", 38), ("3V3_EN", 37), ("3V3", 36), ("ADC_VREF", 35),
    ("GP28", 34), ("AGND33", 33), ("GP27", 32), ("GP26", 31), ("RUN", 30), ("GP22", 29),
    ("GND28", 28), ("GP21", 27), ("GP20", 26), ("GP19", 25), ("GP18", 24), ("GND23", 23),
    ("GP17", 22), ("GP16", 21),
]
_SILK = {
    "GP0": "GP0", "GP1": "GP1", "GND3": "GND", "GP2": "GP2", "GP3": "GP3", "GP4": "GP4",
    "GP5": "GP5", "GND8": "GND", "GP6": "GP6", "GP7": "GP7", "GP8": "GP8", "GP9": "GP9",
    "GND13": "GND", "GP10": "GP10", "GP11": "GP11", "GP12": "GP12", "GP13": "GP13",
    "GND18": "GND", "GP14": "GP14", "GP15": "GP15", "VBUS": "VBUS", "VSYS": "VSYS",
    "GND38": "GND", "3V3_EN": "EN", "3V3": "3V3", "ADC_VREF": "VREF", "GP28": "GP28",
    "AGND33": "AGND", "GP27": "GP27", "GP26": "GP26", "RUN": "RUN", "GP22": "GP22",
    "GND28": "GND", "GP21": "GP21", "GP20": "GP20", "GP19": "GP19", "GP18": "GP18",
    "GND23": "GND", "GP17": "GP17", "GP16": "GP16",
}


def pico2wh():
    """Raspberry Pi Pico 2 W. 51×21mm. USB(마이크로)는 왼쪽 끝, 핀 1번도 왼쪽 끝.

    왼쪽(USB 쪽) 아래 줄 1~20번, 위 줄 40~21번. place(rot=90)로 세우면
    USB가 위, 왼쪽 줄 1~20, 오른쪽 줄 40~21이 되어 계약 7절 설명과 같아진다.
    """
    w, h = 51.0, 21.0
    o = []
    # PCB
    o.append(rect(0.3, 0.6, w - 0.6, h - 1.2, fill=PICO_PCB, stroke=PICO_PCB_EDGE, sw=0.35, rx=1.1))
    # 헤더 플라스틱(위·아래)
    for yy in (0.0, h - 2.54):
        o.append(rect(0.6, yy, w - 1.2, 2.54, fill=HEADER, stroke="#000", sw=0.12, rx=0.35))
    # 마이크로 USB 소켓(왼쪽 끝)
    o.append(rect(-0.9, 6.7, 6.4, 7.6, fill="#cfd4da", stroke="#8d949c", sw=0.3, rx=0.7))
    o.append(rect(0.4, 7.9, 4.4, 5.2, fill="#5c6169", stroke="none"))
    o.append(rect(0.4, 9.3, 4.4, 2.2, fill="#2b2f34", stroke="none"))
    # BOOTSEL 버튼
    o.append(rect(7.4, 8.6, 4.2, 4.2, fill="#c8ccd2", stroke="#8b9098", sw=0.25, rx=0.5))
    o.append(circle(9.5, 10.7, 0.9, fill="#9aa0a8"))
    # 무선 모듈 금속 캔
    o.append(rect(13.0, 5.0, 12.6, 11.4, fill=CAN_METAL, stroke="#8e959d", sw=0.3, rx=1.0))
    o.append(rect(13.8, 5.8, 11.0, 9.8, fill="#c6ccd3", stroke="none", rx=0.8))
    o.append(text(19.3, 10.4, "RM2", 2.3, "#6b7078", "middle", 800))
    o.append(text(19.3, 13.0, "Wi-Fi", 1.5, "#7d838b", "middle", 700))
    # RP2350 칩
    o.append(rect(28.4, 6.4, 7.6, 7.6, fill=CHIP_BLACK, stroke="#000", sw=0.2, rx=0.25))
    o.append(circle(29.9, 7.9, 0.35, fill="#6b7a86"))
    o.append(text(32.2, 10.9, "RP2350", 1.35, "#c9d2da", "middle", 700))
    # 플래시
    o.append(rect(38.2, 8.2, 4.2, 3.4, fill="#2a2f35", stroke="#111", sw=0.2, rx=0.2))
    # 실크 인쇄
    o.append(text(32.8, 16.0, "Pico 2 W", 1.4, "#e8ece6", "middle", 700))
    # 금 도금 패드 + 실크 핀 이름
    pins = {}
    for name, num in _PICO_LEFT:
        x = 1.37 + (num - 1) * 2.54
        o.append(rect(x - 1.15, h - 2.35, 2.30, 2.10, fill=GOLD, stroke="#a8883f", sw=0.1, rx=0.35))
        o.append(text(x, 17.6, _SILK[name], 0.82, "#f2f5ee", "middle", 700))
        pins[name] = (x, h - 1.61)
        pins[str(num)] = (x, h - 1.61)
    for name, num in _PICO_RIGHT:
        x = 1.37 + (40 - num) * 2.54
        o.append(rect(x - 1.15, 0.25, 2.30, 2.10, fill=GOLD, stroke="#a8883f", sw=0.1, rx=0.35))
        o.append(text(x, 4.6, _SILK[name], 0.82, "#f2f5ee", "middle", 700))
        pins[name] = (x, 1.61)
        pins[str(num)] = (x, 1.61)
    return Part("pico2wh", w, h, "".join(o), pins)


# ── SG90 서보 ────────────────────────────────────────────────────────
def sg90():
    """SG90 9g 서보. 32.5(귀 포함)×11.8 몸통. 3선 리드(갈색·빨강·주황)는 오른쪽으로 나와
    검은 3핀 하우징에 물린다. 핀 "GND","5V","SIG".
    """
    w, h = 40.0, 22.7
    o = []
    # 귀(브래킷)
    o.append(rect(0.4, 5.6, 32.0, 11.5, fill=SERVO_BLUE, stroke=SERVO_BLUE_D, sw=0.3, rx=1.6))
    o.append(circle(2.5, 11.35, 1.1, fill="#ffffff", stroke=SERVO_BLUE_D, sw=0.25))
    o.append(circle(29.9, 11.35, 1.1, fill="#ffffff", stroke=SERVO_BLUE_D, sw=0.25))
    # 몸통
    o.append(rect(5.6, 2.2, 21.0, 18.3, fill=SERVO_BLUE, stroke=SERVO_BLUE_D, sw=0.4, rx=1.0))
    o.append(rect(7.2, 3.6, 18.0, 7.0, fill="#3a7cc4", stroke="none", rx=0.5))
    o.append(text(16.1, 8.5, "SG90", 2.0, "#e9f0f8", "middle", 800))
    # 출력축·혼
    o.append(circle(16.1, 14.6, 3.2, fill="#d8dde3", stroke="#9aa1aa", sw=0.25))
    o.append(circle(16.1, 14.6, 1.0, fill="#8f969f"))
    o.append(rect(15.3, 8.2, 1.6, 4.4, fill=HORN_WHITE, stroke="#b9c0c8", sw=0.2, rx=0.6))
    o.append(rect(14.0, 13.8, 4.2, 1.6, fill=HORN_WHITE, stroke="#b9c0c8", sw=0.2, rx=0.6))
    # 3선 리드 → 오른쪽 하우징
    for i, col in enumerate((WIRE["brown"], WIRE["red"], WIRE["orange"])):
        y0 = 7.4 + i * 3.2
        o.append(path("M 31.0 %.2f C 32.6 %.2f, 33.0 %.2f, 35.2 %.2f" % (y0, y0 - 0.8, y0 + 0.5, y0),
                      stroke=col, sw=1.0))
    o.append(rect(35.0, 5.4, 5.0, 11.2, fill="#15181c", stroke="#000", sw=0.2, rx=0.7))
    pins = {}
    for i, name in enumerate(("GND", "5V", "SIG")):
        y = 7.4 + i * 3.2
        o.append(rect(36.4, y - 0.9, 2.6, 1.8, fill=GOLD, stroke="#8f7434", sw=0.15, rx=0.3))
        pins[name] = (w, y)
    return Part("sg90", w, h, "".join(o), pins)


# ── 택트 스위치 6×6 ──────────────────────────────────────────────────
def tact_switch():
    """6×6 택트 스위치. 다리 "A1","A2"(왼쪽), "B1","B2"(오른쪽). 같은 쪽 두 다리는 늘 붙어 있고,
    누르면 좌우가 붙는다. 대각(A1-B2)을 쓰면 오해가 없다.
    """
    w = h = 9.2
    bx, by = 1.6, 1.6
    o = []
    for (lx, ly) in ((0.7, 3.2), (0.7, 6.9), (8.5, 3.2), (8.5, 6.9)):
        o.append(rect(lx - 0.7, ly - 0.55, 1.4, 1.1, fill=SILVER, stroke="#8b9098", sw=0.1, rx=0.15))
    o.append(rect(bx, by, 6.0, 6.0, fill="#20242a", stroke="#0b0d10", sw=0.25, rx=0.45))
    o.append(rect(bx + 0.6, by + 0.6, 4.8, 4.8, fill="#2c3138", stroke="none", rx=0.4))
    o.append(circle(bx + 3.0, by + 3.0, 1.9, fill="#b8bec6", stroke="#7d838b", sw=0.25))
    o.append(circle(bx + 3.0, by + 3.0, 1.1, fill="#9aa0a8", stroke="none"))
    pins = {"A1": (0.7, 3.2), "A2": (0.7, 6.9), "B1": (8.5, 3.2), "B2": (8.5, 6.9)}
    return Part("tact", w, h, "".join(o), pins)


# ── 3색 LED 모듈 ─────────────────────────────────────────────────────
def rgb_led_module():
    """3색(RGB) LED 모듈. 25×15 PCB. 핀 "R","G","B","GND"는 왼쪽 가장자리.

    모듈마다 핀 순서가 다르니 꽂기 전에 실크를 확인한다.
    """
    w, h = 25.0, 15.0
    o = []
    o.append(rect(0, 0, w, h, fill="#1b3f6b", stroke="#0d2340", sw=0.25, rx=0.8))
    # 5mm RGB LED
    o.append(circle(18.8, 8.0, 3.0, fill="#dfe6ee", stroke="#9aa1aa", sw=0.25))
    o.append(circle(18.8, 8.0, 2.0, fill="#f4f7fa", stroke="none"))
    o.append(circle(18.8, 8.0, 1.0, fill="#cdd6df", stroke="none"))
    for i in range(3):
        o.append(rect(9.4, 4.4 + i * 2.6, 4.4, 1.5, fill="#d8c9a0", stroke="#a89a74", sw=0.12, rx=0.35))
    o.append(text(20.9, 2.6, "RGB", 1.6, "#e7eef6", "middle", 800))
    pins = {}
    for i, name in enumerate(("R", "G", "B", "GND")):
        x = 3.4
        y = 2.6 + i * 3.0
        o.append(rect(x - 1.1, y - 1.1, 2.2, 2.2, fill=HEADER, stroke="#000", sw=0.1, rx=0.25))
        o.append(rect(x - 0.55, y - 0.55, 1.1, 1.1, fill=GOLD))
        o.append(text(x + 2.7, y + 0.5, ("R", "G", "B", "-")[i], 1.2, "#e7eef6", "middle", 700))
        pins[name] = (x, y)
    return Part("rgb", w, h, "".join(o), pins)


# ── 능동 부저 모듈 ───────────────────────────────────────────────────
def buzzer_module():
    """능동 부저 모듈. 20×15 PCB, Ø11 부저. 핀 "S","VCC","GND"는 왼쪽 가장자리."""
    w, h = 20.0, 15.0
    o = []
    o.append(rect(0, 0, w, h, fill="#1b3f6b", stroke="#0d2340", sw=0.25, rx=0.8))
    o.append(circle(12.8, 8.0, 5.4, fill=BUZZER_BLACK, stroke="#0b0d10", sw=0.3))
    o.append(circle(12.8, 8.0, 2.0, fill="#101317", stroke="none"))
    o.append(circle(12.8, 8.0, 0.6, fill=BUZZER_BLACK, stroke="none"))
    o.append(text(16.4, 3.6, "+", 2.2, "#e7eef6", "middle", 800))
    pins = {}
    for i, name in enumerate(("S", "VCC", "GND")):
        x = 4.4
        y = 3.0 + i * 3.4
        o.append(rect(x - 1.1, y - 1.1, 2.2, 2.2, fill=HEADER, stroke="#000", sw=0.1, rx=0.25))
        o.append(rect(x - 0.55, y - 0.55, 1.1, 1.1, fill=GOLD))
        o.append(text(x + 2.5, y + 0.5, ("S", "+", "-")[i], 1.2, "#e7eef6", "middle", 700))
        pins[name] = (x, y)
    return Part("buzzer", w, h, "".join(o), pins)


# ── 저항 ────────────────────────────────────────────────────────────
_BAND = {0: "#1a1a1a", 1: "#7a4a22", 2: "#d62f2f", 3: "#f08a24", 4: "#f2c230",
         5: "#2f9e44", 6: "#2f6fd6", 7: "#8a4fd8", 8: "#8a8f98", 9: "#f5f5f0"}


def _bands(ohm):
    """4밴드 저항 색. (1k → 갈·검·빨·금)"""
    v = int(ohm)
    exp = 0
    while v >= 100 and v % 10 == 0:
        v //= 10
        exp += 1
    mant = v
    if mant >= 100:
        mant //= 10
        exp += 1
    if mant >= 100:
        mant //= 10
        exp += 1
    d1, d2 = mant // 10, mant % 10
    return [_BAND[d1], _BAND[d2], _BAND[exp], GOLD]


def resistor(ohm):
    """축형 저항. 전체 길이 16mm(다리 3.5+몸통 9+3.5). 핀 "1"(왼쪽), "2"(오른쪽)."""
    body = 9.0
    lead = 3.5
    w = body + lead * 2 + 0.6
    h = 5.8
    cy = 2.2
    o = []
    o.append(line(0, cy, lead + 0.3, cy, stroke=SILVER, sw=0.55))
    o.append(line(w - lead - 0.3, cy, w, cy, stroke=SILVER, sw=0.55))
    o.append(rect(lead + 0.3, cy - 1.7, body, 3.4, fill="#d9c79c", stroke="#a9986f", sw=0.18, rx=1.4))
    cols = _bands(ohm)
    for i, c in enumerate(cols):
        o.append(rect(lead + 1.5 + i * 1.85, cy - 1.7, 0.95, 3.4, fill=c, stroke="none"))
    o.append(text(w / 2, h - 0.35, _ohm_label(ohm), 1.35, "#4a3f26", "middle", 700))
    return Part("res", w, h, "".join(o), {"1": (0, cy), "2": (w, cy)})


def _ohm_label(ohm):
    v = int(ohm)
    if v >= 1000000:
        return "%gM" % (v / 1000000.0)
    if v >= 1000:
        return "%gk" % (v / 1000.0)
    return "%d" % v


# ── USB 부품 ────────────────────────────────────────────────────────
def micro_usb_plug():
    """마이크로 USB 플러그(케이블 쪽). 16×7.5. 핀 "tip"은 커넥터가 들어가는 왼쪽 끝 중심."""
    w, h = 16.0, 7.5
    o = []
    o.append(rect(0, 1.4, 7.6, 4.7, fill="#aeb5bd", stroke="#7d838b", sw=0.25, rx=0.6))
    o.append(rect(0, 2.2, 5.4, 3.1, fill="#6b7078", stroke="none", rx=0.4))
    o.append(rect(6.9, 0.7, 3.0, 6.1, fill="#c3c9d0", stroke="#8d949c", sw=0.3, rx=1.1))
    o.append(rect(9.4, 2.4, 6.6, 2.7, fill="#2b2f34", stroke="#111", sw=0.18, rx=1.2))
    o.append(rect(2.0, 3.2, 1.2, 1.1, fill="#3a3f45", stroke="none", rx=0.2))
    return Part("usbplug", w, h, "".join(o), {"tip": (0, h / 2)})


def phone_charger():
    """휴대폰 충전기(USB-A 포트가 아래). 45(높이)×30(폭). 핀 "usb"는 포트 중심."""
    w, h = 30.0, 45.0
    o = []
    o.append(rect(0, 0, w, h, fill="#f2f3f4", stroke="#c9ccd1", sw=0.35, rx=2.4))
    o.append(rect(2.0, 2.0, w - 4.0, h - 4.0, fill="#fbfbfc", stroke="none", rx=1.8))
    o.append(text(w / 2, 15.0, "5V", 4.2, "#8b9098", "middle", 800))
    o.append(text(w / 2, 21.0, "2A", 3.0, "#a8adb4", "middle", 700))
    # USB-A 포트(아래)
    o.append(rect(8.2, h - 8.2, 13.6, 7.4, fill="#20242a", stroke="#0b0d10", sw=0.25, rx=0.6))
    o.append(rect(9.6, h - 7.0, 10.8, 3.2, fill="#6b7078", stroke="none", rx=0.4))
    return Part("charger", w, h, "".join(o), {"usb": (w / 2, h)})


# ── 브레드보드 전원 레일 한 줄 ───────────────────────────────────────
def rail_strip(length_mm):
    """브레드보드에서 떼어 낸 전원 레일 한 줄. + 줄과 - 줄이 나란히 있고 2.54 간격 구멍.

    핀 "+1".."+n"은 위(+), "-1".."-n"은 아래(-) 줄.
    """
    L = float(length_mm)
    h = 10.0
    y_plus, y_minus = 3.0, 7.0
    x0 = 4.0
    n = int((L - 2 * x0) / 2.54) + 1
    o = []
    # 플라스틱 몸체(반투명 흰색)
    o.append(rect(0.6, 0.4, L - 1.2, h - 0.8, fill="#f7f7f2", stroke="#cfcfc4", sw=0.3, rx=1.0))
    o.append(rect(0.6, 0.4, L - 1.2, 0.55, fill="#e2e2d6", stroke="none"))
    # 빨강·검정 안내선
    o.append(line(x0 - 1.2, y_plus, x0 + (n - 1) * 2.54 + 1.2, y_plus, stroke="#c0392b", sw=0.5))
    o.append(line(x0 - 1.2, y_minus, x0 + (n - 1) * 2.54 + 1.2, y_minus, stroke="#1c1c1c", sw=0.5))
    o.append(text(x0 - 2.2, y_plus + 0.55, "+", 1.8, "#c0392b", "middle", 800))
    o.append(text(x0 - 2.2, y_minus + 0.55, "-", 1.8, "#1c1c1c", "middle", 800))
    pins = {}
    for i in range(n):
        x = x0 + i * 2.54
        for y, sign in ((y_plus, "+"), (y_minus, "-")):
            o.append(rect(x - 0.95, y - 0.95, 1.9, 1.9, fill="#e9e7dc", stroke="#b9b7a8", sw=0.12))
            o.append(circle(x, y, 0.55, fill="#7d7d70"))
            pins["%s%d" % (sign, i + 1)] = (x, y)
    return Part("rail", L, h, "".join(o), pins)
