"""제설차 실물 배선도·조립도를 만든다.

    python3 docs/realparts/draw_car.py

결과: docs/img/real_car_wiring.svg, docs/img/real_car_assembly.svg
좌표는 화면 px, 부품 내부는 mm다. 배선도는 7px = 1mm(부품 실물 크기 그대로).
계약 7절(제설차 Pico) 배선표를 그대로 그린다.
"""
import os
import sys
import xml.dom.minidom

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import core                                     # noqa: E402
import common                                   # noqa: E402
import car                                      # noqa: E402
from core import (                              # noqa: E402
    place, wire, rect, circle, line, path, text, text_px, svg_doc, WIRE,
)

IMG = os.path.join(_ROOT, "docs", "img")
NAVY = "#012a4a"
YALE = "#013a63"
CER = "#2c7da0"
STEEL = "#61a5c2"
LIGHT = "#a9d6e5"

S = 7.0          # 배선도 px/mm
A = 4.0          # 조립도 px/mm


# ── 작은 도구 ────────────────────────────────────────────────────────
def jw(o, pts, color, label=None, at=0.5, width=3.4):
    o.append(wire(pts, color=color, width=width, label=label, label_at=at))


def tag(o, x, y, s, color=NAVY, size=11):
    w = size * 0.62 * len(s) + 10
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="#ffffff" '
             'stroke="%s" stroke-width="1.2" opacity="0.95"/>' % (x - w / 2, y - size * 0.78, w, size * 1.55, color))
    o.append(text_px(x, y + size * 0.36, s, size, color, "middle", 800))


def dot(o, x, y, color="#1a1a1a", r=4.2):
    o.append(circle(x, y, r, fill=color, stroke="#ffffff", sw=1.4))


def panel(o, x, y, w, h, title=None, fill="#f7fafc"):
    o.append(rect(x, y, w, h, fill=fill, stroke="#cfe0ea", sw=1.6, rx=10))
    if title:
        o.append(text_px(x + 14, y + 22, title, 15, NAVY, "start", 800))


def arrow(o, x1, y1, x2, y2, color=CER, sw=2.0):
    o.append(line(x1, y1, x2, y2, stroke=color, sw=sw))
    dx, dy = x2 - x1, y2 - y1
    l = (dx * dx + dy * dy) ** 0.5 or 1
    ux, uy = dx / l, dy / l
    px, py = -uy, ux
    o.append(path("M %.1f %.1f L %.1f %.1f L %.1f %.1f Z" % (
        x2, y2, x2 - ux * 10 + px * 5, y2 - uy * 10 + py * 5, x2 - ux * 10 - px * 5, y2 - uy * 10 - py * 5),
        fill=color, stroke=color, sw=0.5))


# ── 배선도 ──────────────────────────────────────────────────────────
def pinlab(o, x, y, s, side, color=NAVY):
    """Pico 핀 이름표. side="l"이면 글자가 핀 왼쪽(보드 밖)에 붙는다."""
    w = 5.7 * len(s) + 13
    bx = x - w if side == "l" else x
    o.append(rect(bx, y - 7.4, w, 14.8, fill="#ffffff", stroke="#b9c9d4", sw=0.9, rx=7.4))
    o.append(text_px(bx + w / 2, y + 3.8, s, 9.8, color, "middle", 700))


def build_wiring():
    o = []
    W, H = 1800, 1100

    o.append(text_px(36, 44, "제설차 배선도 — 실물 부품", 28, NAVY, "start", 800))
    o.append(text_px(36, 70, "Pico 2 W · 28BYJ-48 ×2 · ULN2003 ×2 · SG90 · HC-SR04 · RGB · 부저 · 택트    (부품은 7px = 1mm 실물 크기)",
                     12.5, CER, "start", 700))

    pins = {}
    svg, pins["chg"] = place(common.phone_charger(), 30, 88, 6.3, rot=270)
    o.append(svg)
    o.append(text_px(124, 266, "휴대폰 충전기 5V", 12, NAVY, "middle", 800))

    svg, pins["pico"] = place(common.pico2wh(), 1000, 300, S, rot=90)
    o.append(svg)
    o.append(text_px(1002, 676, "Pico 2 W", 12.5, NAVY, "start", 800))

    svg, pins["uln1"] = place(car.uln2003_board(), 380, 331, S)
    o.append(svg)
    o.append(text_px(380, 322, "ULN2003 #1 — 왼쪽 모터", 12.5, NAVY, "start", 800))
    svg, pins["uln2"] = place(car.uln2003_board(), 380, 595, S)
    o.append(svg)
    o.append(text_px(380, 586, "ULN2003 #2 — 오른쪽 모터", 12.5, NAVY, "start", 800))

    svg, pins["m1"] = place(car.motor_28byj48(), 36, 289, S)
    o.append(svg)
    svg, pins["m2"] = place(car.motor_28byj48(), 36, 553, S)
    o.append(svg)
    for ty in (356, 620):
        o.append(text_px(30, ty, "28BYJ-48", 11.5, NAVY, "start", 800).replace(
            '<text', '<text transform="rotate(-90 %.1f %.1f)"' % (30, ty)))

    svg, pins["rail"] = place(common.rail_strip(90), 1090, 140, S)
    o.append(svg)

    svg, pins["sg"] = place(common.sg90(), 580, 700, S)
    o.append(svg)
    o.append(text_px(720, 884, "SG90 살포 서보", 12.5, NAVY, "middle", 800))

    svg, pins["tact"] = place(common.tact_switch(), 890, 690, S)
    o.append(svg)
    o.append(text_px(892, 782, "택트", 11, NAVY, "start", 800))

    svg, pins["rgb"] = place(common.rgb_led_module(), 1240, 560, S)
    o.append(svg)
    o.append(text_px(1330, 552, "3색 LED 모듈", 12, NAVY, "middle", 800))

    svg, pins["buz"] = place(common.buzzer_module(), 1240, 380, S)
    o.append(svg)
    o.append(text_px(1310, 372, "능동 부저 모듈", 12, NAVY, "middle", 800))

    svg, pins["sr"] = place(car.hcsr04(), 1240, 720, S)
    o.append(svg)
    o.append(text_px(1240, 712, "HC-SR04 초음파", 12, NAVY, "start", 800))

    P, C, U1, U2, R = pins["pico"], pins["chg"], pins["uln1"], pins["uln2"], pins["rail"]
    M1, M2, SG, T, RGB, BZ, SR = pins["m1"], pins["m2"], pins["sg"], pins["tact"], pins["rgb"], pins["buz"], pins["sr"]

    # 충전기 → 마이크로 USB → Pico
    ux, uy = 1073.0, 258.0
    o.append('<path d="M %.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f" '
             'fill="none" stroke="#101214" stroke-width="6.5" stroke-linecap="round" opacity="0.92"/>' % (
                 C["usb"][0], C["usb"][1], C["usb"][0] + 40, 248, 360, 272, 620, 276,
                 840, 266, 1000, 250, ux - 16, uy))
    o.append(place(common.micro_usb_plug(), ux - 16, uy - 3.75 * S, S)[0])
    tag(o, 470, 238, "마이크로 USB 케이블 — 위에서 매단 유선", "#101214", 11.5)

    # VBUS(40) → 레일 +, GND(38) → 레일 −
    jw(o, [(P["40"][0], P["40"][1]), (P["40"][0], R["+2"][1])], "red", None)
    o.append(circle(R["+2"][0], R["+2"][1], 4.6, fill=WIRE["red"], stroke="#fff", sw=1.2))
    jw(o, [(P["38"][0], P["38"][1]), (R["-3"][0], P["38"][1]), (R["-3"][0], R["-3"][1])], "black", None)
    o.append(circle(R["-3"][0], R["-3"][1], 4.6, fill="#1a1a1a", stroke="#fff", sw=1.2))

    # ULN 전원
    jw(o, [(R["+1"][0], R["+1"][1]), (660, R["+1"][1]), (660, U2["+"][1]), (U2["+"][0], U2["+"][1])], "red", None)
    jw(o, [(R["-1"][0], R["-1"][1]), (680, R["-1"][1]), (680, U2["-"][1]), (U2["-"][0], U2["-"][1])], "black", None)
    jw(o, [(660, U1["+"][1]), (U1["+"][0], U1["+"][1])], "red", None)
    jw(o, [(680, U1["-"][1]), (U1["-"][0], U1["-"][1])], "black", None)
    dot(o, 660, U1["+"][1], WIRE["red"])
    dot(o, 680, U1["-"][1], WIRE["black"])
    tag(o, 800, R["+1"][1], "레일 +5V", WIRE["red"], 11)
    tag(o, 800, R["-1"][1], "레일 GND", "#111", 11)

    # 오른쪽 배전(Y자 점퍼) — 레일 오른쪽 끝에서 내려가 모듈마다 물린다
    jw(o, [(R["+33"][0], R["+33"][1]), (1740, R["+33"][1]), (1740, 905), (SR["VCC"][0], 905),
           (SR["VCC"][0], SR["VCC"][1])], "red", None)
    jw(o, [(R["-33"][0], R["-33"][1]), (1758, R["-33"][1]), (1758, 870), (SR["Gnd"][0], 870),
           (SR["Gnd"][0], SR["Gnd"][1])], "black", None)
    dot(o, 1740, 905, WIRE["red"])
    dot(o, 1758, 870, "#111")
    tag(o, 1700, 760, "5V", WIRE["red"], 10.5)
    tag(o, 1700, 800, "GND", "#111", 10.5)

    # SG90 전원 — 같은 배전선에 Y로 합류
    jw(o, [(1740, 905), (1740, 1030), (868, 1030), (868, SG["5V"][1]), (SG["5V"][0], SG["5V"][1])], "red", None)
    jw(o, [(1758, 870), (1758, 1052), (880, 1052), (880, SG["GND"][1]), (SG["GND"][0], SG["GND"][1])], "black", None)

    # 신호: Pico → ULN
    for grp, uln, pairs in (
            (1, U1, (("4", "IN1", "blue", "GP2"), ("5", "IN2", "green", "GP3"),
                     ("6", "IN3", "yellow", "GP4"), ("7", "IN4", "orange", "GP5"))),
            (2, U2, (("9", "IN1", "purple", "GP6"), ("10", "IN2", "blue", "GP7"),
                     ("11", "IN3", "green", "GP8"), ("12", "IN4", "yellow", "GP9")))):
        for pn, un, col, lab in pairs:
            jw(o, [(P[pn][0], P[pn][1]), (uln[un][0] + 30, P[pn][1]), (uln[un][0] + 30, uln[un][1]),
                   (uln[un][0], uln[un][1])], col, None, 0.5, 3.0)
            pinlab(o, P[pn][0] - 12, P[pn][1], lab, "l")

    # 모터 → ULN 소켓
    for a, b, col in (("W1", "M1", "blue"), ("W2", "M2", "pink"), ("W3", "M3", "yellow"),
                      ("W4", "M4", "orange"), ("W5", "M5", "red")):
        jw(o, [M1[a], U1[b]], col, None, width=2.8)
        jw(o, [M2[a], U2[b]], col, None, width=2.8)

    # SG90 신호
    jw(o, [(SG["SIG"][0], SG["SIG"][1]), (975, SG["SIG"][1]), (975, P["20"][1]), (P["20"][0], P["20"][1])],
       "orange", None)
    pinlab(o, P["20"][0] - 12, P["20"][1], "GP15", "l")

    # 택트
    jw(o, [(T["A1"][0], T["A1"][1]), (T["A1"][0] + 5, P["19"][1]), (P["19"][0], P["19"][1])], "blue", None)
    pinlab(o, P["19"][0] - 12, P["19"][1], "GP14", "l")
    jw(o, [(T["B2"][0], T["B2"][1]), (1100, T["B2"][1]), (1100, 975), (1758, 975)], "black", None)
    dot(o, 1758, 975, "#111")

    # 초음파 + 분압
    jw(o, [(SR["Trig"][0], SR["Trig"][1]), (SR["Trig"][0], 880), (1210, 880), (1210, P["21"][1]), (P["21"][0], P["21"][1])],
       "yellow", None)
    pinlab(o, P["21"][0] + 13, P["21"][1], "GP16", "r")
    r1 = place(common.resistor(1000), 1180, 903, S)
    o.append(r1[0])
    jw(o, [(SR["Echo"][0], SR["Echo"][1]), (SR["Echo"][0], r1[1]["2"][1]), (r1[1]["2"][0], r1[1]["2"][1])], "green", None)
    node = r1[1]["1"]
    r2 = place(common.resistor(2000), node[0] - 20.3, node[1], S, rot=90)
    o.append(r2[0])
    jw(o, [node, (node[0], P["22"][1]), (P["22"][0], P["22"][1])], "green", None)
    pinlab(o, P["22"][0] + 13, P["22"][1], "GP17", "r")
    top2 = min(r2[1].values(), key=lambda v: v[1])
    bot2 = max(r2[1].values(), key=lambda v: v[1])
    jw(o, [node, top2], "black", None)
    dot(o, node[0], node[1], "#2f9e44")
    jw(o, [bot2, (bot2[0], 1052)], "black", None)
    dot(o, bot2[0], 1052, "#111")
    tag(o, 1252, 886, "1kΩ", "#2f9e44", 10.5)
    tag(o, 1116, 990, "2kΩ", "#111", 10.5)
    tag(o, 1300, 958, "분압: Echo 5V → GP17 3.3V", CER, 10.5)

    # RGB
    for pn, nm, col, lab in (("24", "R", "red", "GP18"), ("25", "G", "green", "GP19"), ("26", "B", "blue", "GP20")):
        jw(o, [(RGB[nm][0], RGB[nm][1]), (P[pn][0], P[pn][1])], col, None, 0.5, 3.0)
        pinlab(o, P[pn][0] + 13, P[pn][1], lab, "r")
    jw(o, [(RGB["GND"][0], RGB["GND"][1]), (P["23"][0], P["23"][1])], "black", None, 0.5, 3.0)
    pinlab(o, P["23"][0] + 13, P["23"][1], "GND", "r")

    # 부저
    jw(o, [(BZ["VCC"][0], BZ["VCC"][1]), (P["36"][0], P["36"][1])], "red", None)
    jw(o, [(BZ["S"][0], BZ["S"][1]), (P["27"][0], P["27"][1])], "purple", None)
    jw(o, [(BZ["GND"][0], BZ["GND"][1]), (P["28"][0], P["28"][1])], "black", None)
    for pn, lab in (("36", "3V3"), ("27", "GP21"), ("28", "GND"), ("40", "VBUS"), ("38", "GND")):
        pinlab(o, P[pn][0] + 13, P[pn][1], lab, "r")

    # 주석
    for i, (t, col) in enumerate((
            ("전원: VBUS(40) → 레일 + , GND(38) → 레일 − . 모듈의 5V·GND는 모두 이 레일에서 받는다.", NAVY),
            ("레일이 브레드보드에서 분리되지 않으면, 오른쪽 끝에서 내려가는 Y자 점퍼 두 가닥으로 대신한다.", CER),
            ("신호선은 Pico 핀 이름표를 따라간다. 5V 빨강 · GND 검정 · 신호는 파랑·초록·노랑·주황·보라.", YALE))):
        o.append(text_px(1200, 252 + i * 21, t, 12, col, "start", 700))

    # 구석 inset
    panel(o, 1150, 14, 600, 100, fill="#fdfaf4")
    o.append(place(car.battery_holder_3aa(), 1160, 22, 1.35)[0])
    o.append(text_px(1250, 40, "대안 전원: AA 3개 홀더 (보조배터리가 없을 때)", 13.5, NAVY, "start", 800))
    o.append(text_px(1250, 62, "＋ → VSYS(39) 와 레일 + ,  − → GND.  USB 업로드할 때는 홀더를 뺀다.", 12, CER, "start", 700))
    o.append(text_px(1250, 84, "AA 3개 = 4.5V. 서보·모터가 같이 돌면 전압이 떨어져 시연은 충전기 전원을 쓴다.", 11.5, YALE, "start", 600))
    o.append(text_px(1250, 104, "홀더 ＋ 는 VSYS(39)에만 붙인다(레일에 바로 붙이면 역류한다).", 11.5, "#8a4a22", "start", 600))

    # 범례
    panel(o, 40, 880, 570, 185, "선 색과 표기")
    for i, (col, lab) in enumerate((("red", "5V"), ("black", "GND"), ("blue", "신호"), ("green", "신호"),
                                    ("yellow", "신호"), ("orange", "서보·모터"), ("purple", "부저"))):
        cx = 58 + (i % 4) * 136
        cy = 922 + (i // 4) * 30
        o.append(line(cx, cy, cx + 34, cy, stroke=WIRE[col], sw=3.4))
        o.append(text_px(cx + 40, cy + 5, lab, 12, NAVY, "start", 700))
    for i, t in enumerate([
            "· 흰 사각형 = 듀폰 커넥터가 꽂힌 자리.  왼쪽 ULN = 왼쪽 바퀴, 오른쪽 ULN = 오른쪽 바퀴.",
            "· 두 ULN 은 IN1~IN4 만 다르고 나머지 배선 모양이 같다.",
            "· 모듈마다 핀 순서가 다르다(RGB·부저). 꽂기 전에 모듈 실크를 먼저 확인한다.",
            "· 택트는 한 다리 GP14, 대각 다리 GND. 두 ULN 은 IN1~IN4 만 다르다.",
            "· 28BYJ-48 은 마주 보게 달아 오른쪽 모터만 코드에서 방향을 뒤집는다."]):
        o.append(text_px(58, 984 + i * 20, t, 11.5, YALE, "start", 600))

    return svg_doc(W, H, "".join(o), "제설차 배선도(실물 부품)")


# ── 조립도 ──────────────────────────────────────────────────────────
def build_assembly():
    o = []
    W, H = 1800, 1100
    o.append(text_px(36, 46, "제설차 조립도 — 실물 부품", 28, NAVY, "start", 800))
    o.append(text_px(36, 72, "하판 100×150 우드락 2겹 · 전체 113×150×약 95 · 바퀴 Ø65×8 · 4px = 1mm", 13, CER, "start", 700))

    # ── (a) 위에서 ──
    px, py = 150.0, 280.0
    PX = lambda v: px + v * A
    PY = lambda v: py + v * A
    o.append(text_px(px, 150, "(a) 위에서", 15, NAVY, "start", 800))
    o.append(text_px(px, 172, "앞이 위(북) · 뒤 범퍼가 아래", 11.5, CER, "start", 700))

    # 바퀴(위에서 = 8×65 띠) — 하판 뒤에 그려 가장자리만 보인다
    wheels = []
    for cx in (-6.5, 98.5):
        x0, y0 = PX(cx), PY(42.5)
        ww, hh = 8 * A, 65 * A
        wheels.append(rect(x0, y0, ww, hh, fill="#26282c", stroke="#111", sw=1.2, rx=6))
        wheels.append(rect(x0 + 2.4, y0 + 4, ww - 4.8, hh - 8, fill="#e9dfc6", stroke="#cfc2a2", sw=1.1, rx=4))
        wheels.append(rect(x0 + 2.4, y0 + hh / 2 - 9, ww - 4.8, 18, fill="#d9cba6", stroke="#b6a882", sw=1.1))
        wheels.append(rect(x0 + ww / 2 - 5, y0 + hh / 2 - 3, 10, 6, fill="#ffffff", stroke="#8f969f", sw=1))
    o.extend(wheels)
    o.append(text_px(PX(-6.5) - 10, PY(42.5) + 8, "Ø65", 10.5, NAVY, "end", 800))

    # 하판
    o.append(place(car.chassis_plate(), PX(0), PY(0), A)[0])

    # 모터(마주 보게, 축은 바깥) — 위에서 본 Ø28 몸통
    for mx, sgn in ((16.0, -1), (84.0, 1)):
        cxm, cym = PX(mx), PY(75)
        r = 14 * A
        o.append(rect(cxm - r, cym - 20 * A / 2 - 6, r * 2, 10, fill="#c2c8cf", stroke="#98a0a8", sw=1.2, rx=3))
        o.append(rect(cxm - r, cym + 20 * A / 2 - 4, r * 2, 10, fill="#c2c8cf", stroke="#98a0a8", sw=1.2, rx=3))
        o.append(circle(cxm, cym, r, fill="#c2c8cf", stroke="#7f878f", sw=1.4))
        o.append(circle(cxm, cym, r - 6, fill="#2b5fa8", stroke="#1b4478", sw=1.2))
        o.append(rect(cxm - 6, cym - 4, 12, 8, fill="#dfe4e9", stroke="#8f969f", sw=1))
        # 축 → 바퀴
        o.append(line(cxm + sgn * r, cym, cxm + sgn * (r + 26), cym, stroke="#9aa1aa", sw=5))
        # 리드선 → 안쪽
        o.append(line(cxm - sgn * (r - 4), cym + 16, cxm - sgn * 34, cym + 26, stroke="#d62f2f", sw=2.2))
        o.append(line(cxm - sgn * (r - 4), cym + 10, cxm - sgn * 34, cym + 20, stroke="#f2c230", sw=2.2))

    # 호퍼
    o.append(place(car.hopper(), PX(25), PY(40), A)[0])
    # ULN 두 장
    for ux, nm in ((2.0, "ULN#1"), (68.0, "ULN#2")):
        o.append(place(car.uln2003_board(), PX(ux), PY(4), A)[0])
        o.append(text_px(PX(ux + 17.5), PY(4) + 62, nm, 10.5, "#ffffff", "middle", 800))
    # SR-04(앞면)
    o.append(place(car.hcsr04(), PX(26), PY(-21), A)[0])
    o.append(text_px(PX(48.5), PY(-22.5), "HC-SR04", 10.5, NAVY, "middle", 800))
    # 범퍼판
    o.append(rect(PX(20), PY(146), 60 * A, 4 * A, fill="#c9d9e4", stroke=YALE, sw=1.4, rx=3))
    o.append(text_px(PX(50), PY(142), "범퍼판 60×30", 10.5, YALE, "middle", 700))
    # Pico(세워서 뒤쪽, USB는 뒤 범퍼 쪽)
    o.append(place(common.pico2wh(), PX(76), PY(96), A, rot=90)[0])
    # 전원 레일
    o.append(place(common.rail_strip(58), PX(4), PY(114), A)[0])
    o.append(text_px(PX(33), PY(126), "전원 레일", 10.5, YALE, "middle", 700))
    # 택트·RGB·부저
    o.append(place(common.tact_switch(), PX(4), PY(94), A * 1.3)[0])
    o.append(place(common.rgb_led_module(), PX(40), PY(92), A * 0.85)[0])
    o.append(place(common.buzzer_module(), PX(4), PY(44), A * 0.85)[0])
    o.append(text_px(PX(3), PY(134), "받침: 우드락 22 + 병뚜껑 13 ×2 (아래)", 10.5, YALE, "start", 700))
    # USB 케이블 — 그림 위 바깥에서 오른쪽 빈틈으로 내려와 Pico 위로 꽂힌다
    o.append('<path d="M 592 96 L 592 632 Q 592 645 579 645 L 509 645 Q 496 645 496 658 L 496 664" '
             'fill="none" stroke="#101214" stroke-width="5" stroke-linecap="round" opacity="0.9"/>')
    o.append(text_px(600, 120, "USB 케이블 — 위에서 매단다", 11, "#101214", "start", 800))

    # 치수
    o.append(line(PX(0), PY(160), PX(100), PY(160), stroke=CER, sw=1.2))
    o.append(text_px(PX(50), PY(172), "100 (하판 폭) · 전체 113(바퀴 포함)", 11.5, CER, "middle", 700))
    o.append(line(PX(-22), PY(0), PX(-22), PY(150), stroke=CER, sw=1.2))
    o.append(text_px(PX(-22) - 6, PY(75), "150", 11.5, CER, "middle", 700).replace(
        '<text', '<text transform="rotate(-90 %.1f %.1f)"' % (PX(-22) - 6, PY(75))))

    # 조립 번호(①~⑫) — car_build.svg 와 같은 자리
    for i, (vx, vy) in enumerate([(96, 50), (10, 84), (-2.5, 40), (44, 84), (6, 10), (86, 140),
                                  (62, 46), (50, 86), (50, -4), (94, 92), (50, 148), (30, 96)], 1):
        o.append(circle(PX(vx), PY(vy), 10.5, fill=NAVY, stroke="#ffffff", sw=1.8))
        o.append(text_px(PX(vx), PY(vy) + 4, str(i), 10.5, "#ffffff", "middle", 800))

    # ── (b) 옆에서 ──
    gx, gy = 640.0, 890.0
    o.append(text_px(gx - 20, 206, "(b) 옆에서 — 앞이 오른쪽", 15, NAVY, "start", 800))
    o.append(line(gx - 40, gy, 1290, gy, stroke=NAVY, sw=2.5))
    for k in range(int(gx) - 34, 1290, 24):
        o.append(line(k, gy, k - 8, gy + 11, stroke=STEEL, sw=1.5))
    wr = 65 * A / 2
    wcx = gx + 75 * A
    wheel_svg = [circle(wcx, gy - wr, wr, fill="#3a3d42", stroke="#1f2226", sw=2),
                 circle(wcx, gy - wr, wr - 3.0, fill="#e9dfc6", stroke="#cfc2a2", sw=1.4),
                 circle(wcx, gy - wr, 24, fill="#d9cba6", stroke="#b6a882", sw=1.2),
                 rect(wcx - 8, gy - wr - 4, 16, 8, fill="#ffffff", stroke="#8f969f", sw=1)]
    o.extend(wheel_svg)

    deck = gy - 38 * A
    o.append(rect(gx, deck, 150 * A, 12, fill="#f3f1ea", stroke="#cbc7b8", sw=1.6, rx=2))
    o.append(text_px(gx + 8, deck - 8, "하판(우드락 2겹, 12)", 11, YALE, "start", 700))
    # 호퍼
    o.append(rect(gx + 40 * A, deck - 55 * A, 50 * A, 55 * A, fill="#f4f6f8", stroke="#c2c8d0", sw=1.8, rx=4))
    o.append(text_px(gx + 65 * A, deck - 32 * A, "호퍼 55", 12, NAVY, "middle", 800))
    o.append(rect(gx + 40 * A, deck - 55 * A, 50 * A, 6, fill="#e6ebef", stroke="#c2c8d0", sw=1.2))
    # SG90 패들(호퍼 바닥)
    o.append(rect(gx + 56 * A, deck - 14 * A, 14 * A, 12 * A, fill="#2b6cb8", stroke="#1e4f8a", sw=1.4, rx=3))
    # 살포구
    o.append(rect(gx + 60 * A, deck, 12 * A, 5, fill="#3a3f45", stroke="#22262b", sw=1.2))
    o.append('<path d="M %.1f %.1f L %.1f %.1f" stroke="%s" stroke-width="3" stroke-dasharray="4 4"/>' % (
        gx + 66 * A, deck + 20, gx + 66 * A, gy - 6, STEEL))
    o.append(text_px(gx + 66 * A + 8, gy - 26, "살포구 → 도로", 11, YALE, "start", 800))
    # ULN(앞쪽, 납작)
    o.append(rect(gx + 2 * A, deck - 3.2 * A, 32 * A, 3.2 * A, fill="#1d5fa8", stroke="#123f73", sw=1.2, rx=2))
    o.append(rect(gx + 66 * A, deck - 3.2 * A, 32 * A, 3.2 * A, fill="#1d5fa8", stroke="#123f73", sw=1.2, rx=2))
    o.append(text_px(gx + 34 * A, deck - 3.2 * A - 6, "ULN #1·#2", 10.5, "#1d5fa8", "middle", 800))
    # Pico
    o.append(rect(gx + 104 * A, deck - 21 * A, 7 * A, 21 * A, fill="#2e6b46", stroke="#1d4a2f", sw=1.4, rx=2))
    o.append(text_px(gx + 107.5 * A, deck - 9 * A, "Pico", 9.5, "#ffffff", "middle", 800))
    # 전원 레일
    o.append(rect(gx + 12 * A, deck - 10.5 * A, 58 * A, 8 * A, fill="#f7f7f2", stroke="#cfcfc4", sw=1.2, rx=2))
    o.append(text_px(gx + 41 * A, deck - 10.5 * A - 7, "전원 레일", 10.5, YALE, "middle", 800))
    # SR-04(앞면)
    o.append(rect(gx + 126 * A, deck - 20 * A, 20 * A, 20 * A, fill="#1d5fa8", stroke="#123f73", sw=1.4, rx=3))
    o.append(circle(gx + 136 * A, deck - 10 * A, 5.4 * A, fill="#c9ced6", stroke="#7f878f", sw=1.2))
    o.append(circle(gx + 136 * A, deck - 10 * A, 3.2 * A, fill="#8f969f", stroke="none"))
    o.append(text_px(gx + 136 * A, deck - 21 * A, "HC-SR04", 10.5, "#1d5fa8", "middle", 800))
    # 모터(바퀴 뒤, 점선)
    o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="#98a0a8" stroke-width="1.6" '
             'stroke-dasharray="6 4"/>' % (wcx, gy - wr, 14 * A))
    o.append(text_px(wcx + 60, gy - wr - 4, "바퀴 Ø65 · 모터 Ø28(뒤)", 11, YALE, "start", 700))
    # 병뚜껑 받침
    for bx in (16, 128):
        sx = gx + bx * A
        o.append(rect(sx + 20, gy - 35 * A, 20 * A, 22 * A, fill="#f3f1ea", stroke="#cbc7b8", sw=1.4, rx=2))
        o.append(rect(sx, gy - 13 * A, 30 * A, 13 * A, fill="#2f6fd6", stroke="#1d4b96", sw=1.4, rx=3))
        o.append(rect(sx + 4, gy - 13 * A, 30 * A - 8, 3 * A, fill="#3f82e0", stroke="none", rx=2))
    o.append(text_px(gx + 16 * A + 60, gy + 36, "받침 = 우드락 22 + 병뚜껑 13 (하판 바닥 35)", 10.5, YALE, "middle", 700))
    # 유선 USB
    o.append('<path d="M %.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f" fill="none" stroke="#101214" '
             'stroke-width="5" stroke-linecap="round"/>' % (
                 gx + 107 * A, deck - 21 * A, gx + 108 * A, deck - 34 * A, gx + 112 * A, deck - 54 * A,
                 gx + 122 * A, deck - 64 * A))
    o.append(text_px(gx + 124 * A, deck - 62 * A, "위로 매단 USB", 11, "#101214", "start", 800))
    o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="#1f2226" stroke-width="2" '
             'stroke-dasharray="10 6" opacity="0.55"/>' % (wcx, gy - wr, wr))
    # 치수
    o.append(line(gx, deck - 55 * A, gx + 150 * A, deck - 55 * A, stroke=CER, sw=1.1))
    o.append(text_px(gx + 75 * A, deck - 55 * A - 8, "150 (길이)", 11.5, CER, "middle", 700))
    o.append(line(gx - 30, deck - 55 * A, gx - 30, gy, stroke=CER, sw=1.1))
    o.append(text_px(gx - 30, deck - 55 * A - 14, "약 95", 11.5, CER, "middle", 700))

    # ── (c) 조립 순서 ──
    cx0 = 1330.0
    o.append(text_px(cx0, 216, "(c) 조립 순서 ①~⑫", 15, NAVY, "start", 800))
    for i, line_s in enumerate([
            "하판 100×150 재단(2겹)", "모터 브래킷 고정", "바퀴 3겹 원판 접착",
            "D축 구멍 3×5 뚫기", "바퀴·고무줄 장착", "ULN2003 ×2 부착",
            "Pico·전원 레일 부착", "호퍼 접착·바닥 구멍", "SG90 패들 장착",
            "SR-04 앞면 장착", "LED·부저·택트·범퍼", "배선·보정 시험"]):
        y = 252 + i * 33
        o.append(circle(cx0 + 11, y - 5, 11, fill=NAVY, stroke="#ffffff", sw=1.6))
        o.append(text_px(cx0 + 11, y - 1, str(i + 1), 10.5, "#ffffff", "middle", 800))
        o.append(text_px(cx0 + 32, y, line_s, 12.5, "#1f3b52", "start", 600))
    for i, t in enumerate([
            "치수: 하판 100×150, 바퀴 Ø65×8(고무줄 포함 71)",
            "모터 귀 구멍 35 간격 — 브래킷 없이 하판에 직접 나사",
            "호퍼 입구 = 뒤 범퍼에서 75 (사기 사일로 출구와 같은 자리)",
            "무게: 뒤쪽 Pico·레일, 가운데 호퍼, 앞쪽 ULN·SR-04",
            "보조배터리 대신 휴대폰 충전기 → 마이크로 USB(위에서 매단다)"]):
        o.append(text_px(cx0 - 10, 680 + i * 22, t, 11.5, YALE, "start", 600))

    o.append(text_px(36, 1000, "바퀴는 우드락 3겹 원판 Ø65 에 고무줄을 걸어 타이어로 쓴다. D축 구멍 3×5 를 뚫어 모터 축에 바로 끼운다.",
                     13, NAVY, "start", 700))
    o.append(text_px(36, 1024, "모터 두 개는 마주 보게 달아 축이 바깥으로 나가고, 오른쪽 모터는 코드에서 방향을 반전한다(CONTRACT 7절).",
                     13, CER, "start", 600))
    o.append(text_px(36, 1048, "번호 ①~⑫는 car_build.svg 와 같은 자리다. ⑦은 배터리 대신 전원 레일을 붙이는 순서로 바뀌었다.",
                     13, YALE, "start", 600))
    return svg_doc(W, H, "".join(o), "제설차 조립도(실물 부품)")


def main():
    if not os.path.isdir(IMG):
        os.makedirs(IMG)
    jobs = (("real_car_wiring.svg", build_wiring), ("real_car_assembly.svg", build_assembly))
    for name, fn in jobs:
        body = fn()
        xml.dom.minidom.parseString(body)          # 파싱 확인
        path = os.path.join(IMG, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        print("wrote %s (%d bytes)" % (path, len(body.encode("utf-8"))))


if __name__ == "__main__":
    main()
