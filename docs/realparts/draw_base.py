# -*- coding: utf-8 -*-
"""제설기지 실물 배선도·조립도를 그린다.

실행: python3 docs/realparts/draw_base.py
결과: docs/img/real_base_wiring.svg · docs/img/real_base_assembly.svg
"""
import math
import os
import sys
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.dirname(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import base as B
from core import place, svg_doc, text_px, WIRE

try:  # 패키지 경로
    from realparts import common as C
except ImportError:  # python3 docs/realparts/draw_base.py
    import common as C

IMG_DIR = os.path.join(os.path.dirname(HERE), "img")

TITLE = "#012a4a"     # 제목·주석 팔레트
SUB = "#2a6f97"
FAB = "#1f3b52"
PAPER = "#f7f9fb"
PANEL = "#eef4f8"
PANEL_LINE = "#c9dbe8"
WARN = "#8a6a20"


# ── 배선도 좌표 ──────────────────────────────────────────────────────
S = 4.0
WV, HV = 1900, 1150
BB_X, BB_Y = 620.0, 330.0

PICO_C0 = 21      # 핀 1번을 꽂는 열
ROW_N, ROW_S = "b", "g"   # Pico 북쪽·남쪽 핀 줄
ROW_HOLE_N, ROW_HOLE_S = "a", "h"   # 점퍼를 꽂는 빈 줄


def bx(mm):
    return BB_X + mm * S


def by(mm):
    return BB_Y + mm * S


def hole(col, row):
    x, y = B.bb_hole(col, row)
    return (bx(x), by(y))


def rail(side, i):
    x, y = B.bb_rail(side, i)
    return (bx(x), by(y))


def rail_y(side):
    return by(B.BB_RAIL_Y[side])


RAIL_TP, RAIL_TN = rail_y("top+"), rail_y("top-")
RAIL_BN, RAIL_BP = rail_y("bottom-"), rail_y("bottom+")


def near_rail_x(side, x):
    """레일에서 x에 가장 가까운 구멍의 x."""
    best = None
    for i in range(B.BB_RAIL_N):
        hx = rail(side, i)[0]
        if best is None or abs(hx - x) < abs(best - x):
            best = hx
    return best


def north_x(pin):
    return bx(B.bb_col_x(PICO_C0 + (40 - pin)))


def south_x(pin):
    return bx(B.bb_col_x(PICO_C0 + (pin - 1)))


# ── SVG 선 도구 ──────────────────────────────────────────────────────
def _straight(out, p0, p1, hop_x, hop_y, hh=4.6):
    (x0, y0), (x1, y1) = p0, p1
    if abs(y1 - y0) < 0.6:
        xs = sorted([x for x in hop_x if min(x0, x1) < x < max(x0, x1)],
                    reverse=(x1 < x0))
        for x in xs:
            s = 1 if x1 > x0 else -1
            out.append("L %.2f %.2f " % (x - hh * s, y0))
            out.append("A %.2f %.2f 0 0 %d %.2f %.2f " % (hh, hh, 1 if s > 0 else 0, x + hh * s, y0))
        out.append("L %.2f %.2f " % (x1, y1))
    elif abs(x1 - x0) < 0.6:
        ys = sorted([y for y in hop_y if min(y0, y1) < y < max(y0, y1)],
                    reverse=(y1 < y0))
        for y in ys:
            s = 1 if y1 > y0 else -1
            out.append("L %.2f %.2f " % (x0, y - hh * s))
            out.append("A %.2f %.2f 0 0 %d %.2f %.2f " % (hh, hh, 1 if s > 0 else 0, x0, y + hh * s))
        out.append("L %.2f %.2f " % (x1, y1))
    else:
        out.append("L %.2f %.2f " % (x1, y1))


def path_d(pts, hop_x=(), hop_y=(), corner=14.0):
    pts = [tuple(p) for p in pts]
    out = ["M %.2f %.2f " % pts[0]]
    n = len(pts)
    for i in range(n - 1):
        p0, p1 = pts[i], pts[i + 1]
        if i > 0:
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            L = math.hypot(dx, dy) or 1.0
            c = min(corner, L * 0.45)
            s = (p0[0] + dx / L * c, p0[1] + dy / L * c)
            out.append("Q %.2f %.2f %.2f %.2f " % (p0[0], p0[1], s[0], s[1]))
        else:
            s = p0
        if i < n - 2:
            p2 = pts[i + 2]
            dx, dy = p0[0] - p1[0], p0[1] - p1[1]
            L = math.hypot(dx, dy) or 1.0
            c = min(corner, L * 0.45)
            e = (p1[0] + dx / L * c, p1[1] + dy / L * c)
        else:
            e = p1
        _straight(out, s, e, hop_x, hop_y)
    return "".join(out)


def pill(x, y, label, color, size=11.0, fill="#ffffff"):
    tw = 12.0
    for ch in label:
        tw += size * (0.62 if ord(ch) < 128 else 0.99)
    return ('<rect x="%.1f" y="%.1f" width="%.1f" height="19" rx="9.5" fill="%s" stroke="%s" '
            'stroke-width="1.7"/>' % (x - tw / 2, y - 9.5, tw, fill, color)
            + text_px(x, y + 4.7, label, size, TITLE, "middle", 800))


def jumper(pts, color, w=3.4, label=None, hop_x=(), hop_y=(), lab=None, lsize=11.0):
    d = path_d(pts, hop_x=hop_x, hop_y=hop_y)
    col = WIRE.get(color, color)
    out = ['<path d="%s" fill="none" stroke="#0e1b26" stroke-opacity="0.20" stroke-width="%.1f" '
           'stroke-linecap="round" stroke-linejoin="round" transform="translate(1.2 1.8)"/>'
           % (d, w + 1.6),
           '<path d="%s" fill="none" stroke="%s" stroke-width="%.1f" stroke-linecap="round" '
           'stroke-linejoin="round"/>' % (d, col, w)]
    for (x, y) in (pts[0], pts[-1]):
        out.append('<rect x="%.1f" y="%.1f" width="8" height="8" rx="1.6" fill="#1a1a1a" '
                   'stroke="%s" stroke-width="1.6"/>' % (x - 4, y - 4, col))
    if label:
        if lab is None:
            best, bi = -1.0, 0
            for i in range(len(pts) - 1):
                L = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                if L > best:
                    best, bi = L, i
            (x0, y0), (x1, y1) = pts[bi], pts[bi + 1]
            lab = (x0 + (x1 - x0) * 0.5, y0 + (y1 - y0) * 0.5)
        out.append(pill(lab[0], lab[1], label, col, lsize))
    return "".join(out)


def tx(x, y, s, size=13, fill=FAB, anchor="start", weight=600):
    return text_px(x, y, s, size, fill, anchor, weight)


# ── 배선도 ──────────────────────────────────────────────────────────
# ── 배선도 ──────────────────────────────────────────────────────────
def build_wiring():
    o = ['<rect width="100%%" height="100%%" fill="%s"/>' % PAPER]
    o.append(tx(40, 50, "제설기지 실물 배선도 — Pico 2 W · 브레드보드 830", 30, TITLE, weight=800))
    o.append(tx(40, 84, "부품은 실제 치수·색·핀 배열로 그렸다. 1mm = 4px.  선 색: 3V3 주황 · 5V 빨강 · GND 검정.",
                16, SUB, weight=600))

    lx, ly = 1424, 96
    o.append('<rect x="%d" y="%d" width="436" height="196" rx="12" fill="%s" stroke="%s" stroke-width="2"/>'
             % (lx, ly, PANEL, PANEL_LINE))
    o.append(tx(lx + 18, ly + 30, "읽는 법", 17, TITLE, weight=800))
    for i, (c, t) in enumerate((("orange", "3V3 — 36번에서 아래 + 레일로"),
                                ("red", "5V · VBUS — 40번에서 위 + 레일로"),
                                ("black", "GND — 위·아래 − 레일 두 줄"))):
        yy = ly + 58 + i * 26
        o.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="6" stroke-linecap="round"/>'
                 % (lx + 20, yy, lx + 62, yy, WIRE[c]))
        o.append(tx(lx + 72, yy + 5, t, 13, FAB))
    o.append(tx(lx + 18, ly + 146, "· 선 끝 검은 사각형 = 듀폰 커넥터를 꽂은 구멍", 12.5, FAB))
    o.append(tx(lx + 18, ly + 168, "· 반원 = 다른 선·레일 위를 넘어간 곳(연결 아님)", 12.5, FAB))
    o.append(tx(lx + 18, ly + 190, "· 같은 열 5구멍은 한 노드 → Pico 옆 빈 줄에 꽂는다", 12.5, FAB))

    # ── 브레드보드 + Pico ──
    s_bb, _ = place(B.breadboard_830(), BB_X, BB_Y, S)
    o.append(s_bb)
    pico = C.pico2wh()
    _, p0 = place(pico, 0, 0, S, 0)
    ax, ay = hole(PICO_C0, ROW_S)
    ox, oy = ax - p0["1"][0], ay - p0["1"][1]
    s_pico, pp = place(pico, ox, oy, S, 0)
    o.append(s_pico)

    def put(part, x, y, rot=0):
        s, pins = place(part, x, y, S, rot)
        o.append(s)
        return pins

    # ── 위쪽 부품 ──
    light = put(B.light_sensor_ky018(), 780, 214)
    o.append(tx(820, 200, "조도 KY-018 (W 그늘)", 13.5, TITLE, "middle", 800))
    water = put(B.water_level_sensor(), 926, 118)
    o.append(tx(1050, 104, "수위(젖음) 센서 — W 갈래 길가", 13.5, TITLE, "middle", 800))
    ring = put(B.neopixel_ring(), 1170, 96)
    o.append(tx(1234, 82, "네오픽셀 링 (지붕 경광등)", 13.5, TITLE, "middle", 800))

    # ── 아래쪽 부품 ──
    put(B.lcd1602_i2c(), 60, 566)
    o.append(tx(220, 552, "LCD1602 (기지 전광판)", 13.5, TITLE, "middle", 800))
    bp = put(B.pcf8574_backpack(), 380, 582)
    o.append(tx(464, 568, "I2C 백팩 — LCD 뒷면", 13.5, TITLE, "middle", 800))
    o.append(tx(380, 692, "명암 가변저항을 돌려 글자를 선명하게.", 11.5, WARN))
    oled = put(B.oled_091(), 560, 556)
    o.append(tx(636, 542, "OLED 0.91\" 128×32", 13.5, TITLE, "middle", 800))

    dhts = []
    for i, (cx, nm) in enumerate(((60, "N"), (180, "E"), (300, "S"), (420, "W"))):
        p = put(B.dht11_module(), cx, 790)
        dhts.append((nm, p))
        o.append(tx(cx + 57, 780, "DHT11 %s 기둥" % nm, 12.5, TITLE, "middle", 800))

    sg = put(C.sg90(), 60, 960)
    rgb = put(C.rgb_led_module(), 280, 960)
    bz = put(C.buzzer_module(), 410, 960)
    tc = put(C.tact_switch(), 520, 990)
    o.append(tx(140, 946, "SG90 보충 게이트", 12.5, TITLE, "middle", 800))
    o.append(tx(330, 946, "3색 LED", 12.5, TITLE, "middle", 800))
    o.append(tx(450, 946, "능동 부저", 12.5, TITLE, "middle", 800))
    o.append(tx(600, 1042, "도킹 택트", 11.5, TITLE, "start", 800))

    # ── 전원 레일 ──
    p36, p38, p40 = pp["36"], pp["38"], pp["40"]
    o.append(jumper([p36, (p36[0], 260), (water["VCC"][0], 260), water["VCC"]],
                    "orange", 3.6, label="3V3", lab=(p36[0] + 40, 260), hop_y=[RAIL_TP, RAIL_TN]))
    o.append(jumper([light["VCC"], (light["VCC"][0], 300), (p36[0], 300)], "orange", 3.0))
    o.append(jumper([p38, (p38[0], RAIL_TN + 2)], "black", 3.4))
    o.append(pill(p38[0] + 58, RAIL_TN - 28, "GND", WIRE["black"]))
    o.append(jumper([p40, (p40[0], RAIL_TP + 2)], "red", 3.4, hop_y=[RAIL_TN],
                    label="5V", lab=(p40[0] - 62, RAIL_TP - 24)))
    e_tn = rail("top-", B.BB_RAIL_N - 1)
    e_bn = rail("bottom-", B.BB_RAIL_N - 1)
    o.append(jumper([(e_tn[0], RAIL_TN), (e_tn[0] + 44, RAIL_TN), (e_tn[0] + 44, RAIL_BN),
                     (e_bn[0], RAIL_BN)], "black", 3.2, label="GND",
                    lab=(e_tn[0] + 44, (RAIL_TN + RAIL_BN) / 2)))

    # ── 북쪽 신호 ──
    YA = hole(PICO_C0, ROW_HOLE_N)[1]
    o.append(jumper([water["S"], (water["S"][0], YA)], "green", 3.6, label="GP26",
                    hop_y=[RAIL_TP, RAIL_TN], lab=(water["S"][0] + 56, 316)))
    o.append(jumper([light["S"], (north_x(32), light["S"][1] + 34), (north_x(32), YA)],
                    "yellow", 3.6, label="GP27", hop_y=[RAIL_TP, RAIL_TN],
                    lab=(light["S"][0] + 52, light["S"][1] + 34)))
    o.append(jumper([ring["DIN"], (north_x(21), ring["DIN"][1]), (north_x(21), YA)],
                    "purple", 3.6, label="GP16", hop_y=[RAIL_TP, RAIL_TN],
                    lab=(north_x(21) + 78, ring["DIN"][1])))
    o.append(jumper([ring["5V"], (ring["5V"][0], 252), (1200, 252), (1200, RAIL_TP + 2)],
                    "red", 3.0, label="5V", lab=(ring["5V"][0] + 14, 252)))
    o.append(jumper([ring["GND"], (ring["GND"][0], 274), (1204, 274), (1204, RAIL_TN + 2)],
                    "black", 3.0, hop_y=[RAIL_TP]))
    o.append(jumper([water["GND"], (water["GND"][0], 198), (1000, 198), (1000, 340),
                     (near_rail_x("top-", 1000), 340), (near_rail_x("top-", 1000), RAIL_TN + 2)],
                    "black", 2.8))
    o.append(jumper([light["GND"], (light["GND"][0], 282), (light["GND"][0], 340),
                     (near_rail_x("top-", light["GND"][0]), 340),
                     (near_rail_x("top-", light["GND"][0]), RAIL_TN + 2)], "black", 2.8))

    # ── 배전선(아래쪽) ── 신호선보다 먼저
    RX3 = near_rail_x("bottom+", 790)
    RXG = near_rail_x("bottom-", 816)
    if abs(RXG - RX3) < 15:
        RXG = RX3 + 20.32
    o.append(jumper([(RX3, RAIL_BP), (RX3, 1036)], "orange", 3.0, label="3V3", lab=(RX3, 620)))
    o.append(jumper([(RXG, RAIL_BN), (RXG, 1036)], "black", 3.0, label="GND", lab=(RXG, 700)))
    LANE3, LANEG = 858, 868
    o.append(jumper([(174, LANE3), (RX3, LANE3)], "orange", 2.6))
    o.append(jumper([(174, LANEG), (RXG, LANEG)], "black", 2.6))
    for nm, pins in dhts:
        o.append(jumper([pins["VCC"], (pins["VCC"][0], LANE3)], "orange", 2.4))
        o.append(jumper([pins["GND"], (pins["GND"][0], LANEG)], "black", 2.4, hop_y=[LANE3]))
    LGE, LTE = 1062, 1076
    o.append(jumper([(252, LGE), (RXG, LGE)], "black", 2.6))
    o.append(jumper([(252, LTE), (RX3, LTE)], "orange", 2.6))
    o.append(jumper([bp["VCC"], (bp["VCC"][0] + 14, bp["VCC"][1]), (RX3, bp["VCC"][1])], "orange", 2.6))
    o.append(jumper([bp["GND"], (bp["GND"][0] + 14, bp["GND"][1]), (RXG, bp["GND"][1])], "black", 2.6))
    o.append(jumper([oled["VCC"], (oled["VCC"][0] + 14, oled["VCC"][1]), (RX3, oled["VCC"][1])], "orange", 2.6))
    o.append(jumper([oled["GND"], (oled["GND"][0] + 14, oled["GND"][1]), (RXG, oled["GND"][1])], "black", 2.6))
    o.append(jumper([bz["VCC"], (bz["VCC"][0] + 20, bz["VCC"][1]), (744, bz["VCC"][1]), (744, LTE)],
                    "orange", 2.6, hop_y=[LGE]))
    o.append(jumper([bz["GND"], (bz["GND"][0] + 20, bz["GND"][1]), (756, bz["GND"][1]), (756, LGE)],
                    "black", 2.6))
    o.append(jumper([rgb["GND"], (rgb["GND"][0] + 20, rgb["GND"][1]), (768, rgb["GND"][1]), (768, LGE)],
                    "black", 2.6))
    o.append(jumper([tc["A1"], (tc["A1"][0], tc["A1"][1]), (tc["A1"][0], LGE)], "black", 2.6))
    o.append(jumper([sg["GND"], (sg["GND"][0] + 16, sg["GND"][1]), (236, 1035), (780, 1035), (780, LGE)],
                    "black", 2.6))
    o.append(jumper([sg["5V"], (sg["5V"][0] + 16, sg["5V"][1]), (240, sg["5V"][1]), (240, 1088),
                     (30, 1088), (30, 344), (690, 344), (690, RAIL_TP + 2)], "red", 3.0,
                    label="5V", lab=(360, 344)))

    # ── 남쪽 신호 ──
    YS = hole(0, ROW_HOLE_S)[1]
    YJ = hole(0, "j")[1]
    o.append(jumper([bp["SDA"], (858.56 + 24, bp["SDA"][1]), (858.56 + 24, YS - 22),
                     (858.56, YS - 22)], "blue", 3.2, label="GP0", lab=(700, bp["SDA"][1])))
    o.append(jumper([bp["SCL"], (858.56, bp["SCL"][1])], "yellow", 3.2, label="GP1", lab=(812, bp["SCL"][1])))
    o.append(jumper([oled["SDA"], (south_x(21) - 10, oled["SDA"][1]),
                     (south_x(21) - 10, YJ), (south_x(21), YJ)], "blue", 3.2))
    o.append(jumper([oled["SCL"], (south_x(22) + 10, oled["SCL"][1]),
                     (south_x(22) + 10, YJ), (south_x(22), YJ)], "yellow", 3.2))
    runs = [722, 732, 742, 752]
    for i, (nm, pins) in enumerate(dhts):
        col = 24 + i
        o.append(jumper([pins["S"], (pins["S"][0], runs[i]), (south_x(col), runs[i]),
                         (south_x(col), YS)],
                        ["green", "purple", "pink", "gray"][i], 3.2,
                        label="GP%d" % (2 + i),
                        lab=((pins["S"][0] + south_x(col)) / 2, runs[i])))
    for i, k in enumerate(("R", "G", "B")):
        pinp = rgb[k]
        vx = pinp[0] + 22 + i * 10
        ry = 900 + i * 10
        o.append(jumper([pinp, (vx, pinp[1]), (vx, ry), (south_x(34 + i), ry),
                         (south_x(34 + i), YS)],
                        ["green", "blue", "pink"][i], 3.0, label="GP%d" % (10 + i),
                        lab=(600 + i * 62, ry)))
    o.append(jumper([bz["S"], (bz["S"][0] + 22, bz["S"][1]), (bz["S"][0] + 22, 930),
                     (south_x(37), 930), (south_x(37), YS)], "purple", 3.0, label="GP13", lab=(846, 930)))
    o.append(jumper([tc["B1"], (tc["B1"][0] + 14, tc["B1"][1]), (tc["B1"][0] + 14, 940),
                     (south_x(39), 940), (south_x(39), YS)], "brown", 3.0, label="GP14", lab=(930, 940)))
    o.append(jumper([sg["SIG"], (sg["SIG"][0] + 30, sg["SIG"][1]), (sg["SIG"][0] + 30, 1000),
                     (south_x(40), 1000), (south_x(40), YS)], "gray", 3.0, label="GP15", lab=(640, 1000)))

    # ── USB ──
    s_pl, _ = place(C.micro_usb_plug(), 776, 415, S, 180)
    o.append(s_pl)
    o.append(jumper([(776, 430), (600, 430), (600, 476)], "gray", 3.0))
    o.append('<rect x="586" y="470" width="28" height="14" rx="4" fill="#cfd4da" stroke="#7d838b" stroke-width="1.6"/>')
    o.append(tx(600, 506, "USB → 맥북", 12, SUB, "middle", 700))

    # ── 핀 연결표 ──
    TX, TY = 1320, 336
    o.append('<rect x="%d" y="%d" width="540" height="700" rx="12" fill="%s" stroke="%s" stroke-width="2"/>'
             % (TX, TY, PANEL, PANEL_LINE))
    o.append(tx(TX + 20, TY + 34, "핀 연결표 (계약 6절)", 17, TITLE, weight=800))
    head = (TX + 20, TX + 232, TX + 344, TX + 442)
    for x, s in zip(head, ("장치", "모듈 핀", "Pico", "선 색")):
        o.append(tx(x, TY + 62, s, 12.5, SUB, weight=800))
    rows = [
        ("DHT11 N 기둥", "S·VCC·GND", "GP2·3V3·GND", "green"),
        ("DHT11 E 기둥", "S·VCC·GND", "GP3·3V3·GND", "purple"),
        ("DHT11 S 기둥", "S·VCC·GND", "GP4·3V3·GND", "pink"),
        ("DHT11 W 기둥", "S·VCC·GND", "GP5·3V3·GND", "gray"),
        ("수위(젖음) 센서", "S", "GP26 (ADC0)", "green"),
        ("조도 KY-018", "S", "GP27 (ADC1)", "yellow"),
        ("OLED 0.91", "SDA·SCL", "GP0·GP1", "blue"),
        ("LCD1602 백팩", "SDA·SCL", "GP0·GP1", "blue"),
        ("3색 LED", "R·G·B", "GP10·11·12", "green"),
        ("능동 부저", "S", "GP13", "purple"),
        ("도킹 택트", "B1·A1", "GP14·GND", "brown"),
        ("SG90 게이트", "SIG", "GP15", "gray"),
        ("네오픽셀 링", "DIN", "GP16", "purple"),
    ]
    for i, (dev, mod, pico, col) in enumerate(rows):
        yy = TY + 90 + i * 30
        if i % 2 == 1:
            o.append('<rect x="%d" y="%d" width="500" height="30" rx="4" fill="#e3edf4"/>'
                     % (TX + 20, yy - 19))
        o.append(tx(head[0], yy, dev, 12.5, FAB, weight=700))
        o.append(tx(head[1], yy, mod, 11.5, FAB))
        o.append(tx(head[2], yy, pico, 11.5, FAB))
        o.append('<circle cx="%d" cy="%d" r="6" fill="%s"/>' % (head[3] + 8, yy - 4, WIRE[col]))
    ty = TY + 90 + 13 * 30
    o.append(tx(TX + 20, ty + 12, "전원: 3V3 = 36 · 5V(VBUS) = 40 · GND = 38", 12, SUB, weight=700))
    o.append(tx(TX + 20, ty + 36, "I2C: OLED 0x3C · LCD 0x27 — 같은 버스", 12, SUB, weight=700))
    o.append(tx(TX + 20, ty + 60, "DHT11은 0~50°C만 잰다. 실패는 null.", 12, SUB, weight=700))
    o.append(tx(TX + 20, ty + 84, "수위·조도는 3V3로 (ADC 최대 3.3V).", 12, SUB, weight=700))

    o.append(tx(40, 1104, "· DHT11 네 개는 갈래 기둥(N·E·S·W)에 세운다. 기둥은 도로 가장자리에서 30mm 밖, 중심에서 약 200mm.",
                13, FAB, weight=600))
    o.append(tx(40, 1128, "· 갈래 위험도에 따라 맥이 @@SHOW로 링 색을 바꾼다. 링 DIN은 GP16 하나뿐이다.",
                13, FAB, weight=600))
    o.append(tx(620, 700, "핀 순서는 모듈 실크 확인 (S·VCC·GND)", 11, WARN))
    o.append(tx(620, 718, "기둥까지 3선 점퍼를 묶어 약 60cm", 11, SUB))
    o.append(tx(40, 1144, "· 3색 LED R·G·B, 부저 S·VCC·GND, 네오픽셀 링 DIN·5V·GND 순서는 모듈 실크를 확인한다.",
                12.5, WARN, weight=600))
    return svg_doc(WV, HV, "".join(o), "제설기지 실물 배선도")


# ── 조립도 ──────────────────────────────────────────────────────────
AV, AH = 1800, 1100
APX, APY, AS = 60.0, 154.0, 3.0          # 평면: 원점·축척(px/mm)
SX, SY, SS = 1080.0, 620.0, 1.65         # 단면: 원점·축척


def ax(x):
    return APX + x * AS


def ay(y):
    return APY + y * AS


def arrow_h(x1, x2, y, label, size=12):
    o = ['<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.3" '
         'marker-start="url(#dimS)" marker-end="url(#dimE)"/>' % (x1, y, x2, y, SUB)]
    o.append(tx((x1 + x2) / 2, y - 7, label, size, SUB, "middle", 700))
    return "".join(o)


def arrow_v(y1, y2, x, label, size=12):
    o = ['<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.3" '
         'marker-start="url(#dimS)" marker-end="url(#dimE)"/>' % (x, y1, x, y2, SUB)]
    o.append(tx(x, (y1 + y2) / 2 + 4, label, size, SUB, "middle", 700))
    return "".join(o)


def build_assembly():
    o = ['<rect width="100%%" height="100%%" fill="%s"/>' % PAPER,
         '<defs><marker id="dimE" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
         'orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="%s"/></marker>'
         '<marker id="dimS" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="6" markerHeight="6" '
         'orient="auto"><path d="M10 0 L0 5 L10 10 z" fill="%s"/></marker>'
         '<marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
         'orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="%s"/></marker></defs>' % (SUB, SUB, TITLE)]

    o.append(tx(60, 52, "제설기지 조립도 — 실물 부품을 기지에 올린 모습", 30, TITLE, weight=800))
    o.append(tx(60, 86, "외곽 320×230 · 차고 140×190×120 · 단위 mm, 화면 3px = 1mm.  평면은 위에서, 오른쪽은 차고 단면.",
                16, SUB, weight=600))

    # ── (a) 평면 ──
    o.append(tx(60, 108, "(a) 평면 — 위에서", 18, TITLE, weight=800))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="#eae6da" stroke="#b9b2a0" '
             'stroke-width="2"/>' % (ax(0), ay(0), 320 * AS, 230 * AS))
    # 벽
    wall = "#f6f3ea"
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="#c3bca8" stroke-width="1.6"/>'
             % (ax(0), ay(0), 320 * AS, 5 * AS, wall))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="#c3bca8" stroke-width="1.6"/>'
             % (ax(0), ay(225), 320 * AS, 5 * AS, wall))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="#c3bca8" stroke-width="1.6"/>'
             % (ax(0), ay(0), 5 * AS, 230 * AS, wall))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="#c3bca8" stroke-width="1.6"/>'
             % (ax(315), ay(0), 5 * AS, 230 * AS, wall))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="#c3bca8" stroke-width="1.6"/>'
             % (ax(145), ay(5), 5 * AS, 220 * AS, wall))
    # 차고 입구 깔때기(45°, 20mm)
    o.append('<path d="M %.1f %.1f L %.1f %.1f" stroke="#012a4a" stroke-width="5" stroke-linecap="round"/>'
             % (ax(5), ay(5), ax(-8), ay(-8)))
    o.append('<path d="M %.1f %.1f L %.1f %.1f" stroke="#012a4a" stroke-width="5" stroke-linecap="round"/>'
             % (ax(145), ay(5), ax(158), ay(-8)))
    # 차고 바닥 + 안내 레일
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#dde7ee" stroke="#9fb2c2" '
             'stroke-width="1.4"/>' % (ax(5), ay(5), 140 * AS, 190 * AS))
    for rx in (5, 141):
        o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#2a6f97" opacity="0.75"/>'
                 % (ax(rx), ay(20), 4 * AS, 170 * AS))
    o.append(tx(ax(75), ay(207), "안내 레일 8mm (양쪽 벽)", 10.5, SUB, "middle", 700))
    # 관제실 바닥
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#e8f0f6" stroke="#9fb2c2" '
             'stroke-width="1.4"/>' % (ax(150), ay(5), 165 * AS, 220 * AS))
    # 도킹한 제설차(윤곽선)
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="10" fill="none" stroke="%s" '
             'stroke-width="2.6" stroke-dasharray="9 6"/>' % (ax(18.5), ay(45), 113 * AS, 150 * AS, TITLE))
    o.append(tx(ax(75), ay(150), "도킹한 제설차", 13, TITLE, "middle", 800))
    o.append(tx(ax(75), ay(164), "113×150 (윤곽선)", 10.5, SUB, "middle", 600))
    o.append(tx(ax(103), ay(34), "입구 45° · 20", 11.5, TITLE, "start", 700))
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2.4" '
             'marker-end="url(#arw)"/>' % (ax(75), ay(20), ax(75), ay(42), TITLE))
    # 범퍼판 + 도킹 스위치
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#468faf" stroke="#2a6f97" '
             'stroke-width="1.4"/>' % (ax(44.5), ay(183), 60 * AS, 11 * AS))
    o.append(tx(ax(75), ay(191), "범퍼판 60×30", 9.5, "#ffffff", "middle", 700))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="#1f2329" '
             'stroke="#000" stroke-width="1"/>' % (ax(70), ay(197), 10 * AS, 7 * AS))
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.2" '
             'stroke-dasharray="4 3"/>' % (ax(75), ay(194), ax(75), ay(197), TITLE))
    o.append(tx(ax(75), ay(214), "도킹 스위치(뒤벽 뒤 택트)", 10.5, TITLE, "middle", 700))
    # 사일로(지붕 위 — 점선)
    o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="2.2" '
             'stroke-dasharray="10 7"/>' % (ax(75), ay(120), 26 * AS, SUB))
    o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#ffffff" stroke="%s" stroke-width="2"/>'
             % (ax(75), ay(120), 6 * AS, SUB))
    o.append(tx(ax(75), ay(84), "사일로 출구 Ø12 (지붕 위)", 10.5, SUB, "middle", 700))

    # 관제실 부품(실물)
    bb = B.breadboard_830()
    s_bb, _ = place(bb, ax(150), ay(40), AS)
    o.append(s_bb)
    pk = C.pico2wh()
    _, p0 = place(pk, 0, 0, AS, 0)
    txx = ax(150) + (B.bb_col_x(PICO_C0) * AS) - p0["1"][0]
    tyy = ay(40) + (B.BB_ROW_Y["g"] * AS) - p0["1"][1]
    s_pk, _ = place(pk, txx, tyy, AS, 0)
    o.append(s_pk)
    o.append(tx(ax(232), ay(30), "브레드보드 830 + Pico 2 W", 11.5, TITLE, "middle", 700))
    s_l, _ = place(B.lcd1602_i2c(), ax(215), ay(180), AS)
    o.append(s_l)
    o.append(tx(ax(255), ay(222), "LCD1602 (앞벽)", 10.5, TITLE, "middle", 700))
    s_o, _ = place(B.oled_091(), ax(228), ay(150), AS)
    o.append(s_o)
    o.append(tx(ax(228) + 40, ay(146), "OLED 0.91\"", 9.5, TITLE, "start", 700))
    s_r, _ = place(C.rgb_led_module(), ax(160), ay(170), AS)
    o.append(s_r)
    o.append(tx(ax(172), ay(192), "3색 LED", 9.5, TITLE, "middle", 700))
    s_b, _ = place(C.buzzer_module(), ax(190), ay(170), AS)
    o.append(s_b)
    o.append(tx(ax(200), ay(192), "부저", 9.5, TITLE, "middle", 700))
    # 지붕 링(점선)
    o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="2" '
             'stroke-dasharray="7 5"/>' % (ax(250), ay(100), 14 * AS, SUB))
    o.append(tx(ax(250), ay(122), "네오픽셀 링(지붕)", 10.5, SUB, "middle", 700))
    # 케이블 통로
    o.append('<path d="M %.1f %.1f L %.1f %.1f" stroke="%s" stroke-width="8" stroke-linecap="round" '
             'stroke-dasharray="14 10" opacity="0.65"/>'
             % (ax(147), ay(210), ax(300), ay(210), "#2c7da0"))
    o.append(tx(ax(224), ay(206), "케이블 통로", 10.5, "#1f5f7a", "middle", 700))

    # 치수
    o.append(arrow_h(ax(0), ax(320), ay(230) + 28, "320"))
    o.append(arrow_v(ay(0), ay(230), ax(0) - 30, "230"))
    o.append(arrow_h(ax(5), ax(145), ay(14), "140"))
    

    # 맥북
    o.append('<rect x="96" y="890" width="300" height="150" rx="8" fill="#e9eef3" stroke="#9fb2c2" stroke-width="2"/>')
    o.append('<rect x="112" y="902" width="268" height="112" rx="5" fill="#3d4b59"/>')
    o.append('<rect x="120" y="908" width="252" height="100" rx="3" fill="#6d879e"/>')
    o.append(text_px(246, 964, "ICE-ZERO", 22, "#eaf4ff", "middle", 800))
    o.append('<rect x="82" y="1042" width="328" height="12" rx="4" fill="#cfd8e0" stroke="#9fb2c2" stroke-width="1.6"/>')
    o.append(tx(410, 1046, "맥북 — 서버·모델 (Pico는 USB 시리얼)", 12, SUB, "start", 700))
    o.append('<path d="M 396 970 C 470 970, 470 812, 520 812" fill="none" stroke="%s" stroke-width="3"/>' % WIRE["gray"])
    o.append(tx(470, 798, "USB", 10.5, SUB, "middle", 700))

    # ── (b) 단면 ──
    o.append(tx(SX, 312, "(b) 차고 단면 — 입구가 왼쪽", 18, TITLE, weight=800))

    def sx(mm):
        return SX + mm * SS

    def sy(mm):
        return SY + mm * SS

    floor = sy(0)
    ceil = sy(-120)
    # 바닥
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="3"/>'
             % (sx(-10), floor, sx(200), floor, TITLE))
    for gx in range(-8, 200, 9):
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#b9b2a0" stroke-width="1.1"/>'
                 % (sx(gx), floor, sx(gx - 4), floor + 9))
    # 벽·지붕
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#f6f3ea" stroke="#c3bca8" stroke-width="1.8"/>'
             % (sx(190), ceil, 5 * SS, 120 * SS))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#f6f3ea" stroke="#c3bca8" stroke-width="1.8"/>'
             % (sx(-5), ceil - 5 * SS, 200 * SS, 5 * SS))
    # 차(윤곽선)
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="8" fill="none" stroke="%s" '
             'stroke-width="2.4" stroke-dasharray="9 6"/>'
             % (sx(40), sy(-95), 150 * SS, 95 * SS, TITLE))
    o.append(tx(sx(105), sy(-58), "제설차", 13, TITLE, "middle", 800))
    o.append(tx(sx(105), sy(-40), "150×95", 10.5, SUB, "middle", 600))
    # 호퍼 입구
    o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#ffffff" stroke="%s" stroke-width="2.2"/>'
             % (sx(115), sy(-95), 5 * SS, "#b3261e"))
    # 범퍼 + 스위치
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#468faf" stroke="#2a6f97" stroke-width="1.4"/>'
             % (sx(185), sy(-30), 5 * SS, 30 * SS))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="#1f2329" stroke="#000"/>'
             % (sx(196), sy(-16), 5 * SS, 8 * SS))
    o.append(tx(sx(203), sy(-22), "도킹 스위치", 10.5, TITLE, "start", 700))
    # 사일로(지붕 위)
    o.append('<path d="M %.1f %.1f L %.1f %.1f L %.1f %.1f L %.1f %.1f Z" fill="#efe7d6" stroke="#b7a98d" '
             'stroke-width="1.8"/>' % (sx(115 - 100), sy(-150), sx(115 + 100), sy(-150),
                                       sx(115 + 14), ceil, sx(115 - 14), ceil))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#ffffff" stroke="#b7a98d" stroke-width="1.6"/>'
             % (sx(115 - 6), ceil, 12 * SS, 10 * SS))
    o.append(tx(sx(115), sy(-161), "사일로 깔때기 (종이·PET)", 11, SUB, "middle", 700))
    o.append(tx(sx(115), sy(-156), "출구 Ø12", 10, SUB, "middle", 600))
    # SG90 게이트
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="#2b6cb8" stroke="#18407f" stroke-width="1.2"/>'
             % (sx(126), ceil + 10 * SS, 22 * SS, 11 * SS))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#f2f2ee" stroke="#a9a496" stroke-width="1"/>'
             % (sx(108), ceil + 10 * SS, 18 * SS, 2.6 * SS))
    o.append(tx(sx(137), ceil + 8 * SS, "SG90 패들", 10, "#18407f", "middle", 700))
    # 관제실 단면
    o.append('<path d="M %.1f %.1f L %.1f %.1f" stroke="#9fb2c2" stroke-width="1.6" '
             'stroke-dasharray="8 6"/>' % (sx(196), ceil, sx(196), floor))
    o.append(tx(sx(196) + 14, sy(-60), "관제실", 12, SUB, "start", 700))

    # 치수
    o.append(arrow_h(sx(0), sx(190), floor + 30, "190 (깊이)"))
    o.append(arrow_v(ceil, floor, sx(-22), "120"))
    o.append(arrow_h(sx(115), sx(190), ceil - 16, "75"))
    o.append(tx(sx(0), floor + 66, "차가 북향 후진으로 들어와 범퍼로 스위치를 누르면 도킹 완료. 그때 게이트가 열린다.",
                11.5, FAB, weight=600))

    # 주석
    o.append(tx(1080, 726, "· 차고 안쪽 140×190×120. 입구 양쪽 벽 끝을 45°로 20mm 벌려 깔때기로 만든다.", 12.5, FAB))
    o.append(tx(1080, 750, "· 바닥 안내 레일 8mm가 차를 가운데로 모은다. 뒤벽 범퍼판 뒤에 택트 스위치.", 12.5, FAB))
    o.append(tx(1080, 774, "· 사일로 출구 Ø12 = 도킹 시 차 호퍼 입구 위(뒤 범퍼에서 75).", 12.5, FAB))
    o.append(tx(1080, 798, "· 관제실 앞벽에 LCD·OLED·RGB·부저, 지붕에 네오픽셀 링.", 12.5, FAB))
    o.append(tx(60, 1092, "· 평면은 위에서 본 모습, 단면은 차고를 남북으로 잘라 동쪽에서 본 모습이다. 점선은 지붕 위(사일로·링)이다.",
                13, FAB, weight=600))
    return svg_doc(AV, AH, "".join(o), "제설기지 조립도")


def main():
    for name, fn in (("real_base_wiring.svg", build_wiring),
                     ("real_base_assembly.svg", build_assembly)):
        out = fn()
        p = os.path.join(IMG_DIR, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(out)
        with open(p, encoding="utf-8") as f:
            doc = xml.dom.minidom.parseString(f.read())
        print("wrote %s  (%d bytes, %d elements)" % (p, len(out), len(doc.getElementsByTagName("*"))))


if __name__ == "__main__":
    main()
