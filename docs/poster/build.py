#!/usr/bin/env python3
"""포스터 그림 세 장(system.svg·board.svg·wiring.svg)과 모형 사진을 만들고 poster.png·poster.pdf로 굽는다.

    python3 docs/poster/build.py            # 그림 + 사진 + PNG·PDF
    python3 docs/poster/build.py --no-render  # 그림과 사진만

핀·차체·보드 치수는 pico/car/config.py와 server/board.json에서, 전체 청소 순서·시간은 server/route.py에서 읽는다.
글은 poster.html에 직접 쓴다. 판 크기와 배치는 Canva 양식(2560×1440px)을 따른다.
"""
import html
import json
import math
import os
import runpy
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = runpy.run_path(os.path.join(ROOT, "pico", "car", "config.py"))
with open(os.path.join(ROOT, "server", "board.json"), encoding="utf-8") as f:
    BOARD = json.load(f)
sys.path.insert(0, os.path.join(ROOT, "server"))
import route  # noqa: E402  펌웨어 경로 계획으로 순서를 고른다(차는 건드리지 않는다)

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FONT = "'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', sans-serif"

# Canva 양식의 색
NAVY, INK, DEEP, MID, LINE, BRIGHT = "#023047", "#13293d", "#004e7a", "#006494", "#247ba0", "#1b98e0"
PALE, ORANGE, WHITE = "#e8f1f2", "#fb8500", "#ffffff"
RED, BLACK, OPT = "#d62828", "#1d1d1d", "#8a9aa5"
IN_COL = ("#1f6fd1", "#2a9d3f", "#d99a00", "#c2185b")       # IN1~IN4 선 색

# Pico 2 W 물리 핀(위에서 본 모습, USB 위). 왼쪽 1~20, 오른쪽 40~21
PICO_LEFT = ["GP0", "GP1", "GND", "GP2", "GP3", "GP4", "GP5", "GND", "GP6", "GP7", "GP8", "GP9", "GND",
             "GP10", "GP11", "GP12", "GP13", "GND", "GP14", "GP15"]
PICO_RIGHT = ["VBUS", "VSYS", "GND", "3V3E", "3V3", "VREF", "GP28", "AGND", "GP27", "GP26", "RUN", "GP22",
              "GND", "GP21", "GP20", "GP19", "GP18", "GND", "GP17", "GP16"]       # 40, 39, ... 21
PHYS = {}
for i, n in enumerate(PICO_LEFT):
    PHYS.setdefault(n, i + 1)
for i, n in enumerate(PICO_RIGHT):
    PHYS.setdefault(n, 40 - i)


def gp(n):
    return PHYS["GP%d" % n]


# ── SVG 도우미 ───────────────────────────────────────────────────────
def t(x, y, s, size=14, fill=INK, w=500, anchor="start", extra=""):
    return '<text x="%.1f" y="%.1f" font-size="%s" font-weight="%s" fill="%s" text-anchor="%s"%s>%s</text>' % (
        x, y, size, w, fill, anchor, extra, html.escape(str(s)))


def rect(x, y, w, h, fill="none", stroke="none", sw=0, rx=0, dash=""):
    d = ' stroke-dasharray="%s"' % dash if dash else ""
    return '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%s" fill="%s" stroke="%s" stroke-width="%s"%s/>' % (
        x, y, w, h, rx, fill, stroke, sw, d)


def poly(pts, stroke, sw=2, dash="", extra=""):
    d = ' stroke-dasharray="%s"' % dash if dash else ""
    p = " ".join("%.1f,%.1f" % xy for xy in pts)
    return '<polyline points="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round"%s %s/>' % (
        p, stroke, sw, d, extra)


def dot(x, y, r=4, fill=INK, stroke="none", sw=0):
    return '<circle cx="%.1f" cy="%.1f" r="%s" fill="%s" stroke="%s" stroke-width="%s"/>' % (x, y, r, fill, stroke, sw)


def svg(w, h, body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" font-family="%s">'
            '<defs>'
            '<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
            '<path d="M0 0L10 5L0 10z" fill="%s"/></marker>'
            '<marker id="ao" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" markerHeight="4" orient="auto">'
            '<path d="M0 0L10 5L0 10z" fill="%s"/></marker>'
            '<marker id="ad" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
            '<path d="M0 0L10 5L0 10z" fill="%s"/></marker>'
            '</defs><rect width="%d" height="%d" fill="#fff"/>%s</svg>\n') % (
        w, h, w, h, FONT, LINE, ORANGE, MID, w, h, "".join(body))


def arrow(pts, both=False, color=LINE, sw=3):
    ends = ' marker-end="url(#ar)"' + (' marker-start="url(#ar)"' if both else "")
    return poly(pts, color, sw, extra=ends)


# ── ① 시스템 구성도 ──────────────────────────────────────────────────
def system_svg():
    W, H, NW, NH = 885, 532, 224, 140
    cols, rows = (9, 331, 653), (21, 281)
    nodes = {
        "app": (0, 0, "웹 화면 /app", ["사진 → Claude 직접 호출", "눈 갈래 최적 경로 표시", "전체 청소 · 정지 버튼", "수동 조작 패드"], False),
        "srv": (1, 0, "맥 서버 (Python)", [":8000 · /app · /monitor", "최적 경로: 순서 24가지 비교", "펌웨어 경로 계획 그대로", "HEIC 변환 · Claude 호출"], True),
        "ai": (2, 0, "Claude API", ["claude-opus-5-5", "사진 → 눈 상자 · 눈 갈래", "화면 표시만 (차는 그대로)", "키는 저장소에 두지 않음"], False),
        "mon": (0, 1, "모니터 /monitor", ["1920×1080 흑백 화면", "지도 · 경로 · 차 위치", "1초마다 갱신", "조작 버튼 없음"], False),
        "car": (1, 1, "제설차 Pico 2 W", ["MicroPython 1.29", "28BYJ-48 ×2 + ULN2003 ×2", "기지 → 갈래 밀기 → 후진", "전원: 맥 USB"], True),
        "man": (2, 1, "수동 조작 (Web Serial)", ["맥의 Chrome · Edge", "USB로 Pico에 직접 연결", "화살표 버튼 · 키", "떼면 바로 정지"], False),
    }
    o = []
    for c, r, title, lines, key in nodes.values():
        x, y = cols[c], rows[r]
        o.append(rect(x, y, NW, NH, PALE, BRIGHT if key else INK, 6 if key else 4))
        o.append(t(x + 12, y + 35, title, 19, INK, 700))
        for i, s in enumerate(lines):
            o.append(t(x + 12, y + 63 + i * 19, s, 14, MID, 500))

    L1, R1 = cols[0] + NW, cols[1]          # 1열 오른쪽 끝, 2열 왼쪽 끝
    L2, R2 = cols[1] + NW, cols[2]
    gap = lambda a, b: (a + b) / 2
    # 웹 ⇄ 서버
    o.append(arrow([(L1 + 4, 58), (R1 - 4, 58)]))
    o.append(t(gap(L1, R1), 30, "사진", 12, MID, 700, "middle"))
    o.append(t(gap(L1, R1), 46, "전체 청소·정지", 12, MID, 700, "middle"))
    o.append(arrow([(R1 - 4, 112), (L1 + 4, 112)]))
    o.append(t(gap(L1, R1), 86, "눈 상자·경로", 12, LINE, 600, "middle"))
    o.append(t(gap(L1, R1), 102, "차 위치", 12, LINE, 600, "middle"))
    # 서버 ⇄ Claude
    o.append(arrow([(L2 + 4, 58), (R2 - 4, 58)]))
    o.append(t(gap(L2, R2), 46, "사진", 12, MID, 700, "middle"))
    o.append(arrow([(R2 - 4, 112), (L2 + 4, 112)]))
    o.append(t(gap(L2, R2), 132, "눈 상자·갈래", 12, LINE, 600, "middle"))
    o.append(t(gap(L2, R2), 148, "(JSON)", 12, LINE, 600, "middle"))
    # 서버 → 모니터(꺾은선)
    o.append(arrow([(R1, 150), (290, 150), (290, rows[1] + 40), (L1 + 4, rows[1] + 40)]))
    o.append(t(282, 205, "같은 핫스팟", 12, MID, 700, "end"))
    o.append(t(282, 221, "1초 갱신", 12, LINE, 600, "end"))
    # 서버 ⇄ 제설차
    cx = cols[1] + NW / 2
    o.append(arrow([(cx, rows[0] + NH + 4), (cx, rows[1] - 4)], both=True))
    o.append(t(cx - 10, 205, "Wi-Fi UDP", 14, MID, 700, "end"))
    o.append(t(cx - 10, 222, "9200 ⇄ 9201", 12, LINE, 600, "end"))
    o.append(t(cx + 10, 205, "계획·정지 ↓  위치 0.5초 ↑", 12, MID, 700))
    o.append(t(cx + 10, 222, "아이폰 핫스팟 2.4GHz", 12, LINE, 600))
    o.append(t(cx + 10, 238, "(호환성 최대화)", 12, LINE, 600))
    # 수동 조작 → 제설차
    y = rows[1] + 70
    o.append(arrow([(R2 - 4, y), (L2 + 4, y)]))
    o.append(t(gap(L2, R2), y - 12, "USB", 12, MID, 700, "middle"))
    o.append(t(gap(L2, R2), y + 22, "Web Serial", 12, LINE, 600, "middle"))
    # 아래 설명
    order = route.plan(route.ALL)
    o.append(rect(9, 445, 868, 78, PALE, BRIGHT, 2))
    notes = [
        "출동 버튼은 ‘전체 청소’ 하나. 누르면 서버가 갈래 순서 %d가지를 펌웨어 경로 계획으로 비교해 가장 빠른 계획을 차에 보낸다." % order["tried"],
        "네 갈래 %s 약 %d초(계산값). Claude가 알려 준 눈 갈래의 최적 순서·경로는 화면 표시만 하고 차는 그대로다." % ("→".join(order["order"]), order["seconds"]),
        "키를 넣은 기기는 Claude를 직접 부르고, 없으면 서버를 거친다. 정지가 언제나 우선, 신호가 %d초 끊기면 일시 정지." % (CFG["LINK_TIMEOUT_MS"] // 1000),
    ]
    for i, s in enumerate(notes):
        o.append(t(22, 470 + i * 21, s, 14, INK, 500))
    return svg(W, H, o)


# ── ② 보드 실측과 출동 경로 ─────────────────────────────────────────
def board_svg():
    W, H = 665, 532
    S, OX, OY = 0.45, 14, 52
    X = lambda x: OX + x * S
    Y = lambda y: OY + y * S
    bw, bh = BOARD["BOARD_MM"]
    cx, cy = BOARD["CENTER_X"], BOARD["CENTER_Y"]
    road = BOARD["ROAD_MM"]
    o = [t(OX, 30, "보드 %d × %d mm · 도로 폭 %d" % (bw, bh, road), 15, INK, 700)]
    o.append(rect(X(0), Y(0), bw * S, bh * S, "#f4f7f8", INK, 2, 6))
    grey, edge = "#d9e0e4", "#aab6bd"
    for x, y, w, h in ((20, 20, 128, 150), (160, 20, 128, 150), (20, 190, 128, 158), (160, 190, 128, 158),
                       (745, 670, 158, 204)):
        o.append(rect(X(x), Y(y), w * S, h * S, grey, edge, 1, 3))
    o.append('<path d="M%.1f %.1fH%.1fV%.1fH%.1fV%.1fH%.1fV%.1fH%.1fV%.1fH%.1fV%.1fH%.1fZ" fill="%s" stroke="%s" stroke-width="1"/>' % (
        X(16), Y(716), X(112), Y(770), X(260), Y(716), X(356), Y(894), X(260), Y(840), X(112), Y(894), X(16), grey, edge))
    o.append(rect(X(300), Y(50), 165 * S, 330 * S, "#bfe3c4", "#7cbf87", 1, 18))       # 공원
    o.append(rect(X(16), Y(560), 340 * S, 146 * S, "#f8dc7a", "#d9a514", 1, 3))          # 노란 코트
    o.append(rect(X(383), Y(560), 125 * S, 192 * S, "#8fcf98", "#5aa766", 1, 3))         # 축구장
    o.append(t(X(186), Y(640), "노란 코트", 11, "#7a5a00", 700, "middle"))
    o.append(t(X(382), Y(220), "공원", 11, "#2f6b3a", 700, "middle"))
    # 도로
    rx0, rx1 = cx - road / 2, cx + road / 2
    ry0, ry1 = cy - road / 2, cy + road / 2
    o.append(rect(X(0), Y(ry0), bw * S, road * S, "#2b2f33"))
    o.append(rect(X(rx0), Y(0), road * S, bh * S, "#2b2f33"))
    o.append(rect(X(rx0 - 3), Y(ry0 + 3), (road + 6) * S, (road - 6) * S, "none", "#f2c230", 1.5))
    for a, (lx, ly) in {"N": (cx, 18), "S": (cx, bh - 18), "W": (18, cy), "E": (bw - 18, cy)}.items():
        o.append(dot(X(lx), Y(ly), 10, WHITE, INK, 1.5))
        o.append(t(X(lx), Y(ly) + 4.5, a, 13, INK, 800, "middle"))
    # 제설 기지(북동쪽 건물, 서쪽 면에 출입구)
    bx0, bx1, by0, by1 = 690, 909, 20, 344
    o.append(rect(X(bx0), Y(by0), (bx1 - bx0) * S, (by1 - by0) * S, "#ffe8cc", ORANGE, 2, 4))
    o.append(poly([(X(bx0), Y(by1 - 290)), (X(bx0), Y(by1))], "#ffe8cc", 4))
    o.append(poly([(X(bx0), Y(by1 - 290)), (X(bx0), Y(by1))], ORANGE, 2, "5 4"))
    o.append(t(X(800), Y(70), "제설 기지", 14, "#9a4d00", 800, "middle"))
    o.append(t(X(800), Y(108), "출입구 서쪽", 10.5, "#9a4d00", 600, "middle"))
    o.append(t(X(800), Y(140), "폭 약 290", 10.5, "#9a4d00", 600, "middle"))
    # 출동 경로(바퀴 축). 기지 → 서쪽 → 남쪽 → 중심, 갈래마다 끝까지 갔다가 후진
    bxy, out = BOARD["BASE_XY"], BOARD["ARM_OUT_MM"]
    ends = {"N": (cx, cy - out["N"]), "E": (cx + out["E"], cy), "S": (cx, cy + out["S"]), "W": (cx - out["W"], cy)}
    plan = route.plan(route.ALL)
    o.append(poly([(X(bxy[0]), Y(bxy[1])), (X(cx), Y(bxy[1])), (X(cx), Y(cy))], ORANGE, 3, "7 5", 'marker-end="url(#ao)"'))
    for i, a in enumerate(plan["order"]):
        ex, ey = ends[a]
        o.append(poly([(X(cx), Y(cy)), (X(ex), Y(ey))], ORANGE, 3, extra='marker-end="url(#ao)"'))
        dx, dy = (ex - cx), (ey - cy)
        k = 1 + 34 / math.hypot(dx, dy)
        nx, ny = X(cx + dx * k), Y(cy + dy * k)
        o.append(dot(nx, ny, 9, ORANGE))
        o.append(t(nx, ny + 4.5, i + 1, 12, WHITE, 800, "middle"))
    o.append(dot(X(cx), Y(cy), 3.5, WHITE))
    # 차고 안의 차(앞이 서쪽). 자세 점 = 바퀴 축 가운데
    f, r, half = CFG["CAR_FRONT_MM"], CFG["CAR_REAR_MM"], 76
    o.append(rect(X(bxy[0] - f), Y(bxy[1] - half), (f + r) * S, 2 * half * S, "#fff4e6", "#c2410c", 1.5, 3))
    o.append(rect(X(bxy[0] - f), Y(bxy[1] - half), 8 * S, 2 * half * S, "#c2410c"))
    o.append(dot(X(bxy[0]), Y(bxy[1]), 3, "#c2410c"))
    o.append(t(X(cx) + 8, Y(cy) + 16, "중심 (%d, %d)" % (cx, cy), 10.5, WHITE, 700))

    # 오른쪽: 차체(위에서 본 모습, 날이 위)
    K, CXc, FY = 0.62, 548, 74
    L, Wd = CFG["CAR_FRONT_MM"] + CFG["CAR_REAR_MM"], 152
    ax = FY + CFG["CAR_FRONT_MM"] * K
    x0, x1, y1 = CXc - Wd / 2 * K, CXc + Wd / 2 * K, FY + L * K
    o.append(t(450, 30, "차체 (2026-11-01 실측, mm)", 15, INK, 700))
    o.append(rect(x0, FY, Wd * K, L * K, PALE, INK, 2, 4))
    o.append(rect(x0 - 2, FY - 6, Wd * K + 4, 8, ORANGE, "none", 0, 2))
    tr, wd = CFG["TRACK_MM"] * K / 2, CFG["WHEEL_D_MM"] * K
    for sx in (-1, 1):
        o.append(rect(CXc + sx * tr - 4, ax - wd / 2, 8, wd, INK, "none", 0, 2))
    o.append(poly([(CXc - tr, ax), (CXc + tr, ax)], MID, 1.5, "3 3"))
    o.append(dot(CXc, ax, 4, ORANGE))
    o.append(t(CXc, ax + 26, "윤거 %d" % CFG["TRACK_MM"], 11, MID, 700, "middle"))
    o.append(t(CXc, ax + 41, "회전 중심 = 바퀴 축", 10, MID, 600, "middle"))
    o.append(t(CXc, FY - 12, "날 폭 152", 11, "#9a4d00", 800, "middle"))

    def vdim(x, ya, yb, label, anchor):
        o.append(poly([(x, ya + 2), (x, yb - 2)], MID, 1.2, extra='marker-start="url(#ad)" marker-end="url(#ad)"'))
        o.append(poly([(x - 4, ya), (x + 4, ya)], MID, 1.2))
        o.append(poly([(x - 4, yb), (x + 4, yb)], MID, 1.2))
        o.append(t(x + (-6 if anchor == "end" else 6), (ya + yb) / 2 + 4, label, 11, MID, 700, anchor))
    vdim(x0 - 12, FY, ax, CFG["CAR_FRONT_MM"], "end")
    vdim(x0 - 12, ax, y1, CFG["CAR_REAR_MM"], "end")
    vdim(x1 + 12, FY, y1, L, "start")

    um = math.pi * CFG["WHEEL_D_MM"] / CFG["STEPS_PER_REV"]          # 스텝당 mm
    spd = lambda us: um / (us * 1e-6)
    specs = [
        ("바퀴 지름 %d · 병뚜껑+고무줄" % CFG["WHEEL_D_MM"], INK),
        ("하프스텝 %d스텝 = 바퀴 1바퀴" % CFG["STEPS_PER_REV"], INK),
        ("출발 %.1fms/스텝 · 초당 %dmm" % (CFG["START_US"] / 1000, round(spd(CFG["START_US"]))), INK),
        ("주행 %.1fms/스텝 · 초당 %dmm" % (CFG["STEP_US"] / 1000, round(spd(CFG["STEP_US"]))), INK),
        ("가감속 %d스텝 (약 %dmm)" % (CFG["RAMP_STEPS"], round(CFG["RAMP_STEPS"] * um)), INK),
        ("전체 청소 %s" % "→".join(plan["order"]), ORANGE),
        ("약 %d초 · 가장 긴 순서 %d초" % (plan["seconds"], plan["worst_seconds"]), INK),
        ("(%d가지 비교, 계산값)" % plan["tried"], MID),
        ("사진 속 눈 갈래의 최적 순서는", MID),
        ("지도에 표시만 (차는 그대로)", MID),
    ]
    for i, (s, c) in enumerate(specs):
        o.append(t(452, 262 + i * 22, s, 13, c, 700 if c == ORANGE else 600))
    o.append(t(OX, 490, "주황 실선 = 바퀴 축이 지나는 출동 경로 · 숫자 = 전체 청소 순서 · 점선 = 기지 → 교차로", 12, INK, 600))
    o.append(t(OX, 510, "차고 안 바퀴 축 (%d, %d) → 서쪽 %d → 남쪽 %d → 교차로 중심. 갈래 끝까지 밀고 같은 길로 후진." % (
        bxy[0], bxy[1], bxy[0] - cx, cy - bxy[1]), 12, MID, 600))
    return svg(W, H, o)


# ── ③ 제설차 배선도 ─────────────────────────────────────────────────
def wiring_svg():
    W, H = 826, 532
    PX, PW, TOP, STEP = 330, 150, 70, 19
    Y0 = TOP + 24

    def pin(p):
        return (PX if p <= 20 else PX + PW, Y0 + ((p - 1) if p <= 20 else (40 - p)) * STEP)

    left = [gp(n) for n in CFG["PIN_LEFT"]]
    right = [gp(n) for n in CFG["PIN_RIGHT"]]
    servo, button = gp(CFG["PIN_SERVO"]), gp(CFG["PIN_BUTTON"])
    trig, echo = gp(CFG["PIN_SONAR_TRIG"]), gp(CFG["PIN_SONAR_ECHO"])
    led = [gp(CFG["PIN_LED_R"]), gp(CFG["PIN_LED_G"]), gp(CFG["PIN_LED_B"])]
    buzzer = gp(CFG["PIN_BUZZER"])
    vbus, gnd = PHYS["VBUS"], 38
    btn_gnd = button - 1 if PICO_LEFT[button - 2] == "GND" else 18          # 버튼 옆 GND 핀
    mounted = set(left + right + [vbus, gnd])
    optional = {servo, button, trig, echo, buzzer, btn_gnd, *led}
    o = []

    # 전원 레일: VBUS(5V) → ULN2003 +, GND → ULN2003 −
    rp, rm = 36, 50
    o.append(poly([pin(vbus), (500, pin(vbus)[1]), (500, rp), (26, rp), (26, 350), (170, 350), (170, 330)], RED, 2.5))
    o.append(poly([pin(gnd), (512, pin(gnd)[1]), (512, rm), (38, rm), (38, 340), (200, 340), (200, 330)], BLACK, 2.5))
    o.append(t(60, rp - 6, "+5V (VBUS · 핀 40)", 11, RED, 700))
    o.append(t(60, rm + 14, "GND (핀 38)", 11, BLACK, 700))

    # ULN2003 두 장 + 28BYJ-48 두 개(실선 = 장착)
    def uln(pins, name, sub, power_top):
        ys = [pin(p)[1] for p in pins]
        y0, y1 = ys[0] - 16, ys[-1] + 16 + (0 if power_top else 11)
        if power_top:
            y0 -= 11
        o.append(rect(140, y0, 122, y1 - y0, PALE, INK, 2, 4))
        o.append(t(148, ys[0] + 4 + (8 if power_top else 0), "ULN2003", 12, INK, 800))
        o.append(t(148, ys[0] + 21 + (8 if power_top else 0), name, 12, MID, 700))
        if sub:
            o.append(t(148, ys[0] + 37 + (8 if power_top else 0), sub, 10.5, MID, 600))
        for k, (p, y) in enumerate(zip(pins, ys)):
            o.append(poly([(262, y), (PX, y)], IN_COL[k], 3))
            o.append(t(256, y + 4, "IN%d" % (k + 1), 10.5, INK, 700, "end"))
            o.append(dot(262, y, 3, IN_COL[k]))
        py = y0 if power_top else y1
        sx_ = (170, 200)
        if power_top:
            o.append(poly([(170, rp), (170, py)], RED, 2.5))
            o.append(poly([(200, rm), (200, py)], BLACK, 2.5))
            o.append(dot(170, rp, 3.5, RED))
            o.append(dot(200, rm, 3.5, BLACK))
        for x_, s in zip(sx_, "+−"):
            o.append(dot(x_, py, 3, WHITE, INK, 1.2))
            o.append(t(x_ + 7, py + (12 if power_top else -5), s, 11, INK, 800, "middle"))
        my = (y0 + y1) / 2
        for k, c in enumerate(("#1f6fd1", "#e64980", "#f2c230", "#fb8500", "#d62828")):
            yy = my - 6 + k * 3
            o.append(poly([(118, yy), (140, yy)], c, 1.6))
        o.append(dot(88, my, 30, "#c9ccd1", "#6c757d", 2))
        o.append(dot(88, my, 9, "#868e96"))
        o.append(t(88, my - 13, "28BYJ-48", 9, INK, 700, "middle"))
        o.append(t(88, my + 22, "모터", 9, INK, 700, "middle"))

    uln(right, "오른쪽 바퀴", "방향 반전(설정)" if CFG["RIGHT_INVERT"] else "", True)
    uln(left, "왼쪽 바퀴", "방향 반전(설정)" if CFG["LEFT_INVERT"] else "", False)

    # 선택 부품(점선, 신호선만)
    def opt_box(x, y, w, h, title, sub):
        o.append(rect(x, y, w, h, "#f5f7f8", OPT, 1.5, 4, "5 4"))
        o.append(t(x + 8, y + 17, title, 11.5, "#4a5a64", 700))
        if sub:
            o.append(t(x + 8, y + 32, sub, 10, OPT, 600))

    def opt_wire(p, x_end, label):
        x, y = pin(p)
        o.append(poly([(x, y), (x_end, y)], OPT, 2, "6 4"))
        o.append(dot(x_end, y, 2.5, OPT))
        if label:
            ax_ = x_end + (6 if x_end > x else -6)
            o.append(t(ax_, y + 4, label, 10, "#4a5a64", 700, "start" if x_end > x else "end"))

    # 왼쪽 아래: 버튼(GP↔GND), 서보
    yb0, yb1 = pin(btn_gnd)[1] - 13, pin(button)[1] + 10
    opt_box(140, yb0, 122, yb1 - yb0, "택트 버튼", "선택 · GND로 누름")
    opt_wire(button, 262, "")
    opt_wire(btn_gnd, 262, "")
    o.append(t(256, pin(button)[1] + 4, "GP%d" % CFG["PIN_BUTTON"], 10, "#4a5a64", 700, "end"))
    o.append(t(256, pin(btn_gnd)[1] + 4, "GND", 10, "#4a5a64", 700, "end"))
    ys = pin(servo)[1]
    opt_box(140, ys - 6, 122, 46, "SG90 서보", "선택 · 살포통")
    opt_wire(servo, 262, "")
    o.append(t(256, ys + 4, "신호", 10, "#4a5a64", 700, "end"))

    # 오른쪽 아래: 부저, 3색 LED, 초음파(ECHO 분압)
    BX = 590
    yz = pin(buzzer)[1]
    opt_box(BX, yz - 11, 180, 20, "능동 부저 · 선택", "")
    opt_wire(buzzer, BX, "")
    ly = [pin(p)[1] for p in led]
    opt_box(BX, min(ly) - 8, 180, max(ly) - min(ly) + 16, "3색 LED · 선택", "")
    for p, s in zip(led, "RGB"):
        opt_wire(p, BX, "")
        o.append(t(BX + 172, pin(p)[1] + 4, s, 10, "#4a5a64", 800, "end"))
    yt, ye = pin(trig)[1], pin(echo)[1]
    opt_box(BX, min(yt, ye) - 12, 180, abs(yt - ye) + 46, "HC-SR04 초음파 · 선택", "")
    opt_wire(trig, BX, "")
    opt_wire(echo, BX, "")
    o.append(t(BX + 172, yt + 4, "TRIG", 10, "#4a5a64", 800, "end"))
    o.append(t(BX + 172, ye + 4, "ECHO", 10, "#4a5a64", 800, "end"))
    o.append(rect(518, ye - 5, 30, 10, WHITE, OPT, 1.5, 2))
    o.append(t(533, ye - 9, "1kΩ·2kΩ 분압", 9.5, "#4a5a64", 700, "middle"))
    o.append(t(BX + 8, max(yt, ye) + 28, "5V ECHO → 3.3V 핀 보호", 10, OPT, 600))

    # Pico 2 W
    o.append(rect(PX + PW / 2 - 18, TOP - 12, 36, 16, "#adb5bd", "#495057", 1.5, 3))
    o.append(rect(PX, TOP, PW, 20 * STEP + 30, "#1f7a3d", "#0b3d1c", 2, 8))
    for p in range(1, 41):
        name = PICO_LEFT[p - 1] if p <= 20 else PICO_RIGHT[40 - p]
        x, y = pin(p)
        used = p in mounted
        col = "#f2c230" if used else ("#cfe8d6" if p in optional else "#5f9e72")
        o.append(dot(x, y, 4.2, col, "#0b3d1c", 1))
        label = ("%d %s" % (p, name)) if p <= 20 else ("%s %d" % (name, p))
        fill = WHITE if used else ("#d8efe0" if p in optional else "#8cc29e")
        o.append(t(x + (9 if p <= 20 else -9), y + 3.8, label, 10, fill, 800 if used or p in optional else 500,
                   "start" if p <= 20 else "end"))
    o.append(t(PX + PW / 2, TOP + 20 * STEP + 50, "Raspberry Pi Pico 2 W", 14, INK, 800, "middle"))
    o.append(t(PX + PW / 2, TOP + 20 * STEP + 66, "MicroPython 1.29", 11, MID, 600, "middle"))

    # 맥 USB(전원·코드·수동 조작). 레일 위를 건너는 선
    ux = PX + PW / 2
    cable = [(ux, TOP - 12), (ux, 14), (556, 14)]
    o.append(poly(cable, WHITE, 9))
    o.append(poly(cable, "#6c757d", 4))
    o.append(rect(556, 3, 160, 22, NAVY, "none", 0, 4))
    o.append(t(636, 18, "맥북 USB (전원·코드)", 11.5, WHITE, 700, "middle"))

    # 오른쪽 위 설명
    NX = 545
    blocks = [
        ("전원 · 연결", [("맥북 USB → Pico 마이크로 USB", MID), ("5V 전원 · 코드 업로드 · 수동 조작", MID),
                       ("VBUS(40) → ULN2003 +, GND(38) → −", MID)]),
        ("모터 (장착)", [("왼쪽  IN1~IN4 = " + "·".join("GP%d" % n for n in CFG["PIN_LEFT"]), MID),
                      ("오른쪽 IN1~IN4 = " + "·".join("GP%d" % n for n in CFG["PIN_RIGHT"]), MID),
                      ("오른쪽은 펌웨어에서 방향 반전", MID),
                      ("2026-11-01 수리로 범퍼를 반대 끝에 달아", MID), ("좌우 핀을 바꿨다", MID)]),
    ]
    y = 72
    for title, lines in blocks:
        o.append(t(NX, y, title, 13.5, INK, 800))
        y += 18
        for s, c in lines:
            o.append(t(NX, y, s, 11.5, c, 600))
            y += 16
        y += 10
    # 선 색 범례
    for k, c in enumerate(IN_COL):
        x = NX + k * 52
        o.append(poly([(x, y), (x + 18, y)], c, 3))
        o.append(t(x + 22, y + 4, "IN%d" % (k + 1), 10, INK, 700))
    y += 18
    o.append(poly([(NX, y), (NX + 18, y)], RED, 2.5))
    o.append(t(NX + 22, y + 4, "+5V", 10, INK, 700))
    o.append(poly([(NX + 64, y), (NX + 82, y)], BLACK, 2.5))
    o.append(t(NX + 86, y + 4, "GND", 10, INK, 700))
    o.append(poly([(NX + 124, y), (NX + 142, y)], OPT, 2, "6 4"))
    o.append(t(NX + 146, y + 4, "선택(미장착)", 10, INK, 700))

    o.append(t(8, 512, "실선 = 장착(지금은 모터만)", 11, MID, 600))
    o.append(t(8, 527, "점선 = 핀만 정한 선택 부품(신호선만 표시)", 11, MID, 600))
    o.append(t(818, 527, "핀 기준: pico/car/config.py", 11, MID, 600, "end"))
    return svg(W, H, o)


def photo():
    """docs/img/board_measured.png 오른쪽(위에서 본 평면 사진, 0.8px/mm)만 잘라 낸다. macOS sips 사용."""
    src = os.path.join(ROOT, "docs", "img", "board_measured.png")
    dst = os.path.join(HERE, "model_photo.jpg")
    subprocess.run(["sips", "-c", "728", "740", "--cropOffset", "110", "880", "-s", "format", "jpeg",
                    "-s", "formatOptions", "88", src, "--out", dst], check=True, capture_output=True)


def render():
    url = "file://" + os.path.join(HERE, "poster.html")
    with tempfile.TemporaryDirectory() as prof:
        base = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                "--user-data-dir=" + prof, "--virtual-time-budget=4000", "--window-size=2560,1440"]
        subprocess.run(base + ["--screenshot=" + os.path.join(HERE, "poster.png"), url], check=True, capture_output=True)
        subprocess.run(base + ["--no-pdf-header-footer", "--print-to-pdf=" + os.path.join(HERE, "poster.pdf"), url],
                       check=True, capture_output=True)


if __name__ == "__main__":
    for name, make in (("system.svg", system_svg), ("board.svg", board_svg), ("wiring.svg", wiring_svg)):
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
            f.write(make())
    photo()
    full = route.plan(route.ALL)
    quote = "%s 약 %d초" % ("→".join(full["order"]), full["seconds"])
    print("전체 청소:", quote, "(%d가지 중, 가장 긴 순서 %d초)" % (full["tried"], full["worst_seconds"]))
    with open(os.path.join(HERE, "poster.html"), encoding="utf-8") as f:
        if quote not in f.read():
            print("경고: poster.html에 '%s'가 없다. 글의 순서·시간을 고칠 것" % quote)
    if "--no-render" not in sys.argv:
        render()
    print("완료:", HERE)
