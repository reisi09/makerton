"""제설차 전용 실물 부품. 1단위 = 1mm.

    motor_28byj48()      28BYJ-48 스텝모터. 핀 "W1".."W5"(파랑·분홍·노랑·주황·빨강)
    uln2003_board()      ULN2003 드라이버. 핀 "IN1".."IN4","+","-","M1".."M5"(모터 소켓)
    hcsr04()             초음파. 핀 "VCC","Trig","Echo","Gnd"
    foam_wheel()         Ø65 우드락 바퀴 + 고무줄 타이어
    bottle_cap_skid()    병뚜껑 미끄럼 받침
    hopper()             50×50 호퍼(바닥 살포구 + SG90 패들)
    chassis_plate()      100×150 우드락 하판
    battery_holder_3aa() AA 3개 홀더(보조배터리 대안)
"""
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core import (  # noqa: E402
    Part, rect, circle, line, path, text, mount_hole, pin_header,
    PCB_GREEN, PCB_BLUE, PCB_BLACK, PCB_RED, GOLD, SILVER, HEADER, SILK, WIRE,
)

MOTOR_SILVER = "#c2c8cf"
MOTOR_SILVER_D = "#98a0a8"
GEAR_BLUE = "#2b5fa8"
GEAR_BLUE_L = "#3d76c4"
FOAM_TAN = "#e9dfc6"
FOAM_TAN_D = "#cfc2a2"
RUBBER = "#26282c"
PAPER = "#f4f6f8"
CASE_BLACK = "#26292e"


# ── 28BYJ-48 스텝모터 ────────────────────────────────────────────────
def motor_28byj48():
    """Ø28 은색 몸통 + 파란 감속 기어 커버. 귀 구멍 간격 35mm, D축 Ø5.

    핀 "W1".."W5"는 리드선이 흰 5핀 커넥터로 나가는 점(파랑·분홍·노랑·주황·빨강 순).
    """
    w, h = 42.0, 42.0
    cx, cy = 19.0, 21.0
    o = []
    # 귀(위·아래) — 구멍 간격 35
    for sy in (-1, 1):
        ey = cy + sy * 17.5
        o.append(rect(cx - 4.6, ey - 3.4, 9.2, 6.8, fill=MOTOR_SILVER, stroke=MOTOR_SILVER_D, sw=0.3, rx=1.2))
        mount_hole(cx, ey, 1.5)
    # 몸통(은색 캔)
    o.append(circle(cx, cy, 14.0, fill=MOTOR_SILVER, stroke="#7f878f", sw=0.4))
    o.append(circle(cx, cy, 13.2, fill="#cdd3d9", stroke="none"))
    o.append(path("M %.2f %.2f A 13.2 13.2 0 0 1 %.2f %.2f" % (cx - 9.3, cy - 9.3, cx + 9.3, cy - 9.3),
                  stroke="#e4e8ec", sw=1.1))
    # 파란 기어 커버(축 쪽)
    o.append(circle(cx, cy, 11.6, fill=GEAR_BLUE, stroke="#1b4478", sw=0.35))
    o.append(circle(cx, cy, 9.6, fill=GEAR_BLUE_L, stroke="none"))
    o.append(text(cx, cy + 7.2, "28BYJ-48", 1.5, "#d7e3f2", "middle", 700))
    # D축
    o.append(circle(cx, cy, 2.6, fill="#dfe4e9", stroke="#8f969f", sw=0.25))
    o.append(rect(cx - 2.6, cy - 0.9, 5.2, 1.8, fill="#f2f5f8", stroke="none"))
    # 리드선 5가닥 → 오른쪽 흰 5핀 커넥터
    cols = [("W1", WIRE["blue"]), ("W2", WIRE["pink"]), ("W3", WIRE["yellow"]),
            ("W4", WIRE["orange"]), ("W5", WIRE["red"])]
    pins = {}
    y_top = cy - 6.0
    for i, (nm, col) in enumerate(cols):
        y_out = y_top + i * 3.0
        o.append(path("M %.2f %.2f C %.2f %.2f, %.2f %.2f, %.2f %.2f" % (
            30.4, cy - 2.0, 33.0, y_out - 1.0, 35.0, y_out, 37.6, y_out),
            stroke=col, sw=1.2))
        pins[nm] = (w, y_out)
    o.append(rect(37.2, y_top - 1.9, 4.2, 15.8, fill="#eceff2", stroke="#b7bcc2", sw=0.28, rx=0.6))
    for i in range(5):
        o.append(rect(38.0, y_top - 1.2 + i * 3.0, 2.6, 2.3, fill="#f7f9fa", stroke="#c6cbd1", sw=0.12, rx=0.35))
    return Part("28byj48", w, h, "".join(o), pins)


# ── ULN2003 드라이버 보드 ────────────────────────────────────────────
def uln2003_board():
    """ULN2003APG 보드 35×32. 입력 헤더(IN1~IN4, +, -)는 오른쪽, 흰 5핀 모터 소켓은 왼쪽.

    핀: "IN1".."IN4","+","-"는 오른쪽 끝, "M1".."M5"는 왼쪽 소켓 안.
    """
    w, h = 35.0, 32.0
    o = []
    o.append(rect(0, 0, w, h, fill=PCB_BLUE, stroke="#123f73", sw=0.35, rx=1.2))
    o.append(rect(1.2, 1.2, w - 2.4, h - 2.4, fill="none", stroke="#2f74c8", sw=0.2, rx=0.9))
    o.append(text(w / 2 + 1.0, 3.1, "ULN2003", 1.6, "#dbe7f6", "middle", 800))
    # DIP16 (ULN2003APG)
    bx, by = 9.0, 12.2
    o.append(rect(bx, by, 19.3, 6.6, fill=PCB_BLACK, stroke="#0b0d10", sw=0.28, rx=0.4))
    o.append(circle(bx + 1.9, by + 1.9, 0.5, fill="#4a5560"))
    o.append(text(bx + 11.4, by + 4.3, "ULN2003APG", 1.25, "#b9c3cd", "middle", 700))
    for i in range(8):
        px = bx + 1.05 + i * 2.54
        for py, dy in ((by - 1.2, 1.2), (by + 6.6, 1.2)):
            o.append(rect(px - 0.55, py - dy / 2, 1.1, dy + 0.2, fill=SILVER, stroke="#8b9098", sw=0.1))
            o.append(circle(px, py - dy / 2 if py < by else py + dy / 2, 0.5, fill=GOLD))
    # LED A~D
    for i, lab in enumerate("ABCD"):
        lx = 9.2 + i * 4.6
        o.append(circle(lx, 24.2, 1.5, fill="#e04a4a", stroke="#8f2222", sw=0.2))
        o.append(circle(lx - 0.4, 24.0, 0.45, fill="#ffd7d7"))
        o.append(text(lx, 28.1, lab, 1.15, "#dbe7f6", "middle", 700))
    # 흰 5핀 모터 소켓(왼쪽)
    o.append(rect(0.2, 8.2, 4.6, 14.6, fill="#eceff2", stroke="#b7bcc2", sw=0.25, rx=0.5))
    pins = {}
    for i in range(5):
        y = 10.0 + i * 2.54
        o.append(rect(1.0, y - 1.25, 2.6, 2.5, fill="#f7f9fa", stroke="#c6cbd1", sw=0.12, rx=0.35))
        o.append(circle(2.3, y, 0.55, fill="#9aa1aa"))
        pins["M%d" % (i + 1)] = (1.0, y)
    # 입력 헤더(오른쪽)
    for i, nm in enumerate(("IN1", "IN2", "IN3", "IN4", "+", "-")):
        y = 4.5 + i * 2.54 if i < 4 else (15.0 if i == 4 else 17.6)
        o.append(rect(w - 2.4, y - 1.15, 2.4, 2.3, fill=HEADER, stroke="#000", sw=0.1, rx=0.3))
        o.append(rect(w - 1.9, y - 0.5, 1.0, 1.0, fill=GOLD))
        pins[nm] = (w, y)
        o.append(text(w - 3.4, y + 0.55, {"+": "+", "-": "-"}.get(nm, nm[-1]), 1.4,
                      "#ffe0e0" if nm == "+" else ("#d8dcdf" if nm == "-" else "#dbe7f6"), "end", 700))
    o.append(text(w - 2.0, 21.4, "IN1~4", 1.15, "#a9c6e8", "end", 700))
    return Part("uln2003", w, h, "".join(o), pins)


# ── HC-SR04 초음파 ──────────────────────────────────────────────────
def hcsr04():
    """HC-SR04. 45×20 파란 PCB, 은색 트랜스듀서 T·R. 핀 "VCC","Trig","Echo","Gnd"는 아래 가장자리."""
    w, h = 45.0, 20.0
    o = []
    o.append(rect(0, 0, w, h, fill=PCB_BLUE, stroke="#123f73", sw=0.35, rx=1.0))
    o.append(rect(1.0, 1.0, w - 2.0, h - 2.0, fill="none", stroke="#2f74c8", sw=0.18, rx=0.8))
    for cx, lab in ((9.0, "T"), (36.0, "R")):
        o.append(circle(cx, 8.4, 8.0, fill=SILVER, stroke="#7f878f", sw=0.35))
        o.append(circle(cx, 8.4, 6.6, fill="#d8dde3", stroke="#a6adb5", sw=0.2))
        o.append(circle(cx, 8.4, 5.2, fill="#9aa1a9", stroke="none"))
        o.append(circle(cx, 8.4, 4.2, fill="#7f878f", stroke="none"))
        o.append(text(cx, 15.9, lab, 1.5, "#dbe7f6", "middle", 800))
    o.append(rect(20.4, 5.4, 4.4, 2.6, fill="#c8ccd2", stroke="#8b9098", sw=0.2, rx=0.3))
    o.append(text(22.6, 12.4, "HC-SR04", 1.5, "#dbe7f6", "middle", 700))
    pins = {}
    for i, nm in enumerate(("VCC", "Trig", "Echo", "Gnd")):
        x = 20.5 + i * 2.54
        o.append(rect(x - 1.1, h - 3.0, 2.2, 3.0, fill=HEADER, stroke="#000", sw=0.1, rx=0.25))
        o.append(rect(x - 0.5, h - 2.6, 1.0, 1.0, fill=GOLD))
        o.append(text(x, h - 4.4, nm if i < 3 else "G", 1.05, "#dbe7f6", "middle", 700))
        pins[nm] = (x, h)
    return Part("hcsr04", w, h, "".join(o), pins)


# ── 우드락 바퀴 Ø65 + 고무줄 ─────────────────────────────────────────
def foam_wheel():
    """Ø65 우드락 3겹 원판 + 고무줄 타이어 + D축 구멍(3×5). 축 방향에서 본 그림."""
    w = h = 65.0
    c = 32.5
    o = []
    # 고무줄 타이어
    o.append(circle(c, c, 32.5, fill=RUBBER, stroke="#111", sw=0.3))
    o.append(circle(c, c, 29.6, fill=FOAM_TAN, stroke=FOAM_TAN_D, sw=0.3))
    # 우드락 3겹 층
    o.append(circle(c, c, 27.2, fill="#efe7d1", stroke=FOAM_TAN_D, sw=0.25))
    o.append(circle(c, c, 21.0, fill=FOAM_TAN, stroke=FOAM_TAN_D, sw=0.25))
    o.append(circle(c, c, 14.4, fill="#efe7d1", stroke=FOAM_TAN_D, sw=0.2))
    # 접착 자국
    for a in range(0, 360, 60):
        ra = math.radians(a)
        o.append(line(c + 16 * math.cos(ra), c + 16 * math.sin(ra),
                      c + 24 * math.cos(ra), c + 24 * math.sin(ra), stroke="#ddd2b6", sw=0.5))
    # 허브 + D축 구멍
    o.append(circle(c, c, 6.6, fill="#d9cba6", stroke="#b6a882", sw=0.3))
    o.append(rect(c - 2.5, c - 1.5, 5.0, 3.0, fill="#ffffff", stroke="#8f969f", sw=0.2, rx=0.2))
    return Part("wheel", w, h, "".join(o), {"hub": (c, c)})


# ── 병뚜껑 받침 ─────────────────────────────────────────────────────
def bottle_cap_skid(side=False):
    """병뚜껑 미끄럼 받침. side=False면 위에서(Ø30), side=True면 옆에서(30×18)."""
    if side:
        w, h = 30.0, 18.0
        o = [path("M 1.0 %.2f L 3.4 3.2 L 26.6 3.2 L 29.0 %.2f Z" % (h - 0.6, h - 0.6),
                  fill="#2f6fd6", stroke="#1d4b96", sw=0.35),
             rect(2.2, 1.4, 25.6, 2.2, fill="#3f82e0", stroke="#1d4b96", sw=0.2, rx=0.6)]
        for i in range(9):
            o.append(line(3.4 + i * 2.9, 5.2, 3.0 + i * 2.9, h - 1.6, stroke="#2a63be", sw=0.35))
        o.append(rect(1.0, h - 1.4, 28.0, 1.4, fill="#1f2a36", stroke="none", rx=0.4))
        return Part("skid_side", w, h, "".join(o), {"top": (w / 2, 1.4)})
    w = h = 30.0
    c = 15.0
    o = [circle(c, c, 15.0, fill="#2f6fd6", stroke="#1d4b96", sw=0.35),
         circle(c, c, 13.2, fill="#3672d8", stroke="none")]
    for a in range(0, 360, 24):
        ra = math.radians(a)
        o.append(line(c + 13.4 * math.cos(ra), c + 13.4 * math.sin(ra),
                      c + 15.0 * math.cos(ra), c + 15.0 * math.sin(ra), stroke="#1d4b96", sw=0.5))
    o.append(circle(c, c, 9.0, fill="#2a63be", stroke="#1d4b96", sw=0.25))
    o.append(circle(c, c, 3.0, fill="#25549f", stroke="none"))
    return Part("skid", w, h, "".join(o), {})


# ── 호퍼 50×50 ──────────────────────────────────────────────────────
def hopper():
    """호퍼 50×50(높이 55). 위에서 본 그림. 바닥 살포구 Ø12는 앞쪽(아래) 가운데,
    그 위에 SG90 패들이 게이트로 붙는다. 핀 "spout"은 살포구 중심."""
    w = h = 50.0
    o = []
    # 종이 벽 바깥/안
    o.append(rect(0, 0, w, h, fill=PAPER, stroke="#c2c8d0", sw=0.35, rx=2.0))
    o.append(rect(2.6, 2.6, w - 5.2, h - 5.2, fill="#ffffff", stroke="#d3d8de", sw=0.3, rx=1.6))
    # 깔때기 경사(안쪽으로 갈수록 좁아짐)
    o.append(path("M 4.0 4.0 L %.2f 4.0 L %.2f %.2f L 9.0 %.2f Z" % (w - 4.0, w - 9.0, h - 9.0, h - 9.0),
                  fill="#eef2f5", stroke="#c8ced5", sw=0.25))
    # 살포구
    o.append(circle(25.0, 44.0, 6.0, fill="#3a3f45", stroke="#22262b", sw=0.35))
    o.append(circle(25.0, 44.0, 4.5, fill="#15181c", stroke="none"))
    # SG90 패들(게이트)
    o.append(rect(17.4, 30.0, 15.2, 8.0, fill="#2b6cb8", stroke="#1e4f8a", sw=0.3, rx=1.2))
    o.append(text(25.0, 35.4, "SG90", 1.5, "#e9f0f8", "middle", 800))
    o.append(rect(22.6, 37.8, 4.8, 10.6, fill="#eceff2", stroke="#b9c0c8", sw=0.25, rx=1.4))
    o.append(circle(25.0, 40.0, 1.5, fill="#b9c0c8"))
    o.append(text(25.0, 14.0, "호퍼", 2.4, "#8b9299", "middle", 800))
    o.append(text(25.0, 19.0, "50×50 · 높이 55", 1.7, "#a6adb4", "middle", 700))
    return Part("hopper", w, h, "".join(o), {"spout": (25.0, 44.0), "paddle": (25.0, 40.0)})


# ── 우드락 하판 ─────────────────────────────────────────────────────
def chassis_plate():
    """우드락 2겹 하판 100×150."""
    w, h = 100.0, 150.0
    o = []
    o.append(rect(0, 0, w, h, fill="#f6f4ee", stroke="#cbc7b8", sw=0.45, rx=3.0))
    o.append(rect(1.6, 1.6, w - 3.2, h - 3.2, fill="none", stroke="#e2ddcf", sw=0.35, rx=2.4))
    o.append(rect(3.4, 3.4, w - 6.8, h - 6.8, fill="none", stroke="#efece1", sw=0.8, rx=1.8))
    return Part("plate", w, h, "".join(o), {})


# ── AA 3개 홀더(대안 전원) ───────────────────────────────────────────
def battery_holder_3aa():
    """AA 3개 홀더 48×55. 핀 "BAT+"(빨강), "BAT-"(검정)은 리드선 끝."""
    w, h = 48.0, 55.0
    o = []
    o.append(rect(0, 0, w, h, fill=CASE_BLACK, stroke="#0f1114", sw=0.4, rx=2.0))
    o.append(rect(2.0, 2.0, w - 4.0, h - 4.0, fill="#31353b", stroke="none", rx=1.6))
    for i in range(3):
        cx = 8.6 + i * 15.0
        o.append(rect(cx - 6.6, 6.0, 13.2, 43.0, fill="#3e434a", stroke="#1b1e22", sw=0.3, rx=6.0))
        o.append(rect(cx - 5.0, 8.6, 10.0, 37.4, fill="#4a5058", stroke="none", rx=5.0))
        o.append(rect(cx - 3.0, 12.0, 6.0, 30.6, fill="#22262b", stroke="none", rx=2.0))
        o.append(rect(cx - 1.4, 4.4, 2.8, 2.4, fill=GOLD, stroke="#8f7434", sw=0.15, rx=0.4))
        o.append(rect(cx - 1.4, h - 6.8, 2.8, 2.4, fill=SILVER, stroke="#8b9098", sw=0.15, rx=0.4))
    o.append(text(w / 2, 51.0, "AA ×3", 1.5, "#aeb6bf", "middle", 700))
    o.append(path("M 3.0 3.0 C -3.0 6.0, -2.0 14.0, -6.0 18.0", stroke=WIRE["red"], sw=1.2))
    o.append(path("M %.2f %.2f C %.2f %.2f, %.2f %.2f, %.2f %.2f" % (
        w - 3.0, h - 3.0, w + 3.0, h - 6.0, w + 2.0, h - 12.0, w + 8.0, h - 15.0),
        stroke=WIRE["black"], sw=1.2))
    pins = {"BAT+": (0.0, 18.0), "BAT-": (w + 8.0, h - 15.0)}
    return Part("aa3", w, h, "".join(o), pins)
