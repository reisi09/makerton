"""제설기지(base) 전용 부품. 1단위 = 1mm, 지역 원점 = 부품 왼쪽 위.

부품 함수는 core.Part를 돌려준다. 핀은 부품 외곽선 위(테두리)에 둔다.
공용 부품(Pico·SG90·택트·RGB·부저·저항)은 common.py에 있다.
"""
try:
    from .core import (Part, rect, circle, line, path, text, mount_hole,
                       PCB_GREEN, PCB_BLUE, PCB_BLACK, PCB_RED, GOLD, SILVER, HEADER, SILK)
except ImportError:  # `python3 docs/realparts/draw_base.py`처럼 스크립트로 실행할 때
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from core import (Part, rect, circle, line, path, text, mount_hole,
                      PCB_GREEN, PCB_BLUE, PCB_BLACK, PCB_RED, GOLD, SILVER, HEADER, SILK)

PITCH = 2.54


def _hdr3(x0, y0, names, pin_y, blue=False):
    """3핀 수 헤더(검정 플라스틱 + 금도금 핀). 반환 (svg, {이름: (x,y)})."""
    out = [rect(x0 - 1.3, y0, 3 * PITCH - 0.02 + 2.6, 2.6, fill=HEADER, stroke="#000", sw=0.12, rx=0.25)]
    pins = {}
    for i, nm in enumerate(names):
        cx = x0 + i * PITCH
        out.append(circle(cx, y0 + 1.3, 0.78, fill=GOLD, stroke="#8d6f28", sw=0.1))
        pins[nm] = (cx, pin_y)
    return "".join(out), pins


def _hdr4(x0, y0, names, pin_y):
    out = [rect(x0 - 1.3, y0, 4 * PITCH, 2.6, fill=HEADER, stroke="#000", sw=0.12, rx=0.25)]
    pins = {}
    for i, nm in enumerate(names):
        cx = x0 + i * PITCH
        out.append(circle(cx, y0 + 1.3, 0.78, fill=GOLD, stroke="#8d6f28", sw=0.1))
        pins[nm] = (cx, pin_y)
    return "".join(out), pins


# ── 센서 모듈 ────────────────────────────────────────────────────────
def dht11_module():
    """DHT11 온습도 모듈(KY-015형). 파란 PCB 28.5×12, 흰 격자 센서, 3핀 S/VCC/GND.
    헤더는 PCB 오른쪽 짧은 변에 붙는다(핀은 오른쪽 외곽선)."""
    w, h = 28.5, 16.0
    pin_y = (5.0, 7.54, 10.08)
    o = [rect(0, 2.0, 27.2, 12.0, fill="#1c5c9c", stroke="#0d3a68", sw=0.3, rx=0.7)]
    o.append(rect(0.7, 2.7, 25.8, 10.6, fill="none", stroke="#dde9f3", sw=0.25, rx=0.4))
    # 센서 하우징(격자 구멍)
    o.append(rect(2.0, 0.1, 12.0, 15.4, fill="#cfe3f1", stroke="#79aac6", sw=0.3, rx=0.9))
    o.append(rect(2.7, 0.8, 10.6, 14.0, fill="none", stroke="#a4c9dc", sw=0.2, rx=0.6))
    for r in range(5):
        for c in range(4):
            o.append(circle(3.9 + c * 2.72, 2.7 + r * 2.62, 0.62, fill="#42708d"))
    # 풀업 저항(10k)과 커패시터
    o.append(rect(16.2, 4.2, 3.4, 1.8, fill="#181818", stroke="#000", sw=0.12, rx=0.2))
    o.append(rect(17.0, 9.0, 2.2, 1.5, fill="#c9a04a", stroke="#8a6a20", sw=0.12))
    # 3핀 헤더(오른쪽)
    o.append(rect(23.6, 2.9, 3.0, 10.2, fill=HEADER, stroke="#000", sw=0.12, rx=0.25))
    pins = {}
    for nm, cy in zip(("S", "VCC", "GND"), pin_y):
        o.append(circle(25.9, cy, 0.78, fill=GOLD, stroke="#8d6f28", sw=0.1))
        pins[nm] = (w, cy)
    o.append(text(19.6, 7.6, "DHT11", 1.5, "#eaf3fa", "middle", 800))
    o.append(text(19.6, 10.2, "10k", 1.2, "#cfe0ee", "middle", 600))
    for lab, cy in zip(("S", "+", "-"), pin_y):
        o.append(text(22.4, cy + 0.45, lab, 1.15, "#eaf3fa", "middle", 800))
    return Part("DHT11 모듈", w, h, "".join(o), pins)


def water_level_sensor():
    """수위(젖음) 센서 HW-038형. 빨간 PCB 62×20, 구리 빗살 전극, 3핀 S/VCC/GND(아래 변)."""
    w, h = 62.0, 20.0
    px = (3.5, 6.04, 8.58)
    o = [rect(0, 0, w, h, fill=PCB_RED, stroke="#7c1b14", sw=0.3, rx=1.0)]
    o.append(rect(0.7, 0.7, w - 1.4, h - 1.4, fill="none", stroke="#e4b3ad", sw=0.2, rx=0.7))
    # 구리 빗살: 한쪽은 위 트레이스, 다른 쪽은 아래 트레이스에 번갈아 붙는다
    o.append(rect(12.0, 2.6, 47.5, 0.9, fill=GOLD, stroke="#9c7c2c", sw=0.1))
    o.append(rect(12.0, 14.6, 47.5, 0.9, fill=GOLD, stroke="#9c7c2c", sw=0.1))
    for i in range(17):
        x = 13.0 + i * 2.62
        if i % 2 == 0:
            o.append(rect(x - 0.5, 3.2, 1.0, 6.2, fill=GOLD, stroke="#9c7c2c", sw=0.08))
        else:
            o.append(rect(x - 0.5, 8.4, 1.0, 6.2, fill=GOLD, stroke="#9c7c2c", sw=0.08))
    # 3핀 헤더(아래 왼쪽)
    o.append(rect(2.2, 14.9, 10.2, 4.4, fill=HEADER, stroke="#000", sw=0.12, rx=0.25))
    pins = {}
    for nm, cx in zip(("S", "VCC", "GND"), px):
        o.append(circle(cx, 17.1, 0.72, fill=GOLD, stroke="#8d6f28", sw=0.1))
        pins[nm] = (cx, h)
    for lab, cx in zip(("S", "+", "-"), px):
        o.append(text(cx, 19.0, lab, 1.1, "#ffe9e6", "middle", 800))
    o.append(text(50.0, 11.6, "WATER", 1.5, "#ffe9e6", "middle", 800))
    o.append(text(50.0, 14.1, "LEVEL", 1.5, "#ffe9e6", "middle", 800))
    return Part("수위 센서", w, h, "".join(o), pins)


def light_sensor_ky018():
    """조도 모듈 KY-018형. 검은 PCB 20×17, CdS 셀, 3핀 S/VCC/GND(아래 변)."""
    w, h = 20.0, 17.0
    px = (6.0, 8.54, 11.08)
    o = [rect(0, 0, w, h, fill=PCB_BLACK, stroke="#000", sw=0.3, rx=0.8)]
    o.append(rect(0.6, 0.6, w - 1.2, h - 1.2, fill="none", stroke="#cfd4da", sw=0.2, rx=0.5))
    # CdS 셀(세라믹 기판 + 지그재그)
    o.append(circle(13.4, 6.2, 3.7, fill="#f0ead6", stroke="#b7ae93", sw=0.3))
    d = []
    for i in range(6):
        y = 3.2 + i * 1.2
        d.append("M %.2f %.2f L %.2f %.2f" % (10.7 if i % 2 == 0 else 16.1, y, 16.1 if i % 2 == 0 else 10.7, y))
    o.append(path(" ".join(d), fill="none", stroke="#8a4a1e", sw=0.32))
    o.append(circle(13.4, 6.2, 1.0, fill="none", stroke="#8a4a1e", sw=0.3))
    # 3핀 헤더(아래)
    o.append(rect(4.7, 12.4, 8.2, 4.0, fill=HEADER, stroke="#000", sw=0.12, rx=0.25))
    pins = {}
    for nm, cx in zip(("S", "VCC", "GND"), px):
        o.append(circle(cx, 14.4, 0.72, fill=GOLD, stroke="#8d6f28", sw=0.1))
        pins[nm] = (cx, h)
    o.append(text(3.4, 10.6, "CdS", 1.3, "#e6eaee", "middle", 700))
    return Part("조도 센서", w, h, "".join(o), pins)


# ── 표시 장치 ────────────────────────────────────────────────────────
def oled_091():
    """OLED 0.91인치 SSD1306 128×32. 검은 PCB 38×12, 4핀 GND/VCC/SCL/SDA(오른쪽 변)."""
    w, h = 38.0, 12.0
    py = (2.19, 4.73, 7.27, 9.81)
    o = [rect(0, 0, w, h, fill="#15181c", stroke="#000", sw=0.3, rx=0.6)]
    o.append(rect(0.5, 0.5, w - 1.0, h - 1.0, fill="none", stroke="#8f969e", sw=0.15, rx=0.4))
    # 유리 + 발광 영역
    o.append(rect(2.0, 1.7, 23.4, 8.6, fill="#0a0d11", stroke="#3a4048", sw=0.25, rx=0.4))
    o.append(rect(2.7, 2.4, 22.0, 7.2, fill="#05070a", stroke="none", rx=0.2))
    for i in range(7):
        o.append(line(2.7, 3.1 + i * 0.98, 24.7, 3.1 + i * 0.98, "#1d2a36", 0.12))
    o.append(text(13.7, 7.2, "128x32", 2.0, "#4f7fa8", "middle", 700))
    # 4핀 헤더(오른쪽)
    o.append(rect(33.6, 1.1, 3.4, 9.8, fill=HEADER, stroke="#000", sw=0.12, rx=0.25))
    pins = {}
    for nm, cy in zip(("GND", "VCC", "SCL", "SDA"), py):
        o.append(circle(36.1, cy, 0.7, fill=GOLD, stroke="#8d6f28", sw=0.1))
        pins[nm] = (w, cy)
    for lab, cy in zip(("G", "V", "C", "D"), py):
        o.append(text(32.2, cy + 0.45, lab, 1.05, "#c9d3dc", "middle", 800))
    o.append(text(27.6, 5.4, "OLED", 1.4, "#c9d3dc", "middle", 800))
    return Part("OLED 0.91", w, h, "".join(o), pins)


def lcd1602_i2c():
    """I2C 1602 LCD 앞면. 초록 PCB 80×36, 파란 화면 16×2. 백팩은 뒷면(pcf8574_backpack)."""
    w, h = 80.0, 36.0
    o = [rect(0, 0, w, h, fill=PCB_GREEN, stroke="#0d4a22", sw=0.3, rx=1.2)]
    o.append(rect(0.9, 0.9, w - 1.8, h - 1.8, fill="none", stroke="#d8e8c8", sw=0.2, rx=0.9))
    # 금속 베젤 + 유리
    o.append(rect(3.6, 3.2, 72.8, 26.4, fill="#b9c0c6", stroke="#7d858c", sw=0.3, rx=0.8))
    o.append(rect(4.6, 4.2, 70.8, 24.4, fill="#0d2f52", stroke="#081a2e", sw=0.3, rx=0.5))
    o.append(rect(6.6, 6.2, 66.8, 20.4, fill="#0a3f6e", stroke="none", rx=0.3))
    # 16×2 문자 셀
    for r in range(2):
        cy = 12.0 + r * 8.2
        for c in range(16):
            cx = 8.1 + c * 4.03
            o.append(rect(cx - 1.85, cy - 3.1, 3.7, 6.2, fill="#0d4b7e", stroke="#0a3557", sw=0.1, rx=0.2))
    for r, s in enumerate(("ICE-ZERO  BASE", "SENSOR   READY")):
        cy = 14.4 + r * 8.2
        for c, ch in enumerate(s):
            o.append(text(8.1 + c * 4.03, cy, ch, 4.0, "#dff0ff", "middle", 500))
    # 장착 구멍
    for (mx, my) in ((2.2, 2.2), (77.8, 2.2), (2.2, 33.8), (77.8, 33.8)):
        o.append(mount_hole(mx, my, 1.3, "#a8b0b6"))
    o.append(text(40, 33.4, "LCD1602  I2C 0x27", 1.5, "#e6f2dc", "middle", 700))
    return Part("LCD1602", w, h, "".join(o), {})


def pcf8574_backpack():
    """I2C 백팩(PCF8574) 뒷면. 42×22, 4핀 GND/VCC/SDA/SCL, 명암 가변저항."""
    w, h = 42.0, 22.0
    py = (7.19, 9.73, 12.27, 14.81)
    o = [rect(0, 0, w, h, fill=PCB_GREEN, stroke="#0d4a22", sw=0.3, rx=0.9)]
    o.append(rect(0.7, 0.7, w - 1.4, h - 1.4, fill="none", stroke="#cfe4bf", sw=0.18, rx=0.7))
    # PCF8574 DIP-16
    o.append(rect(11.5, 3.2, 18.0, 7.4, fill="#1b1b1b", stroke="#000", sw=0.2, rx=0.4))
    for i in range(8):
        o.append(rect(12.3 + i * 2.2, 2.3, 1.0, 1.1, fill=SILVER, stroke="#8b9198", sw=0.08))
        o.append(rect(12.3 + i * 2.2, 10.5, 1.0, 1.1, fill=SILVER, stroke="#8b9198", sw=0.08))
    o.append(circle(12.6, 4.2, 0.5, fill="#666"))
    o.append(text(20.5, 8.4, "PCF8574", 1.5, "#cfd6dd", "middle", 700))
    # 명암 가변저항(파란 트리머)
    o.append(rect(2.2, 12.6, 9.4, 7.2, fill="#1f4fa0", stroke="#12316a", sw=0.25, rx=0.6))
    o.append(circle(6.9, 16.2, 3.2, fill="#2f66c4", stroke="#12316a", sw=0.2))
    o.append(line(5.0, 16.2, 8.8, 16.2, "#dfe7f2", 0.55))
    o.append(line(6.9, 14.3, 6.9, 18.1, "#dfe7f2", 0.55))
    # 백라이트 점퍼 3핀
    for i in range(3):
        o.append(rect(30.5 + i * 2.54, 15.4, 1.9, 1.9, fill=GOLD, stroke="#8d6f28", sw=0.1, rx=0.2))
    o.append(rect(30.2, 15.1, 8.4, 2.5, fill="none", stroke="#0d4a22", sw=0.2))
    # 16핀 LCD 헤더(긴 쪽)
    o.append(rect(2.0, 0.4, 38.0, 1.9, fill=HEADER, stroke="#000", sw=0.1))
    # 4핀 I2C 헤더
    o.append(rect(w - 2.6, 6.4, 2.0, 9.4, fill=HEADER, stroke="#000", sw=0.1, rx=0.2))
    pins = {}
    for nm, cy in zip(("GND", "VCC", "SDA", "SCL"), py):
        o.append(circle(w - 1.0, cy, 0.72, fill=GOLD, stroke="#8d6f28", sw=0.1))
        pins[nm] = (w, cy)
    for nm, cy in zip(("G", "V", "D", "C"), py):
        o.append(text(w - 4.2, cy + 0.5, nm, 1.35, "#e6f2dc", "middle", 800))
    o.append(text(20.0, 14.4, "I2C 1602", 1.4, "#e6f2dc", "middle", 700))
    return Part("I2C 백팩", w, h, "".join(o), pins)


def neopixel_ring():
    """WS2812B 8픽셀 링. 바깥 Ø28, 안쪽 구멍 Ø14, 4패드 DIN/5V/GND/DOUT."""
    w, h = 32.0, 36.0
    cx, cy = 16.0, 15.0
    pad_x = (12.19, 14.73, 17.27, 19.81)
    o = [circle(cx, cy, 14.2, fill="#101216", stroke="#000", sw=0.3)]
    o.append(circle(cx, cy, 13.4, fill="#1b1f26", stroke="#2c323c", sw=0.25))
    o.append(circle(cx, cy, 7.4, fill="#ffffff", stroke="#0c0e12", sw=0.4))
    o.append(circle(cx, cy, 7.0, fill="#f7f6f2", stroke="#cfcbc0", sw=0.2))
    # 링 트레이스
    o.append(circle(cx, cy, 11.6, fill="none", stroke="#3b4552", sw=0.5))
    o.append(circle(cx, cy, 9.1, fill="none", stroke="#3b4552", sw=0.5))
    # 5050 LED 8개
    import math
    for i in range(8):
        a = math.radians(-90 + i * 45)
        lx, ly = cx + 10.4 * math.cos(a), cy + 10.4 * math.sin(a)
        o.append('<g transform="translate(%.2f %.2f) rotate(%d)">' % (lx, ly, -90 + i * 45))
        o.append(rect(-2.5, -2.5, 5.0, 5.0, fill="#f2f2ee", stroke="#b9b6ac", sw=0.25, rx=0.3))
        o.append(rect(-1.9, -1.9, 3.8, 3.8, fill="#e8e4d8", stroke="#c9c4b6", sw=0.15))
        o.append(rect(-1.35, -1.35, 2.7, 2.7, fill="#fbfbf7", stroke="#d5d0c4", sw=0.15))
        o.append(circle(0, 0, 0.55, fill="#fffdf4"))
        o.append("</g>")
    o.append(text(cx, cy + 1.0, "WS2812", 1.5, "#7d8794", "middle", 700))
    o.append(text(cx, cy + 3.0, "8", 1.6, "#7d8794", "middle", 800))
    # 4패드
    for nm, x in zip(("DIN", "5V", "GND", "DOUT"), pad_x):
        o.append(rect(x - 1.0, 31.4, 2.0, 2.2, fill=GOLD, stroke="#8d6f28", sw=0.12, rx=0.25))
    for nm, x in zip(("DIN", "5V", "G", "DOUT"), pad_x):
        o.append(text(x, 30.2, nm, 1.15, "#e8edf2", "middle", 700))
    pins = {"DIN": (pad_x[0], 33.5), "5V": (pad_x[1], 33.5), "GND": (pad_x[2], 33.5), "DOUT": (pad_x[3], 33.5)}
    return Part("네오픽셀 링", w, h, "".join(o), pins)


# ── 브레드보드 830 ───────────────────────────────────────────────────
BB_W, BB_H = 165.0, 55.0
BB_NCOL = 63
BB_ROW_Y = {"a": 13.53, "b": 16.07, "c": 18.61, "d": 21.15, "e": 23.69,
            "f": 31.31, "g": 33.85, "h": 36.39, "i": 38.93, "j": 41.47}
BB_RAIL_Y = {"top+": 5.00, "top-": 7.54, "bottom-": 47.46, "bottom+": 50.00}
BB_RAIL_N = 50
BB_RAIL_COL0 = 6  # 레일 구멍은 6번 열부터 열 격자에 맞춘다


def bb_col_x(col):
    """열 번호(0부터 62)의 x(mm)."""
    return 82.5 - 31 * PITCH + col * PITCH


def bb_hole(col, row):
    """본체 구멍 좌표(mm). col 0~62, row 'a'~'j'."""
    return (bb_col_x(col), BB_ROW_Y[row])


def bb_rail(side, i):
    """전원 레일 구멍 좌표(mm). side: 'top+'·'top-'·'bottom+'·'bottom-', i 0~49."""
    return (bb_col_x(BB_RAIL_COL0 + i), BB_RAIL_Y[side])


def breadboard_830():
    """830틴트 브레드보드 165×55. 63열×5행 두 블록 + 전원 레일 4줄, 가운데 홈."""
    w, h = BB_W, BB_H
    x0, x1 = bb_col_x(0) - 1.27, bb_col_x(BB_NCOL - 1) + 1.27
    o = ['<defs>']
    # 본체 구멍 격자(2.54 간격) — 패턴 하나로 630개를 그린다
    o.append('<pattern id="bbh" width="2.54" height="2.54" patternUnits="userSpaceOnUse" '
             'patternTransform="translate(%.3f %.3f)">' % (bb_col_x(0) - 1.27, BB_ROW_Y["a"] - 1.27))
    o.append('<rect x="0.45" y="0.45" width="1.64" height="1.64" rx="0.3" fill="#b9b3a0" stroke="#8f8875" stroke-width="0.14"/>')
    o.append('<rect x="0.86" y="0.86" width="0.82" height="0.82" rx="0.2" fill="#6f6a5b"/>')
    o.append('</pattern>')
    # 레일 구멍(가로 1줄)
    for side in ("top+", "top-", "bottom-", "bottom+"):
        o.append('<pattern id="bbr_%s" width="2.54" height="2.54" patternUnits="userSpaceOnUse" '
                 'patternTransform="translate(%.3f %.3f)">'
                 % (side.replace("+", "p").replace("-", "m"), bb_col_x(BB_RAIL_COL0) - 1.27, BB_RAIL_Y[side] - 1.27))
        o.append('<rect x="0.45" y="0.45" width="1.64" height="1.64" rx="0.3" fill="#b9b3a0" stroke="#8f8875" stroke-width="0.14"/>')
        o.append('<rect x="0.86" y="0.86" width="0.82" height="0.82" rx="0.2" fill="#6f6a5b"/>')
        o.append('</pattern>')
    o.append('</defs>')
    # 몸체
    o.append(rect(0, 0, w, h, fill="#f2eee0", stroke="#c9c2ac", sw=0.4, rx=1.6))
    o.append(rect(1.2, 1.2, w - 2.4, h - 2.4, fill="none", stroke="#d9d2bd", sw=0.25, rx=1.2))
    # 두 블록 바탕
    o.append(rect(x0 - 1.4, BB_ROW_Y["a"] - 2.4, (x1 - x0) + 2.8, BB_ROW_Y["e"] - BB_ROW_Y["a"] + 4.8,
                  fill="#eae5d5", stroke="none", rx=0.8))
    o.append(rect(x0 - 1.4, BB_ROW_Y["f"] - 2.4, (x1 - x0) + 2.8, BB_ROW_Y["j"] - BB_ROW_Y["f"] + 4.8,
                  fill="#eae5d5", stroke="none", rx=0.8))
    # 가운데 홈
    o.append(rect(2.0, BB_ROW_Y["e"] + 2.0, w - 4.0, BB_ROW_Y["f"] - BB_ROW_Y["e"] - 4.0, fill="#ddd7c4",
                  stroke="#c4bda6", sw=0.25, rx=1.0))
    # 구멍 격자
    o.append(rect(x0 - 1.27, BB_ROW_Y["a"] - 1.27, (x1 - x0) + 2.54, BB_ROW_Y["e"] - BB_ROW_Y["a"] + 2.54,
                  fill="url(#bbh)", stroke="none"))
    o.append(rect(x0 - 1.27, BB_ROW_Y["f"] - 1.27, (x1 - x0) + 2.54, BB_ROW_Y["j"] - BB_ROW_Y["f"] + 2.54,
                  fill="url(#bbh)", stroke="none"))
    # 전원 레일
    for side, col in (("top+", "#d8483f"), ("top-", "#2f6fd6"), ("bottom-", "#2f6fd6"), ("bottom+" , "#d8483f")):
        y = BB_RAIL_Y[side]
        o.append(rect(bb_col_x(BB_RAIL_COL0) - 1.6, y - 1.05, (BB_RAIL_N - 1) * PITCH + 3.2, 2.1,
                      fill=col, stroke="none", rx=0.5, extra='opacity="0.55"'))
        key = side.replace("+", "p").replace("-", "m")
        o.append(rect(bb_col_x(BB_RAIL_COL0) - 1.27, y - 1.27, (BB_RAIL_N - 1) * PITCH + 2.54, 2.54,
                      fill="url(#bbr_%s)" % key, stroke="none"))
    # 레일 표시(+/-)
    for side, sign in (("top+", "+"), ("top-", "−"), ("bottom-", "−"), ("bottom+", "+")):
        cy = BB_RAIL_Y[side]
        o.append(text(bb_col_x(BB_RAIL_COL0) - 3.4, cy + 0.6, sign, 1.8, "#5d5747", "middle", 800))
        o.append(text(bb_col_x(BB_RAIL_COL0 + BB_RAIL_N - 1) + 3.4, cy + 0.6, sign, 1.8, "#5d5747", "middle", 800))
    # 열 번호·행 글자
    for c in range(0, BB_NCOL, 5):
        o.append(text(bb_col_x(c), 3.0, str(c + 1), 1.35, "#8b8470", "middle", 700))
        o.append(text(bb_col_x(c), 52.4, str(c + 1), 1.35, "#8b8470", "middle", 700))
    o.append(text(bb_col_x(BB_NCOL - 1) + 1.4, 3.0, "63", 1.35, "#8b8470", "middle", 700))
    o.append(text(bb_col_x(BB_NCOL - 1) + 1.4, 52.4, "63", 1.35, "#8b8470", "middle", 700))
    for row, y in BB_ROW_Y.items():
        o.append(text(1.0, y + 0.55, row, 1.3, "#8b8470", "middle", 700))
        o.append(text(w - 1.0, y + 0.55, row, 1.3, "#8b8470", "middle", 700))
    o.append(text(w / 2, h - 3.0, "830 tie-points  ·  63 × 5 × 2  +  4 × 50", 1.5, "#a8a08a", "middle", 600))
    return Part("브레드보드 830", w, h, "".join(o), {})


# ── 기지 구조물 ──────────────────────────────────────────────────────
def dht_post():
    """우드락 기둥에 DHT11 모듈을 붙인 모습. 케이블은 기둥을 타고 내려와 오른쪽으로 나간다."""
    w, h = 34.0, 152.0
    o = []
    # 기둥(5mm 우드락) — 앞면 + 옆면
    o.append(rect(6.0, 26.0, 20.0, 118.0, fill="#f8f5ec", stroke="#cdc6b4", sw=0.3))
    o.append(rect(26.0, 26.0, 3.0, 118.0, fill="#e3ddcc", stroke="#cdc6b4", sw=0.3))
    o.append(rect(6.0, 26.0, 20.0, 2.2, fill="#efe9d9", stroke="#cdc6b4", sw=0.25))
    # 받침
    o.append(rect(2.0, 144.0, 30.0, 8.0, fill="#f4f0e4", stroke="#c6bfae", sw=0.3))
    o.append(rect(2.0, 144.0, 30.0, 2.0, fill="#e7e1d0", stroke="#c6bfae", sw=0.25))
    # DHT11 모듈(기둥 위 모서리에 붙임)
    mod = dht11_module()
    o.append('<g transform="translate(3.00 3.00)">%s</g>' % mod.svg)
    # 보강 브래킷
    o.append(rect(3.0, 22.6, 4.5, 2.0, fill="#e9e3d2", stroke="#c6bfae", sw=0.2))
    # 케이블: 모듈 핀에서 기둥 옆으로
    o.append(path("M 14.5 26.0 C 14.5 40, 11.0 44, 11.0 60 L 11.0 140", fill="none", stroke="#3a3a3a", sw=1.5))
    o.append(path("M 14.5 26.0 C 14.5 40, 11.0 44, 11.0 60 L 11.0 140", fill="none", stroke="#7a4a22", sw=0.5,
                  extra='opacity="0.9"'))
    o.append(circle(14.5, 26.2, 1.5, fill="#1a1a1a", stroke="#000", sw=0.15))
    o.append(text(16.0, 62.0, "DHT11", 1.4, "#7a7566", "start", 700))
    o.append(text(16.0, 66.0, "N 기둥", 1.3, "#9a9484", "start", 600))
    pins = {"S": (34.0, 138.0), "VCC": (34.0, 141.0), "GND": (34.0, 144.0)}
    for nm, (px, py) in pins.items():
        o.append(rect(px - 1.6, py - 1.2, 1.6, 2.4, fill="#1a1a1a", stroke="#000", sw=0.1, rx=0.2))
    return Part("DHT 기둥", w, h, "".join(o), pins)


def silo_gate():
    """사일로 깔때기 + SG90 패들 게이트(단면). 출구 Ø12, 패들이 출구를 막는다."""
    w, h = 212.0, 122.0
    o = []
    # 깔때기(종이·PET 원뿔)
    o.append(path("M 8 2 L 204 2 L 116 66 L 96 66 Z", fill="#efe7d6", stroke="#b7a98d", sw=0.45))
    for i in range(1, 6):
        y = 2 + i * 10.5
        k = (i * 10.5) / 64.0
        xa, xb = 8 + (96 - 8) * k, 204 + (116 - 204) * k
        o.append(line(xa, y, xb, y, "#d9cdb4", 0.22))
    # 깔때기 안 자갈(염화칼슘 알갱이)
    for (gx, gy) in ((30, 14), (44, 22), (62, 11), (76, 26), (94, 17), (110, 30), (128, 13), (146, 24),
                     (160, 12), (176, 20), (52, 34), (86, 38), (142, 36), (168, 32), (70, 44), (120, 44)):
        o.append(circle(gx, gy, 1.7, fill="#cfc9bd", stroke="#a79f8f", sw=0.15))
    # 출구관
    o.append(rect(95.0, 66.0, 22.0, 12.0, fill="#f4efe2", stroke="#b7a98d", sw=0.4))
    o.append(rect(99.0, 66.0, 14.0, 12.0, fill="#ffffff", stroke="#cfc7b4", sw=0.2))
    # 패들(게이트)
    o.append(rect(97.6, 78.0, 16.8, 2.6, fill="#f2f2ee", stroke="#a9a496", sw=0.3, rx=0.4))
    o.append(line(106.0, 78.4, 106.0, 80.2, "#8e8a7d", 0.4))
    # SG90(옆면) + 혼
    o.append(rect(124.0, 78.0, 24.0, 12.6, fill="#2f6fd6", stroke="#18407f", sw=0.35, rx=0.6))
    o.append(rect(121.0, 76.0, 3.6, 16.6, fill="#2f6fd6", stroke="#18407f", sw=0.3))
    o.append(rect(147.4, 76.0, 3.6, 16.6, fill="#2f6fd6", stroke="#18407f", sw=0.3))
    o.append(rect(130.0, 82.0, 12.0, 6.0, fill="#1c1c1c", stroke="#000", sw=0.2, rx=0.4))
    o.append(circle(123.2, 74.4, 3.4, fill="#f4f2ea", stroke="#b3ad9c", sw=0.3))
    o.append(rect(122.4, 70.6, 1.6, 4.6, fill="#f4f2ea", stroke="#b3ad9c", sw=0.25))
    o.append(line(114.0, 74.4, 114.0, 79.3, "#dcd8cc", 2.6))
    o.append(rect(112.6, 74.0, 12.0, 3.0, fill="#f4f2ea", stroke="#b3ad9c", sw=0.3, rx=0.5))
    # 서보 케이블
    o.append(path("M 147.0 88.0 C 158 88, 162 96, 176 96", fill="none", stroke="#3a3a3a", sw=1.6))
    o.append(path("M 147.0 88.0 C 158 88, 162 96, 176 96", fill="none", stroke="#f08a24", sw=0.6))
    o.append(rect(176.0, 94.4, 5.0, 3.2, fill="#1a1a1a", stroke="#000", sw=0.1, rx=0.3))
    o.append(text(158.0, 108.0, "SG90", 1.9, "#5c6b7a", "middle", 800))
    pins = {"SIG": (183.0, 93.0), "5V": (183.0, 96.0), "GND": (183.0, 99.0)}
    for nm, (px, py) in pins.items():
        o.append(rect(px - 1.0, py - 1.0, 2.0, 2.0, fill="#c9a04a", stroke="#8a6a20", sw=0.1))
    return Part("사일로 게이트", w, h, "".join(o), pins)
