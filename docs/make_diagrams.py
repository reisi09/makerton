"""makerton 도면 7장을 만든다. 기준은 CONTRACT.md 3~8절(핀·상수·좌표).

실행: python3 docs/make_diagrams.py   →   docs/img/*.svg
색은 계약 5절 팔레트를 강조색으로 쓴다. 배선 관례(5V 빨강, GND 검정)는 그대로 둔다.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from svgkit import C, L, P, Rc, T, box, dim_h, dim_v, esc, net, pico, wire  # noqa: E402

IMG = os.path.join(HERE, "img")

# ── 계약 5절 팔레트(어두운 → 밝은) ──
NAVY = "#012a4a"
YALE = "#013a63"
YALE2 = "#01497c"
YALE3 = "#014f86"
CER = "#2a6f97"
CER2 = "#2c7da0"
AFB = "#468faf"
STEEL = "#61a5c2"
SKY = "#89c2d9"
LIGHT = "#a9d6e5"
PAPER = "#eaf3f9"
RED = "#b91c1c"          # 5V 관례
BLACK = "#111111"        # GND 관례

# ── 계약 7·8절 기구·배치 상수(mm) ──
BOARD = 900
ROAD_LO, ROAD_HI = 375, 525
MID = 450
PILLARS = {"N": (535, 220), "E": (680, 535), "S": (365, 680), "W": (220, 365)}
WET_PT = (700, 540)
LIGHT_PT = (200, 530)
WHEEL_D = 65
TRACK = 105
BODY_W, BODY_L = 130, 110
OUT_MM = 360
SPRAY_FROM, SPRAY_TO = 110, 340
OBST_CM = 8

DEFS = """<defs>
<marker id="arrE" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#01497c"/></marker>
<marker id="arrS" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10 0 L0 5 L10 10 z" fill="#01497c"/></marker>
<marker id="flow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#012a4a"/></marker>
<marker id="flowB" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#2a6f97"/></marker>
<marker id="flowL" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#a9d6e5"/></marker>
<pattern id="waves" width="40" height="18" patternUnits="userSpaceOnUse"><path d="M0 9 q10 -7 20 0 t20 0" fill="none" stroke="#468faf" stroke-width="2"/></pattern>
<pattern id="hatch" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="12" fill="#a9d6e5"/><rect x="6" width="6" height="12" fill="#ffffff"/></pattern>
</defs>
"""


def head(vb, w, h, title):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s" width="%d" height="%d" '
            "font-family=\"'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', sans-serif\">\n"
            '<title>%s</title>\n%s' % (vb, w, h, esc(title), DEFS))


def panel(x, y, w, h, title, sub, fill, accent=NAVY, title_size=28, sub_size=19):
    o = [Rc(x, y, w, h, fill=fill, stroke=accent, sw=2.5, rx=14)]
    o.append(T(x + w / 2, y + 40, title, title_size, weight=800, fill=NAVY))
    for i, line in enumerate(sub):
        o.append(T(x + w / 2, y + 78 + i * 29, line, sub_size, weight=600, fill="#1f3b52"))
    return "".join(o)


# ────────────────────────────────────────────────────────────── 1. system.svg
def svg_system():
    o = [head("0 0 1560 900", 1560, 900, "시스템 구성")]
    o.append(T(24, 46, "고색고 ICE-ZERO 자동 제설 모형 — 시스템 구성", 34, "start", 800))
    o.append(T(24, 80, "LLM 없음. 판단은 학습 모델과 코드 규칙이 한다.", 20, "start", 600, CER))

    o.append(panel(20, 110, 430, 250, "맥북 — 모델·서버", [
        "ICE-ZERO 지면온도 예보(고색고 재학습)",
        "갈래 예측 동결확률 · 상대 우선순위",
        "서버 0.0.0.0:8000 (조작 대시보드 /)",
        "자동 출동 판단(예산·순서)",
    ], "#dceaf4"))
    o.append(panel(20, 490, 430, 200, "모니터 — 웹 /monitor", [
        "1920×1080 키오스크, 스크롤 없음",
        "1초 갱신 · 조작 버튼 없음",
        "같은 Wi-Fi: http://<맥 IP>:8000/monitor",
    ], "#cfe3f0", title_size=26))

    o.append(panel(610, 110, 340, 250, "기지 Pico #1", [
        "관제실 · USB 시리얼(맥북 전원)",
        "DHT11×4 · 수위(W) · 조도",
        "OLED · LCD · LED · 부저 · 링",
        "도킹 감지 · 자동 보충",
    ], "#dceaf4", title_size=26))

    o.append(panel(610, 490, 340, 236, "제설차 Pico #2", [
        "Wi-Fi UDP 9200 ⇄ 9201",
        "28BYJ-48 ×2 + ULN2003 ×2",
        "기지 출발 → 살포 → 후진 도킹",
        "비상 버튼 · SR-04 정지",
    ], "#cfe3f0", title_size=26))

    o.append(panel(1110, 110, 430, 250, "사거리 보드 — 도로", [
        "검은 종이 도로 폭 약 150",
        "A3 광장 297×420 · 임의 도로 4갈래",
        "DHT11 기둥 4 · 젖음·조도(W)",
    ], "#e3eef6", title_size=26))
    o.append(panel(1110, 490, 430, 236, "제설기지 (S 끝 남쪽)", [
        "외곽 320×230 · 차고 140×190×120",
        "사일로·SG90 보충 게이트",
        "도킹 스위치 · 지붕 경광등",
    ], "#e3eef6", title_size=26))

    # 연결 1: 맥북 ↔ 센서 Pico (USB 시리얼)
    o.append(L(450, 210, 610, 210, YALE2, 4, extra='marker-start="url(#flowB)" marker-end="url(#flowB)"'))
    o.append(T(530, 196, "USB 시리얼", 18, weight=800, fill=YALE2))
    o.append(T(530, 244, "@@TEL·@@SHOW", 15, weight=700, fill=CER))

    # 연결 2: 센서 Pico → 센서부
    o.append(L(950, 210, 1110, 210, CER, 4, extra='marker-end="url(#flowB)"'))
    o.append(T(1030, 196, "3V3·ADC", 18, weight=800, fill=CER))
    o.append(T(1030, 244, "신호선", 15, weight=700, fill=CER))

    # 연결 3: 맥북 → 모니터(웹)
    o.append(L(235, 360, 235, 490, YALE2, 4, extra='marker-end="url(#flowB)"'))
    o.append(T(250, 412, "웹 /monitor", 17, "start", 800, YALE2))
    o.append(T(250, 438, "같은 Wi-Fi", 15, "start", 700, CER))

    # 연결 4: 맥북 ↔ 제설차 Pico (Wi-Fi UDP)
    o.append(P("M 450 320 L 545 320 L 545 600 L 610 600", stroke=YALE2, sw=4))
    o.append('<path d="M 610 600 l -14 -7 l 0 14 z" fill="%s"/>' % YALE2)
    o.append('<path d="M 545 320 l -7 14 l 14 0 z" fill="%s"/>' % YALE2)
    o.append(T(537, 430, "Wi-Fi UDP", 17, "end", 800, YALE2))
    o.append(T(537, 455, "9200 ⇄ 9201", 15, "end", 700, CER))

    # 연결 5: 제설차 → 도로부
    o.append(L(950, 600, 1110, 600, CER, 4, extra='marker-end="url(#flowB)"'))
    o.append(T(1030, 586, "모터·서보", 18, weight=800, fill=CER))
    o.append(T(1030, 634, "차 위치", 15, weight=700, fill=CER))

    o.append(Rc(20, 756, 1520, 76, fill="#f2f8fc", stroke=STEEL, sw=1.5, rx=10))
    o.append(T(40, 790, "auto 켜짐 + recommend + 차 idle + 실행 중 계획 없음 → 서버가 plan을 보낸다.", 18, "start", 700, NAVY))
    o.append(T(40, 816, "기지 출발 → 갈래 살포 → 후진 도킹 → 자동 보충. 비상 정지 셋(대시보드·버튼·초음파)은 항상 동작한다.", 17, "start", 700, NAVY))
    o.append(T(1520, 872, "CONTRACT.md 1·5~8절", 16, "end", 600, AFB))
    o.append('</svg>')
    return "".join(o)


# ───────────────────────────────────────────────────── 2. sensor_wiring.svg
def ptag(x, y, label, color):
    """모듈 전원 표시(선 없이 상자 안에 붙인다). VCC·GND가 공통임을 보여 준다."""
    w = 18 + 7.4 * len(label)
    return Rc(x, y - 11, w, 22, fill=color, rx=4) + T(x + w / 2, y + 5, label, 12, weight=800, fill="#fff")


def svg_sensor_wiring():
    used = {1: "#2c7da0", 2: "#2c7da0", 4: "#2a6f97", 5: "#2a6f97", 6: "#2a6f97", 7: "#2a6f97",
            14: "#b91c1c", 15: "#15803d", 16: "#1d4ed8", 17: "#6d28d9", 21: "#014f86",
            31: "#0e7490", 32: "#a16207", 36: RED, 38: BLACK, 40: RED}
    o = [head("-70 -50 1580 1240", 1580, 1240, "센서 Pico #1 배선도")]
    o.append(T(-50, -18, "센서 Pico #1 배선 — DHT11×4 · 수위 · 조도 · OLED · 3색 LED · 부저 · 링", 30, "start", 800))
    ps, pp = pico(660, 120, used, "Pico 2 W (#1, USB)")
    o.append(ps)

    # ── 왼쪽: OLED ──
    s, op = box(110, 90, 280, 150, "OLED 0.91\" (I2C0)", ["SDA", "SCL"])
    o.append(s)
    o.append(ptag(126, 212, "3V3 · GND", YALE2))
    o.append(wire(op["SDA"], pp[1], CER2, None, via=590))
    o.append(wire(op["SCL"], pp[2], CER2, None, via=560))
    o.append(T(250, 262, "주소 0x3C · LCD 0x27 공유", 14, weight=700, fill=CER))

    # ── 왼쪽: DHT11 ×4 ──
    s, dp = box(110, 300, 280, 250, "DHT11 ×4 (갈래)", ["N", "E", "S", "W"])
    o.append(s)
    o.append(ptag(126, 532, "3V3 · GND", YALE2))
    for name, pin, via in (("N", 4, 610), ("E", 5, 580), ("S", 6, 550), ("W", 7, 520)):
        o.append(wire(dp[name], pp[pin], CER, None, via=via))
    o.append(T(250, 596, "모듈 풀업 사용 · 0~50°C만", 14, weight=700, fill=CER))

    # ── 왼쪽: 3색 LED · 부저 ──
    s, lp = box(110, 620, 280, 150, "3색 LED (로컬 경고)", ["R", "G", "B"])
    o.append(s)
    o.append(ptag(126, 742, "GND", BLACK))
    for name, pin, via, col in (("R", 14, 600, RED), ("G", 15, 570, "#15803d"), ("B", 16, 540, "#1d4ed8")):
        o.append(wire(lp[name], pp[pin], col, None, via=via))

    s, bp = box(110, 820, 280, 120, "능동 부저", ["+"])
    o.append(s)
    o.append(ptag(126, 912, "GND", BLACK))
    o.append(wire(bp["+"], pp[17], "#6d28d9", None, via=600))

    # ── 오른쪽: 조도 · 수위 · 링 ──
    s, gip = box(1080, 230, 330, 150, "조도 모듈 (W 그늘)", ["AO"], side="left")
    o.append(s)
    o.append(ptag(1108, 352, "3V3 · GND", YALE2))
    o.append(wire(pp[32], gip["AO"], "#a16207", None, via=950))

    s, wp = box(1080, 430, 330, 150, "수위감지 (젖음, W)", ["AO"], side="left")
    o.append(s)
    o.append(ptag(1108, 552, "3V3 · GND", YALE2))
    o.append(wire(pp[31], wp["AO"], "#0e7490", None, via=925))

    s, rp = box(1080, 630, 330, 150, "WS2812 링 (갈래 상태)", ["DIN"], side="left")
    o.append(s)
    o.append(ptag(1108, 752, "VBUS 5V · GND", RED))
    o.append(wire(pp[21], rp["DIN"], YALE3, None, via=950))

    # ── 기지 부가 장치 ──
    s, dp = box(110, 960, 280, 150, "기지: 도킹 스위치 · 보충 서보", ["도킹", "보충"])
    o.append(s)
    o.append(ptag(126, 1088, "GND", BLACK))
    o.append(wire(dp["도킹"], pp[19], "#0e7490", None, via=470))
    o.append(wire(dp["보충"], pp[20], "#6d28d9", None, via=440))

    # ── Pico 전원 ──
    o.append(net(pp[40], "VBUS 5V", RED, "right"))
    o.append(net(pp[36], "3V3", RED, "right"))
    o.append(net(pp[38], "GND", BLACK, "right"))

    o.append(T(110, 1140, "모든 모듈 VCC는 3V3, GND는 공통이다. 링만 VBUS 5V를 쓰고 DIN에 330Ω을 넣는다.", 17, "start", 700, YALE))
    o.append(T(110, 1168, "DHT11 모듈은 풀업이 붙어 있어 데이터선만 이으면 된다. 수위·조도 AO는 3V3 기준 0~65535.", 17, "start", 600, CER))
    o.append('</svg>')
    return "".join(o)


# ─────────────────────────────────────────────────────── 3. car_wiring.svg
def svg_car_wiring():
    # 키는 물리 핀 번호다(계약 7절 GPIO → 핀: GP14=19, GP15=20, GP16=21, GP17=22,
    # GP18=24, GP19=25, GP20=26, GP21=27).
    used = {4: "#2a6f97", 5: "#2a6f97", 6: "#2a6f97", 7: "#2a6f97",
            9: "#01497c", 10: "#01497c", 11: "#01497c", 12: "#01497c",
            19: "#0e7490", 20: "#6d28d9", 21: "#a16207", 22: "#2c7da0",
            24: "#b91c1c", 25: "#15803d", 26: "#1d4ed8", 27: "#7c3aed",
            36: RED, 38: BLACK, 40: RED}
    o = [head("0 -50 1580 1120", 1580, 1120, "제설차 Pico #2 배선도")]
    o.append(T(20, -14, "제설차 Pico #2 배선 — 스텝모터 ×2 · 서보 · 초음파 · 버튼 · LED · 부저", 30, "start", 800))
    ps, pp = pico(660, 140, used, "Pico 2 W (#2, Wi-Fi)")
    o.append(ps)

    # ── 왼쪽: 모터 두 개(마주 보게) + ULN2003 ──
    for idx, (my, top, fill) in enumerate(((200, "ULN2003 #1 (왼쪽)", CER), (340, "ULN2003 #2 (오른쪽)", YALE2))):
        o.append(Rc(30, my, 110, 129, fill="#e3eef6", stroke=YALE, sw=2, rx=8))
        o.append(C(85, my + 50, 26, fill=STEEL, stroke=YALE, sw=2))
        o.append(T(85, my + 57, ("L", "R")[idx], 20, weight=800, fill=NAVY))
        o.append(T(85, my + 106, "28BYJ-48", 12, weight=700))
        s, u = box(190, my, 300, 129, top, ["IN1", "IN2", "IN3", "IN4"])
        o.append(s)
        o.append(L(140, my + 30, 190, my + 30, fill, 5))
        o.append(T(165, my + 20, "5선", 11, weight=800, fill=fill))
        pins = (4, 5, 6, 7) if idx == 0 else (9, 10, 11, 12)
        for k, name in enumerate(("IN1", "IN2", "IN3", "IN4")):
            o.append(wire(u[name], pp[pins[k]], fill, None, via=610 - k * 26))

    # ── 왼쪽: 버튼 · 서보 ──
    s, bt = box(190, 510, 300, 110, "택트 스위치(정지·재개)", ["SIG"])
    o.append(s)
    o.append(ptag(206, 600, "GND", BLACK))
    o.append(wire(bt["SIG"], pp[19], "#0e7490", None, via=620))
    o.append(T(340, 604, "내부 풀업 · 누르면 GND", 13, weight=700, fill=CER))

    s, sv = box(190, 660, 300, 150, "SG90 살포 서보", ["PWM"])
    o.append(s)
    o.append(ptag(206, 782, "VBUS 5V · GND", RED))
    o.append(wire(sv["PWM"], pp[20], "#6d28d9", None, via=610))

    # ── 오른쪽: 전원 · LED · 부저 · 초음파 ──
    o.append(Rc(1080, 140, 340, 130, fill="#f4f8fb", stroke=YALE, sw=2, rx=8))
    o.append(T(1096, 172, "보조배터리 5V 2A", 17, "start", 800, NAVY))
    o.append(T(1096, 200, "USB → Pico VBUS", 14, "start", 700, YALE2))
    o.append(ptag(1096, 236, "VBUS 5V · GND", RED))

    s, lp = box(1080, 320, 340, 200, "3색 LED (상태)", ["R", "G", "B"], side="left")
    o.append(s)
    o.append(ptag(1108, 486, "GND", BLACK))
    o.append(wire(lp["R"], pp[24], RED, None, via=930))
    o.append(wire(lp["G"], pp[25], "#15803d", None, via=955))
    o.append(wire(lp["B"], pp[26], "#1d4ed8", None, via=980))

    s, bp = box(1080, 570, 340, 130, "능동 부저", ["+"], side="left")
    o.append(s)
    o.append(ptag(1108, 666, "GND", BLACK))
    o.append(wire(bp["+"], pp[27], "#7c3aed", None, via=930))

    s, us = box(1080, 750, 340, 200, "SR-04 초음파", ["TRIG", "ECHO"], side="left")
    o.append(s)
    o.append(ptag(1108, 906, "VBUS 5V · GND", RED))
    o.append(wire(us["TRIG"], pp[21], "#a16207", None, via=930))
    o.append(wire(us["ECHO"], pp[22], CER2, None, via=960))
    o.append(T(1096, 972, "ECHO → 1kΩ·2kΩ 분압", 14, "start", 700, YALE3))

    o.append(net(pp[40], "VBUS 5V", RED, "right"))
    o.append(net(pp[36], "3V3", RED, "right"))
    o.append(net(pp[38], "GND", BLACK, "right"))

    o.append(T(20, 1012, "ULN2003 VCC는 VBUS, GND는 Pico와 공통. stop·버튼·장애물이면 ULN 입력을 모두 LOW로 내려 모터를 세운다.",
               17, "start", 700, YALE))
    o.append(T(20, 1044, "SR-04 ECHO는 5V이므로 1kΩ·2kΩ 분압으로 3.3V에 맞춘다. 스텝모터 두 개를 마주 보게 달아 오른쪽 방향을 반전한다.",
               17, "start", 600, CER))
    o.append('</svg>')
    return "".join(o)


# ─────────────────────────────────────────────────────── 4. car_layout.svg
def svg_car_layout():
    o = [head("0 0 1560 920", 1560, 920, "제설차 평면·측면")]
    o.append(T(24, 44, "제설차 배치 — 평면(위에서) 과 측면", 30, "start", 800))
    o.append(T(24, 76, "단위 mm. 화면 3px = 1mm. 바퀴 지름 65, 바퀴 중심 간격 105, 차체 약 130×110.", 18, "start", 600, CER))

    s = 3.0
    bx, by = 180.0, 190.0
    bw, bl = BODY_W * s, BODY_L * s                     # 390 × 330
    cx, cy = bx + bw / 2, by + bl / 2                    # 375, 355
    o.append(T(bx, 122, "(a) 평면 — 앞이 북(위)", 22, "start", 800))
    o.append(Rc(bx, by, bw, bl, fill="#eef6fb", stroke=NAVY, sw=3, rx=10))

    # 바퀴(차체 밑, 차체 밖으로 조금 나온다)
    wr = WHEEL_D * s / 2                                  # 97.5
    for wx in (cx - TRACK * s / 2, cx + TRACK * s / 2):
        o.append(Rc(wx - 19, cy - wr, 38, 2 * wr, fill=NAVY, stroke=NAVY, rx=8))
    o.append(T(cx - TRACK * s / 2, cy + wr + 26, "L", 18, weight=800, fill=NAVY))
    o.append(T(cx + TRACK * s / 2, cy + wr + 26, "R", 18, weight=800, fill=NAVY))

    # 28BYJ-48 두 개를 마주 보게
    for mx in (bx + 62, bx + bw - 62):
        o.append(Rc(mx - 30, cy - 34, 60, 68, fill=SKY, stroke=YALE, sw=2, rx=6))
        o.append(T(mx, cy + 5, "M", 16, weight=800, fill=NAVY))

    # 호퍼 + 서보 + 살포구
    o.append(Rc(cx - 65, by + 44, 130, 84, fill=LIGHT, stroke=YALE3, sw=2.5, rx=6))
    o.append(T(cx, by + 74, "호퍼", 16, weight=800, fill=NAVY))
    o.append(T(cx, by + 96, "모래", 13, weight=700, fill=YALE3))
    o.append(Rc(cx - 30, by + 134, 60, 26, fill=CER, stroke=NAVY, sw=2, rx=4))
    o.append(T(cx, by + 152, "서보", 13, weight=800, fill="#fff"))
    o.append(P("M %d %d L %d %d" % (cx, by + 160, cx, by + 188), stroke=YALE3, sw=5,
               extra='marker-end="url(#flowB)"'))
    o.append(T(cx + 12, by + 188, "살포구", 13, "start", 800, YALE3))

    # 초음파 · 배터리 · 캐스터
    o.append(Rc(cx - 22, by + 6, 44, 22, fill=STEEL, stroke=YALE, sw=2, rx=4))
    o.append(T(cx + 34, by + 22, "SR-04", 14, "start", 800, YALE))
    o.append(Rc(cx - 70, by + 212, 140, 90, fill="#cfe3f0", stroke=YALE2, sw=2, rx=6))
    o.append(T(cx, by + 248, "보조배터리", 15, weight=800, fill=NAVY))
    o.append(T(cx, by + 272, "5V 2A", 13, weight=700, fill=YALE2))
    for gx in (cx - 50, cx + 50):
        o.append(C(gx, by + 322, 10, fill="#fff", stroke=YALE2, sw=2))
    o.append(T(cx, by + 352, "캐스터(뒤) · 슬라이더(앞)", 13, weight=700, fill=YALE2))

    # 치수
    o.append(dim_h(bx, bx + bw, by - 30, "130", ext_from=by, size=17))
    o.append(dim_v(by, by + bl, bx - 40, "110", ext_from=bx, size=17))
    o.append(dim_h(cx - TRACK * s / 2, cx + TRACK * s / 2, by + bl + 74, "105 (바퀴 중심)", ext_from=by + bl, size=17))
    o.append(dim_v(cy - wr, cy + wr, bx + bw + 46, "Ø65", ext_from=bx + bw, size=17))

    # ── 측면 ──
    gy = 720.0
    o.append(T(760, 122, "(b) 측면 — 앞이 오른쪽", 22, "start", 800))
    o.append(L(720, gy, 1500, gy, NAVY, 3))
    for gx in range(730, 1500, 26):
        o.append(L(gx, gy, gx - 10, gy + 12, STEEL, 2))
    o.append(T(1500, gy + 34, "바닥(우드락)", 15, "end", 700, YALE))

    wcx, wcy = 850.0, gy - wr
    o.append(C(wcx, wcy, wr, fill=NAVY, stroke=NAVY, sw=2))
    o.append(C(wcx, wcy, 26, fill="#e3eef6", stroke=STEEL, sw=2))
    o.append(T(wcx, wcy + 6, "Ø65", 14, weight=800, fill=NAVY))
    o.append(dim_v(wcy - wr, wcy + wr, wcx - 130, "65", ext_from=wcx - wr, size=17))

    deck = gy - 215
    o.append(Rc(900, deck, 330, 16, fill=STEEL, stroke=YALE, sw=2))
    o.append(T(1065, deck + 44, "데크", 13, weight=700, fill=YALE))
    o.append(Rc(910, deck - 76, 100, 76, fill="#cfe3f0", stroke=YALE2, sw=2, rx=5))
    o.append(T(960, deck - 44, "배터리", 14, weight=800, fill=NAVY))
    o.append(T(960, deck - 24, "5V 2A", 12, weight=700, fill=YALE2))
    o.append(Rc(1020, deck - 62, 76, 62, fill="#e3eef6", stroke=YALE2, sw=2, rx=5))
    o.append(T(1058, deck - 32, "Pico", 13, weight=800, fill=NAVY))
    o.append(T(1058, deck - 14, "ULN×2", 12, weight=700, fill=YALE2))
    o.append(Rc(1100, deck - 210, 130, 210, fill=LIGHT, stroke=YALE3, sw=2.5, rx=6))
    o.append(T(1165, deck - 176, "호퍼", 16, weight=800, fill=NAVY))
    o.append(Rc(1130, deck - 34, 70, 34, fill=CER, stroke=NAVY, sw=2, rx=4))
    o.append(T(1165, deck - 12, "서보", 13, weight=800, fill="#fff"))
    o.append(P("M 1228 %d L 1272 %d" % (deck, gy - 4), stroke=YALE3, sw=6,
               extra='marker-end="url(#flowB)"'))
    o.append(T(1282, gy - 60, "살포구 → 지면", 14, "start", 800, YALE3))
    o.append(Rc(1228, deck - 250, 34, 30, fill=STEEL, stroke=YALE, sw=2, rx=4))
    o.append(C(1235, deck - 235, 5, fill=NAVY))
    o.append(C(1255, deck - 235, 5, fill=NAVY))
    o.append(T(1270, deck - 230, "SR-04", 14, "start", 800, YALE))
    o.append(dim_h(900, 1230, deck - 292, "약 110 (차체 길이)", ext_from=deck - 210, size=17))

    o.append(T(24, 852, "28BYJ-48 두 개를 마주 보게 달아 바퀴를 차체 밖으로 내고, 오른쪽 모터 방향만 반전한다.",
               17, "start", 700, NAVY))
    o.append(T(24, 882, "바퀴 지름·바퀴 중심 간격은 실측해 pico/car/config.py의 WHEEL_D_MM·TRACK_MM에 넣는다.",
               17, "start", 700, CER))
    o.append('</svg>')
    return "".join(o)


# ─────────────────────────────────────────────────────── 5. board_layout.svg
def svg_board_layout():
    o = [head("-120 -170 1330 1240", 1330, 1240, "사거리 보드 배치")]
    o.append(T(-100, -122, "사거리 보드 900×900 배치 — 센서 기둥 · 젖음 · 조도 · 차 홈 · 갈래 경로", 30, "start", 800))
    o.append(Rc(0, 0, BOARD, BOARD, fill="#f4f8fb", stroke=NAVY, sw=3, rx=6))
    # 도로
    o.append(Rc(ROAD_LO, 0, ROAD_HI - ROAD_LO, BOARD, fill="#3f5f74"))
    o.append(Rc(0, ROAD_LO, BOARD, ROAD_HI - ROAD_LO, fill="#3f5f74"))
    o.append(L(MID, 0, MID, BOARD, "#c9b24a", 4, "24 18"))
    o.append(L(0, MID, BOARD, MID, "#c9b24a", 4, "24 18"))
    # 갈래 경로(중심 → 360mm)
    for d in ("N", "E", "S", "W"):
        if d == "N":
            o.append(L(MID, MID, MID, MID - OUT_MM, "#dff0f8", 3, "10 9"))
            o.append(L(MID, MID - SPRAY_FROM, MID, MID - SPRAY_TO, LIGHT, 14))
        elif d == "E":
            o.append(L(MID, MID, MID + OUT_MM, MID, "#dff0f8", 3, "10 9"))
            o.append(L(MID + SPRAY_FROM, MID, MID + SPRAY_TO, MID, LIGHT, 14))
        elif d == "S":
            o.append(L(MID, MID, MID, MID + OUT_MM, "#dff0f8", 3, "10 9"))
            o.append(L(MID, MID + SPRAY_FROM, MID, MID + SPRAY_TO, LIGHT, 14))
        else:
            o.append(L(MID, MID, MID - OUT_MM, MID, "#dff0f8", 3, "10 9"))
            o.append(L(MID - SPRAY_FROM, MID, MID - SPRAY_TO, MID, LIGHT, 14))

    # 차 홈
    o.append(Rc(MID - BODY_W / 2, MID - BODY_L / 2, BODY_W, BODY_L, fill="#cfe3f0", stroke=YALE2, sw=2.5, rx=6))
    o.append(T(MID, MID + 6, "차 홈", 17, weight=800, fill=NAVY))
    o.append(L(MID, MID - BODY_L / 2 - 4, MID, MID - BODY_L / 2 - 46, YALE2, 4, extra='marker-end="url(#flowB)"'))
    o.append(T(MID + 14, MID - BODY_L / 2 - 44, "북향", 15, "start", 800, YALE2))

    # 센서 기둥 · 젖음 · 조도
    labels = {"N": (28, -14, "start"), "E": (30, -30, "start"), "S": (-26, 34, "end"), "W": (-26, -14, "end")}
    for d, (x, y) in PILLARS.items():
        o.append(C(x, y, 17, fill=CER, stroke=NAVY, sw=2.5))
        o.append(T(x, y + 6, d, 16, weight=800, fill="#fff"))
        dx, dy, an = labels[d]
        o.append(T(x + dx, y + dy, "%s 기둥" % d, 17, an, 800, NAVY))
    o.append(Rc(WET_PT[0] - 13, WET_PT[1] - 13, 26, 26, fill=YALE3, stroke=NAVY, sw=2, rx=3))
    o.append(T(WET_PT[0] + 22, WET_PT[1] + 46, "젖음(E)", 16, "start", 800, YALE3))
    o.append(Rc(LIGHT_PT[0] - 13, LIGHT_PT[1] - 13, 26, 26, fill="#a16207", stroke=NAVY, sw=2, rx=3))
    o.append(T(LIGHT_PT[0] - 22, LIGHT_PT[1] + 42, "조도(W)", 16, "end", 800, "#8a5a06"))

    # 살포 구간 표시
    o.append(T(760, 168, "살포 구간 110~340mm", 17, "start", 800, YALE3))
    o.append(L(752, 174, 470, 196, YALE3, 1.5))

    # 갈래 이름
    o.append(T(MID, 40, "N 갈래", 19, weight=800, fill="#dff0f8"))
    o.append(T(MID, 878, "S 갈래", 19, weight=800, fill="#dff0f8"))
    o.append(T(866, 442, "E 갈래", 19, "end", 800, "#dff0f8"))
    o.append(T(34, 442, "W 갈래", 19, "start", 800, "#dff0f8"))

    # 동쪽 책상
    o.append(Rc(950, 300, 190, 300, fill="#f4f8fb", stroke=STEEL, sw=2, dash="8 6", rx=10))
    o.append(T(1045, 336, "보드 동쪽 책상", 16, weight=800, fill=NAVY))
    o.append(T(1045, 366, "센서 Pico #1", 15, weight=700, fill=YALE2))
    o.append(T(1045, 390, "맥북 USB", 15, weight=700, fill=YALE2))
    o.append(P("M 950 450 C 880 470, 800 500, 726 540", stroke=STEEL, sw=2,
               extra='stroke-dasharray="8 7"'))

    # 나침반
    o.append(L(820, 860, 820, 790, NAVY, 4, extra='marker-end="url(#flow)"'))
    o.append(T(820, 886, "북", 18, weight=800))

    # 치수
    o.append(dim_h(0, BOARD, -72, "900", ext_from=0, size=17))
    o.append(dim_v(0, BOARD, -60, "900", ext_from=0, size=17))
    o.append(dim_h(ROAD_LO, ROAD_HI, -32, "도로 150", ext_from=0, size=15))
    o.append(T(-100, 950, "갈래 이름·교량 여부는 model/data/roads/cross_arms.json을 따른다. 회색 점선 = 주행, 굵은 하늘색 = 서보 살포 구간.",
               17, "start", 700, NAVY))
    o.append(T(-100, 978, "차는 홈(450,450)에서 북향으로 대기한다. 갈래 방위: N=0° E=90° S=180° W=270°(시계 방향).",
               17, "start", 600, CER))
    o.append('</svg>')
    return "".join(o)


# ─────────────────────────────────────────────────────── 6. car_states.svg
def svg_car_states():
    o = [head("0 0 1560 1000", 1560, 1000, "제설차 상태기계")]
    o.append(T(24, 46, "제설차 상태기계 — idle · run · pause · stopped · error", 32, "start", 800))
    o.append(T(24, 78, "상태 이름은 UDP 텔레메트리 state 값과 같다.", 19, "start", 600, CER))

    def st(x, y, w, h, name, sub, fill, accent=NAVY):
        s = [Rc(x, y, w, h, fill=fill, stroke=accent, sw=2.5, rx=12)]
        s.append(T(x + w / 2, y + 40, name, 26, weight=800, fill=NAVY))
        for i, line in enumerate(sub):
            s.append(T(x + w / 2, y + 68 + i * 22, line, 15, weight=600, fill="#1f3b52"))
        return "".join(s)

    o.append(st(70, 150, 300, 100, "idle", ["북향 대기", "코일 OFF"], "#dceaf4"))
    o.append(st(620, 150, 320, 100, "run", ["계획 실행", "phase 4단계"], "#cfe3f0"))
    o.append(st(1150, 150, 300, 100, "pause", ["모터 정지", "계획 유지"], "#e8f1f8"))
    o.append(st(620, 470, 320, 110, "stopped", ["코일 OFF · 서보 닫힘", "위치 기억"], "#b9d6e7"))
    o.append(st(1150, 470, 300, 110, "error", ["초기화·통신 실패", "재부팅으로 복귀"], "#dceaf4"))

    # idle → run
    o.append(L(370, 180, 620, 180, NAVY, 3, extra='marker-end="url(#flow)"'))
    o.append(T(495, 164, "plan", 19, weight=800, fill=NAVY))
    o.append(T(495, 206, "실행 중이면 ok=false", 14, weight=600, fill=CER))
    # run → idle
    o.append(L(620, 222, 370, 222, CER, 3, extra='marker-end="url(#flowB)"'))
    o.append(T(495, 246, "plan_done / aborted", 15, weight=700, fill=CER))

    # run → pause
    o.append(L(940, 180, 1150, 180, NAVY, 3, extra='marker-end="url(#flow)"'))
    o.append(T(1045, 164, "5초 무패킷", 17, weight=800, fill=NAVY))
    # pause → run
    o.append(L(1150, 222, 940, 222, CER, 3, extra='marker-end="url(#flowB)"'))
    o.append(T(1045, 246, "패킷 수신", 15, weight=700, fill=CER))

    # run → stopped
    o.append(L(760, 250, 760, 470, NAVY, 3, extra='marker-end="url(#flow)"'))
    o.append(T(772, 370, "stop / 버튼", 17, "start", 800, NAVY))
    # stopped → run
    o.append(L(690, 470, 690, 250, CER, 3, extra='marker-end="url(#flowB)"'))
    o.append(T(678, 370, "버튼(재개)", 17, "end", 800, CER))

    # pause → stopped
    o.append(P("M 1300 250 L 1300 410 L 940 410 L 940 470", stroke=NAVY, sw=3, extra='marker-end="url(#flow)"'))
    o.append(T(1120, 398, "stop / 버튼", 17, weight=800, fill=NAVY))

    # stopped → idle
    o.append(P("M 620 520 L 220 520 L 220 250", stroke=CER, sw=3, extra='marker-end="url(#flowB)"'))
    o.append(T(430, 560, "home(중심 복귀) → idle", 15, "middle", 700, CER))

    # run 자기루프(장애물)
    o.append(P("M 700 150 C 700 76, 860 76, 860 150", stroke=YALE3, sw=3, extra='marker-end="url(#flowB)"'))
    o.append(T(780, 68, "초음파 < 8cm → 모터 정지", 16, weight=800, fill=YALE3))

    # 하단: 규칙 + 단계
    o.append(Rc(70, 640, 470, 330, fill="#f4f8fb", stroke=STEEL, sw=2, rx=12))
    o.append(T(96, 678, "규칙", 22, "start", 800, NAVY))
    rules = ["같은 seq는 한 번만 실행한다.",
             "링크 5초 끊기면 pause, 다시 받으면 재개.",
             "초음파 8cm 안쪽이면 모터를 세운다.",
             "1초 비면 재개, 10초 막히면 aborted.",
             "stop·버튼: 코일 OFF, 서보 닫힘.",
             "부팅 직후는 idle, 북향·중심."]
    for i, line in enumerate(rules):
        o.append(T(96, 716 + i * 40, "· " + line, 17, "start", 600, "#1f3b52"))

    o.append(Rc(580, 640, 940, 330, fill="#f4f8fb", stroke=STEEL, sw=2, rx=12))
    o.append(T(606, 678, "run 내부 phase — 갈래 하나마다", 22, "start", 800, NAVY))
    chips = [("turn", "갈래 방위 회전"), ("out", "360mm 전진"), ("back", "180° 회전"), ("home", "360mm 복귀")]
    colors = ("#dceaf4", "#cfe3f0", "#dceaf4", "#cfe3f0")
    for i, (name, sub) in enumerate(chips):
        x = 606 + i * 228
        o.append(Rc(x, 706, 190, 96, fill=colors[i], stroke=YALE2, sw=2, rx=10))
        o.append(T(x + 95, 740, name, 22, weight=800, fill=NAVY))
        o.append(T(x + 95, 772, sub, 15, weight=700, fill=YALE2))
        if i < 3:
            o.append(L(x + 194, 754, x + 222, 754, NAVY, 3, extra='marker-end="url(#flow)"'))
    o.append(T(606, 846, "out 단계에서 중심 110~340mm 구간에만 서보를 연다(열림 70°, 닫힘 0°).", 17, "start", 700, YALE))
    o.append(T(606, 882, "계획이 끝나면 마지막에 북향으로 돌아 idle로 간다. 순서는 plan.order를 따른다.", 17, "start", 700, YALE))
    o.append(T(606, 918, "실행 중에 새 plan이 오면 ack ok=false로 거절한다(계획 겹침 금지).", 17, "start", 600, CER))
    o.append('</svg>')
    return "".join(o)


# ───────────────────────────────────────────────────────── 7. protocol.svg
def svg_protocol():
    o = [head("0 0 1560 1060", 1560, 1060, "UDP 프로토콜 순서")]
    o.append(T(24, 44, "UDP 프로토콜 — 서버(맥북) ⇄ 제설차 Pico #2", 32, "start", 800))
    o.append(T(24, 76, "한 줄 = 한 데이터그램(JSON). 서버 9200 수신, 차 9201 수신.", 19, "start", 600, CER))

    sx, cx = 430, 1080
    for x, name, sub in ((sx, "서버", "맥북 0.0.0.0:9200"), (cx, "제설차", "Pico #2 :9201")):
        o.append(Rc(x - 150, 110, 300, 80, fill="#cfe3f0", stroke=NAVY, sw=2.5, rx=10))
        o.append(T(x, 148, name, 26, weight=800, fill=NAVY))
        o.append(T(x, 176, sub, 15, weight=600, fill=YALE2))
        o.append(L(x, 195, x, 930, STEEL, 2, "9 8"))

    o.append(L(60, 200, 60, 930, STEEL, 2, extra='marker-end="url(#flowB)"'))
    o.append(T(46, 560, "시간", 18, "middle", 800, CER, extra='transform="rotate(-90 46 560)"'))

    def msg(y, label, sub, to_car=False, dash=None, color=NAVY, mark="flow"):
        """to_car=True: 서버 → 차. False: 차 → 서버."""
        s = []
        x1, x2 = (sx, cx) if to_car else (cx, sx)
        s.append(L(x1, y, x2, y, color, 3, dash, extra='marker-end="url(#%s)"' % mark))
        s.append(T((sx + cx) / 2, y - 12, label, 20, weight=800, fill=color))
        if sub:
            s.append(T((sx + cx) / 2, y + 26, sub, 15, weight=600, fill=YALE2))
        return "".join(s)

    o.append(msg(250, "hello {id:\"car1\"}", "부팅 시 브로드캐스트(SERVER_IP 비면)", to_car=False, dash="8 7"))
    o.append(msg(330, "plan {seq, order:[…]}", "실행 중이면 거절", to_car=True))
    o.append(msg(400, "ack {seq, ok}", "같은 seq는 한 번만 실행", to_car=False))
    o.append(msg(470, "evt plan_start · arm_start", "갈래 시작", to_car=False))
    o.append(msg(540, "evt spray_on · spray_off · arm_done", "살포 구간 110~340mm", to_car=False))
    o.append(msg(620, "tel 500ms", "{state, arm, phase, x, y, h, spray, obst_cm}", to_car=False, color=YALE3, mark="flowB"))
    o.append(msg(710, "stop", "비상 정지 · 자동 끔", to_car=True))
    o.append(msg(780, "evt stopped", "코일 OFF · 서보 닫힘", to_car=False, color=YALE3, mark="flowB"))
    o.append(msg(850, "home", "추측 위치로 중심 복귀", to_car=True))
    o.append(msg(920, "evt plan_done · tel idle", "계획 종료", to_car=False, color=YALE3, mark="flowB"))

    # 규칙 상자
    o.append(Rc(1170, 220, 360, 300, fill="#f4f8fb", stroke=STEEL, sw=2, rx=12))
    o.append(T(1194, 256, "규칙", 22, "start", 800, NAVY))
    for i, line in enumerate(["tel 500ms 주기(끊김 감시)", "5초 무패킷 → pause", "패킷 오면 재개", "obst < 8cm → 정지",
                              "1초 비면 재개 · 10초 aborted", "stop/home은 언제나 받는다"]):
        o.append(T(1194, 292 + i * 36, "· " + line, 16, "start", 600, "#1f3b52"))

    o.append(T(24, 1014, "ack는 받은 seq를 되돌려 준다. 서버는 ack ok=false면 계획을 접고 이벤트에 남긴다.",
               17, "start", 700, NAVY))
    o.append(T(24, 1042, "차가 없거나 링크가 끊기면 서버는 '모의 실행'으로 갈래당 3초 뒤 완료 처리한다.",
               17, "start", 600, CER))
    o.append('</svg>')
    return "".join(o)


def svg_board_v2():
    """사용자 보드 사진 기준 평면. 값은 계약 8절의 사진 추정값(mm)."""
    o = [head("-130 -200 1550 1420", 1550, 1420, "보드 평면 v2(사진 추정)")]
    o.append(T(-110, -160, "보드 평면 — 사용자 사진 기준", 34, "start", 800))
    o.append(T(-110, -124, "검은 종이 도로 폭 약 150, 가운데 A3 광장 297×420. 중심 (480,340), 원점은 판 왼쪽 위.", 19, "start", 600, CER))
    o.append(Rc(-110, -108, 640, 46, fill="#cfe3f0", stroke=YALE2, sw=2, rx=8))
    o.append(T(-98, -78, "사진 추정값 — 줄자로 실측해 config와 board.json을 고친다", 18, "start", 800, NAVY))

    # 판·도로·광장
    o.append(Rc(-20, 0, 970, 1000, fill="#fbfcfd", stroke=NAVY, sw=4))
    o.append(Rc(405, 0, 150, 735, fill="#2f3338"))
    o.append(Rc(-20, 265, 970, 150, fill="#2f3338"))
    o.append(Rc(331.5, 130, 297, 420, fill="#3b4046", stroke="#6b7480", sw=2))
    o.append(L(480, 0, 480, 735, "#c9b24a", 3, "22 18"))
    o.append(L(-20, 340, 950, 340, "#c9b24a", 3, "22 18"))
    o.append(T(348, 172, "A3 광장", 19, "start", 800, "#dff0f8"))
    o.append(T(348, 196, "297 × 420", 15, "start", 700, "#dff0f8"))

    # 건물
    bld = [(40, 60, 220, 140, "NW", "낮은 주택", "그림자 N 0.29"),
           (680, 60, 220, 140, "NE", "고색고 교사동", "낮게"),
           (40, 470, 250, 150, "SW", "아파트(높음)", "W 1.00 · S 0.84"),
           (680, 470, 220, 140, "SE", "낮은 건물", "보조")]
    for (x, y, w, h, tag, name, note) in bld:
        o.append(Rc(x, y, w, h, fill="#cbd9e4", stroke=YALE, sw=2.5, rx=5))
        o.append(T(x + w / 2, y + 40, tag, 22, weight=800, fill=NAVY))
        o.append(T(x + w / 2, y + 76, name, 17, weight=700, fill=NAVY))
        o.append(T(x + w / 2, y + 102, note, 15, weight=600, fill=YALE3))

    # 센서 기둥 · 젖음/조도
    for d, (x, y), (dx, dy, an) in (("N", (585, 120), (24, -8, "start")), ("E", (700, 445), (26, 30, "start")),
                                    ("S", (375, 600), (-26, 34, "end")), ("W", (260, 235), (-10, -20, "end"))):
        o.append(C(x, y, 14, fill=CER, stroke=NAVY, sw=2.5))
        o.append(T(x, y + 6, d, 14, weight=800, fill="#fff"))
        o.append(T(x + dx, y + dy, "%s 기둥" % d, 16, an, 800, NAVY))
    o.append(Rc(168, 233, 24, 24, fill=YALE3, stroke=NAVY, sw=2, rx=3))
    o.append(T(202, 250, "젖음·조도", 15, "start", 800, YALE3))

    # 기지
    o.append(Rc(395, 745, 320, 230, fill="#eef4f8", stroke=NAVY, sw=3, rx=6))
    o.append(Rc(410, 750, 140, 185, fill="#dce9f2", stroke=YALE2, sw=2))
    o.append(T(480, 786, "차고", 17, weight=800, fill=NAVY))
    o.append(Rc(558, 750, 150, 220, fill="#e6f0f7", stroke=YALE2, sw=2, dash="7 5", rx=4))
    o.append(T(633, 786, "관제실", 16, weight=800, fill=NAVY))
    o.append(T(633, 812, "Pico #1", 14, weight=700, fill=YALE2))
    o.append(L(410, 745, 386, 721, NAVY, 3))
    o.append(L(550, 745, 574, 721, NAVY, 3))
    # 도킹 차
    o.append(Rc(423.5, 765, 113, 150, fill=LIGHT, stroke=YALE2, sw=2.5, rx=5))
    o.append(T(480, 830, "차", 16, weight=800, fill=NAVY))
    o.append(T(480, 854, "도킹", 13, weight=700, fill=YALE2))
    o.append(C(480, 865, 7, fill="#fff", stroke=NAVY, sw=2))
    o.append(T(596, 872, "사일로 Ø12", 14, "start", 800, YALE3))
    o.append(L(588, 866, 490, 866, YALE3, 1.4))
    o.append(Rc(440, 928, 80, 8, fill=CER, stroke=NAVY, sw=1.5))
    o.append(T(480, 960, "범퍼판·도킹 스위치", 13, weight=700, fill=YALE2))

    # 주행 경로
    o.append(L(480, 840, 480, 348, "#e6f4fb", 3, "10 9"))
    o.append('<path d="M 480 330 l -9 -18 l 18 0 z" fill="#e6f4fb"/>')
    o.append(T(492, 600, "출발 500", 16, "start", 800, "#e6f4fb"))
    o.append(L(506, 348, 506, 846, "#8fc3dc", 3, "9 8", extra='marker-end="url(#arrE)"'))
    o.append(T(520, 700, "귀환(후진 515)", 15, "start", 800, SKY))
    o.append(L(480, 340, 480, 96, "#e6f4fb", 3, "10 9"))
    o.append(L(480, 240, 480, 96, LIGHT, 11))
    o.append(L(480, 340, 852, 340, "#e6f4fb", 3, "10 9"))
    o.append(L(580, 340, 852, 340, LIGHT, 11))
    o.append(L(480, 340, 88, 340, "#e6f4fb", 3, "10 9"))
    o.append(L(380, 340, 88, 340, LIGHT, 11))
    o.append(L(480, 440, 480, 726, LIGHT, 11))
    o.append(T(600, 296, "살포 = 굵은 띠", 15, "start", 800, LIGHT))

    # 치수
    o.append(dim_h(480, 950, -22, "E 470", ext_from=0, size=17))
    o.append(dim_h(-20, 480, -22, "W 500", ext_from=0, size=17))
    o.append(dim_v(0, 340, -70, "N 340", ext_from=-20, size=17))
    o.append(dim_v(340, 735, 990, "S 395", ext_from=735, size=17))

    # 범례
    o.append(Rc(1030, 40, 370, 470, fill="#f4f8fb", stroke=STEEL, sw=2, rx=10))
    o.append(T(1054, 78, "건물 배치 원칙", 21, "start", 800, NAVY))
    for i, line in enumerate([
            "도로 가장자리에서 30mm,",
            "광장 모서리에서 40mm 이상 띄운다.",
            "SW는 높은 아파트: W·S 그늘.",
            "E 옆은 고색고 교사동.",
            "NW는 낮은 주택(N 0.29).",
            "초음파·차 간섭을 피해 비운다."]):
        o.append(T(1054, 116 + i * 30, "· " + line, 15, "start", 600, "#1f3b52"))
    o.append(T(1054, 320, "실측 기입(8)", 19, "start", 800, YALE3))
    for i, line in enumerate(["중심 x·y", "N·E·W 판 끝", "S 도로 끝", "도로 폭", "광장 가로·세로"]):
        o.append(T(1054, 352 + i * 28, "· " + line, 14, "start", 600, "#1f3b52"))

    o.append(T(-110, 1052, "사진 추정: 실측값을 pico/car/config.py(CENTER_X·CENTER_Y·BASE_DIST_MM·ARM_OUT_MM·SPRAY_WIN)와 server/board.json에 넣는다.",
               17, "start", 700, NAVY))
    o.append(T(-110, 1082, "S 도로는 남쪽 395에서 끝나고 그 아래 흰 공간이 기지다. 차는 기지에서 북상해 중심에 닿고, 갈래를 돌고, 북향 후진으로 돌아온다.",
               17, "start", 600, CER))
    o.append('</svg>')
    return "".join(o)


def svg_base_plan():
    """제설기지 평면 + 정면 단면. 계약 9절(320×230, 차고 140×190×120, 출구 Ø12)."""
    s = 2.4
    o = [head("0 0 1800 1020", 1800, 1020, "제설기지 평면·단면")]
    o.append(T(40, 48, "제설기지 — 평면(위에서) 과 정면 단면", 32, "start", 800))
    o.append(T(40, 80, "외곽 320×230. 서쪽 차고 140×190×120, 동쪽 관제실. 단위 mm, 화면 2.4px = 1mm.", 18, "start", 600, CER))

    # ── (a) 평면 ──
    ox, oy = 90.0, 170.0
    X = lambda v: ox + (v - 395) * s
    Y = lambda v: oy + (v - 745) * s
    o.append(T(40, 106, "(a) 평면", 21, "start", 800))
    o.append(Rc(X(395), Y(745), 320 * s, 230 * s, fill="#eef4f8", stroke=NAVY, sw=3, rx=8))
    o.append(Rc(X(410), Y(750), 140 * s, 185 * s, fill="#dce9f2", stroke=YALE2, sw=2.5))
    o.append(Rc(X(558), Y(750), 150 * s, 220 * s, fill="#e6f0f7", stroke=YALE2, sw=2, dash="8 6", rx=4))
    for (x1, y1, x2, y2) in ((410, 750, 410, 935), (550, 750, 550, 935)):
        o.append(L(X(x1), Y(y1), X(x2), Y(y2), NAVY, 5))
    # 깔때기
    o.append(L(X(410), Y(745), X(386), Y(722), NAVY, 5))
    o.append(L(X(550), Y(745), X(574), Y(722), NAVY, 5))
    o.append(T(X(480), Y(714), "입구 45° · 20", 14, weight=800, fill=NAVY))
    # 안내 레일
    o.append(L(X(414), Y(760), X(414), Y(928), CER, 5))
    o.append(L(X(546), Y(760), X(546), Y(928), CER, 5))
    o.append(T(X(480), Y(946), "안내 레일 8", 13, weight=700, fill=YALE3))
    # 차
    o.append(Rc(X(423.5), Y(765), 113 * s, 150 * s, fill=LIGHT, stroke=YALE2, sw=2.5, rx=6))
    o.append(T(X(480), Y(828), "차", 18, weight=800, fill=NAVY))
    o.append(T(X(480), Y(852), "150×113", 12, weight=700, fill=YALE2))
    # 범퍼판 + 스위치
    o.append(Rc(X(450), Y(926), 60 * s, 9 * s, fill=CER, stroke=NAVY, sw=2))
    o.append(T(X(480), Y(972), "범퍼판 60×30 + 도킹 스위치", 13, weight=700, fill=YALE2))
    # 사일로 출구
    o.append(C(X(480), Y(865), 13, fill="#fff", stroke=NAVY, sw=2.5))
    o.append(L(X(480), Y(878), X(480), Y(897), YALE3, 1.5))
    o.append(T(X(480), Y(914), "사일로 Ø12", 13, weight=800, fill=YALE3))
    # 관제실
    o.append(Rc(X(572), Y(770), 60 * s, 44 * s, fill="#cfe3f0", stroke=YALE2, sw=2, rx=4))
    o.append(T(X(602), Y(796), "Pico #1", 14, weight=800, fill=NAVY))
    o.append(Rc(X(572), Y(830), 54 * s, 34 * s, fill="#dce9f2", stroke=YALE2, sw=2, rx=4))
    o.append(T(X(599), Y(852), "브레드보드", 11, weight=700, fill=YALE2))
    o.append(Rc(X(636), Y(770), 58 * s, 34 * s, fill="#cfe3f0", stroke=YALE2, sw=2, rx=4))
    o.append(T(X(665), Y(792), "LCD", 13, weight=800, fill=NAVY))
    o.append(Rc(X(640), Y(830), 54 * s, 30 * s, fill="#dce9f2", stroke=YALE2, sw=2, rx=4))
    o.append(T(X(667), Y(850), "LED·부저", 11, weight=700, fill=YALE2))
    o.append(L(X(558), Y(940), X(700), Y(940), CER2, 6, "10 7"))
    o.append(T(X(629), Y(958), "케이블 통로", 13, weight=700, fill=YALE3))

    # ── (b) 단면 ──
    bx, gy = 940.0, 780.0
    s2 = s
    o.append(T(900, 106, "(b) 정면 단면 — 입구가 왼쪽", 21, "start", 800))
    o.append(L(900, gy, 1600, gy, NAVY, 3))
    for gx in range(910, 1600, 22):
        o.append(L(gx, gy, gx - 9, gy + 12, STEEL, 2))
    # 차고 벽·지붕
    ceil = gy - 120 * s2
    o.append(L(bx, gy, bx, ceil, NAVY, 5))
    o.append(Rc(1396, ceil, 20, 120 * s2, fill="#cbd9e4", stroke=NAVY, sw=2))
    o.append(Rc(bx - 10, ceil - 12, 1130 - bx + 10, 12, fill="#cbd9e4", stroke=NAVY, sw=2))
    o.append(Rc(1158, ceil - 12, 1416 - 1158 + 10, 12, fill="#cbd9e4", stroke=NAVY, sw=2))
    # 차
    o.append(Rc(964, gy - 95 * s2, 150 * s2, 95 * s2, fill=LIGHT, stroke=YALE2, sw=2.5, rx=6))
    o.append(T(1144, gy - 40 * s2, "차", 16, weight=800, fill=NAVY))
    # 범퍼판
    o.append(Rc(1324, gy - 30 * s2, 72, 30 * s2, fill=CER, stroke=NAVY, sw=2))
    o.append(T(1360, gy - 14 * s2, "범퍼", 11, weight=800, fill="#fff"))
    # 도킹 스위치(뒤벽 뒤)
    o.append(C(1430, gy - 22, 9, fill="#fff", stroke=RED, sw=2.5))
    # 사일로
    fx = 1144.0
    o.append(P("M %.0f 330 L %.0f 330 L %.0f %.0f L %.0f %.0f Z" % (fx - 100, fx + 100, fx + 14, ceil - 6, fx - 14, ceil - 6),
               fill=LIGHT, stroke=YALE3, sw=2.5))
    o.append(Rc(fx - 14, ceil - 6, 28, 18, fill="#fff", stroke=NAVY, sw=2))
    o.append(T(1290, 340, "사일로 깔때기", 15, "start", 800, YALE3))
    o.append(T(1290, 366, "출구 Ø12", 13, "start", 700, YALE3))
    o.append(T(1290, 392, "SG90 패들 0°/60°", 13, "start", 700, YALE3))
    # 차 호퍼 입구
    o.append(C(fx, gy - 95 * s2 + 8, 8, fill="none", stroke=RED, sw=2.5))
    # 경광등
    for i in range(3):
        o.append(C(962 + i * 24, ceil - 26, 7, fill=SKY, stroke=YALE3, sw=1.5))
    o.append(T(920, ceil - 46, "지붕 경광등(링)", 13, "start", 700, YALE3))
    # 치수
    o.append(dim_v(ceil, gy, bx - 62, "120", ext_from=bx, size=16))
    o.append(dim_h(bx, 1396, gy + 52, "190 (깊이)", ext_from=gy, size=16))
    o.append(dim_h(fx, 1396, ceil + 28, "75", ext_from=ceil, size=15))

    # ── 부품 설명 ──
    o.append(Rc(1470, 300, 300, 330, fill="#f4f8fb", stroke=STEEL, sw=2, rx=10))
    o.append(T(1490, 336, "단면 표시", 19, "start", 800, NAVY))
    for i, line in enumerate([
            "사일로: 종이·PET 원뿔",
            "출구 Ø12, SG90 패들 게이트",
            "호퍼 입구 = 뒤 범퍼에서 75",
            "뒤벽 범퍼판 60×30",
            "도킹 스위치 = 뒤벽 뒤 택트",
            "지붕 링 = WS2812 8픽셀",
            "안내 레일 8mm(양쪽 벽)"]):
        o.append(T(1490, 374 + i * 34, "· " + line, 14, "start", 600, "#1f3b52"))

    o.append(T(40, 940, "차고 안내 레일 8mm는 바닥 양쪽 벽을 따라 붙여 차를 가운데로 모은다. 입구 벽 끝은 45°로 20mm 벌린 깔때기다.",
               17, "start", 700, NAVY))
    o.append(T(40, 968, "도킹: 차가 북향 후진으로 들어와 범퍼판을 밀면 도킹 스위치가 눌린다(눌리면 0). 그때 사일로 게이트가 열려 호퍼를 채운다.",
               17, "start", 600, CER))
    o.append('</svg>')
    return "".join(o)


def svg_car_build():
    """제설차 제작 도면. 하판 100(폭)×150(길이), 전체 113×150×약 95, 바퀴 Ø65×8."""
    s = 4.0
    o = [head("0 0 1800 1000", 1800, 1000, "제설차 제작 도면")]
    o.append(T(30, 46, "제설차 제작 도면 — 하판 100×150, 전체 113×150×약 95", 32, "start", 800))
    o.append(T(30, 78, "단위 mm, 화면 4px = 1mm. 28BYJ-48 두 개를 마주 보게 달고 축은 바깥으로 낸다. 앞이 위(북).", 18, "start", 600, CER))

    px, py = 60.0, 190.0
    PX = lambda v: px + v * s
    PY = lambda v: py + v * s
    o.append(T(px, 122, "(a) 위에서 — 앞이 위(북)", 21, "start", 800))
    o.append(Rc(PX(0), PY(0), 100 * s, 150 * s, fill="#fbfcfd", stroke=NAVY, sw=3, rx=8))

    # 바퀴 Ø65×8 — 전체 폭 113
    for cx in (50 - 52.5, 50 + 52.5):
        o.append(Rc(PX(cx - 4), PY(42.5), 8 * s, 65 * s, fill=NAVY, rx=6))
        o.append(T(PX(cx), PY(41.5), "Ø65", 11, weight=800, fill=NAVY))
    # 모터(마주 보게, 차체 밖으로 조금) + 축
    for mx in (-4, 76):
        o.append(Rc(PX(mx), PY(61), 28 * s, 28 * s, fill=SKY, stroke=YALE, sw=2, rx=4))
        o.append(T(PX(mx + 14), PY(79), "M", 15, weight=800, fill=NAVY))
    o.append(L(PX(-4), PY(75), PX(-6.5), PY(75), CER, 4))
    o.append(L(PX(104), PY(75), PX(106.5), PY(75), CER, 4))
    # 호퍼 50×50
    o.append(Rc(PX(25), PY(40), 50 * s, 50 * s, fill=LIGHT, stroke=YALE3, sw=2.5, rx=5))
    o.append(T(PX(50), PY(64), "호퍼 50×50", 14, weight=800, fill=NAVY))
    o.append(T(PX(50), PY(72), "높이 55", 12, weight=700, fill=YALE3))
    o.append(C(PX(50), PY(86), 7, fill="#fff", stroke=NAVY, sw=2))
    # ULN ×2 (앞쪽 좌우)
    for ux, name in ((2, "ULN #1"), (68, "ULN #2")):
        o.append(Rc(PX(ux), PY(4), 30 * s, 30 * s, fill="#e6f0f7", stroke=YALE2, sw=2, rx=4))
        o.append(T(PX(ux + 15), PY(22), name, 11, weight=800, fill=NAVY))
    # SR-04 (앞, 판 밖으로 조금)
    o.append(Rc(PX(40), PY(-9), 20 * s, 9 * s, fill=STEEL, stroke=YALE, sw=2, rx=3))
    o.append(T(PX(62), PY(-12), "SR-04", 12, "start", 800, YALE))
    # 배터리 · Pico
    o.append(Rc(PX(8), PY(104), 60 * s, 36 * s, fill="#cfe3f0", stroke=YALE2, sw=2, rx=4))
    o.append(T(PX(38), PY(126), "보조배터리", 12, weight=800, fill=NAVY))
    o.append(Rc(PX(76), PY(96), 21 * s, 51 * s, fill="#dce9f2", stroke=YALE2, sw=2, rx=3))
    o.append(T(PX(86.5), PY(126), "Pico", 11, weight=800, fill=NAVY))
    # LED·버튼·부저
    o.append(C(PX(94), PY(92), 6, fill=RED, stroke=NAVY, sw=1.5))
    o.append(T(PX(90), PY(96), "LED", 11, "end", 700, RED))
    o.append(C(PX(6), PY(96), 6, fill="#fff", stroke=NAVY, sw=1.5))
    o.append(T(PX(10), PY(100), "버튼", 11, "start", 700, YALE2))
    o.append(C(PX(8), PY(48), 6, fill="#fff", stroke=NAVY, sw=1.5))
    o.append(T(PX(8), PY(40), "부저", 11, "start", 700, YALE2))
    # 범퍼판
    o.append(Rc(PX(20), PY(146), 60 * s, 4 * s, fill=CER, stroke=NAVY, sw=1.5))
    o.append(T(PX(50), PY(142), "범퍼판 60×30", 11, weight=700, fill=YALE2))

    # 조립 번호
    for n, (vx, vy) in enumerate([(96, 50), (10, 84), (-2.5, 40), (44, 84), (6, 10), (86, 140),
                                  (62, 46), (50, 86), (50, -4), (94, 92), (50, 148), (30, 96)], 1):
        o.append(C(PX(vx), PY(vy), 10, fill=NAVY, stroke="#fff", sw=1.5))
        o.append(T(PX(vx), PY(vy) + 4, str(n), 10, weight=800, fill="#fff"))

    o.append(dim_v(PY(0), PY(150), PX(0) - 46, "150", ext_from=PX(0), size=16))
    o.append(dim_h(PX(0), PX(100), PY(150) + 56, "100 (폭)", ext_from=PY(150), size=16))

    # ── (b) 옆에서 ──
    gy, gx = 740.0, 760.0
    rear, front = 800.0, 1400.0          # 차체 길이 150 = 600px
    mid = (rear + front) / 2             # 바퀴 중심 = 길이 중앙(75)
    o.append(T(gx, 122, "(b) 옆에서 — 앞이 오른쪽", 21, "start", 800))
    o.append(L(gx - 20, gy, 1500, gy, NAVY, 3))
    for k in range(int(gx) - 10, 1500, 24):
        o.append(L(k, gy, k - 9, gy + 12, STEEL, 2))
    wr = 65 * s / 2
    o.append(C(mid, gy - wr, wr, fill="#cbd9e4", stroke=STEEL, sw=2, extra='stroke-dasharray="7 5"'))
    o.append(C(mid, gy - wr, 24, fill="#e3eef6", stroke=STEEL, sw=2))
    o.append(T(mid - 74, gy - wr + 5, "Ø65", 12, "end", 800, fill=NAVY))
    o.append(T(mid + 150, gy - wr - 6, "바퀴 중심 = 길이 중앙(75)", 12, "start", 700, YALE2))
    deck = gy - 38 * s
    o.append(Rc(rear, deck, 150 * s, 12, fill=STEEL, stroke=YALE, sw=2))
    o.append(T(rear + 16, deck - 12, "하판(우드락 2겹)", 12, "start", 700, YALE))
    o.append(T(mid + 150, deck + 44, "점선 = 반대쪽 바퀴", 11, "start", 600, STEEL))
    # 호퍼(입구는 뒤 범퍼에서 75 = 차체 중앙)
    o.append(Rc(mid - 25 * s, deck - 55 * s, 50 * s, 55 * s, fill=LIGHT, stroke=YALE3, sw=2.5, rx=4))
    o.append(T(mid, deck - 30 * s, "호퍼", 14, weight=800, fill=NAVY))
    o.append(T(mid, deck - 10 * s, "55", 12, weight=700, fill=YALE3))
    # 살포구(차체 가운데 아래) — 바퀴는 반대쪽이므로 뒤에 그린다
    o.append(P("M %.0f %.0f L %.0f %.0f" % (mid, deck + 14, mid, gy - 8), stroke=YALE3, sw=4,
               extra='marker-end="url(#flowB)"'))
    o.append(T(mid + 12, gy - 44, "살포구", 13, "start", 800, YALE3))
    # 미끄럼 받침(병뚜껑)
    for bx in (rear + 40, front - 40):
        o.append(Rc(bx - 26, gy - 28, 52, 28, fill="#cbd9e4", stroke=YALE2, sw=1.5, rx=6))
    o.append(T(front - 40, gy + 26, "미끄럼 받침(병뚜껑)", 11, "middle", 700, YALE2))
    # 범퍼판·SR-04
    o.append(Rc(rear, deck - 30 * s, 12, 30 * s, fill=CER, stroke=NAVY, sw=1.5))
    o.append(T(rear - 8, deck - 12, "범퍼", 10, "end", 800, YALE2))
    o.append(Rc(front - 40, deck - 46, 40, 46, fill=STEEL, stroke=YALE, sw=2, rx=3))
    o.append(T(front - 20, deck - 58, "SR-04", 12, weight=800, fill=YALE))
    o.append(dim_v(deck - 55 * s, gy, gx - 40, "약 95", ext_from=rear, size=15))
    o.append(dim_h(rear, front, deck - 55 * s - 34, "150 (길이)", ext_from=deck - 55 * s, size=15))

    # ── (c) 조립 순서 ──
    cx0 = 1540.0
    o.append(T(cx0, 122, "(c) 조립 순서", 21, "start", 800))
    steps = ["하판 100×150 재단(2겹)", "모터 브래킷 고정", "바퀴 3겹 원판 접착",
             "D축 구멍 3×5 뚫기", "바퀴·고무줄 장착", "ULN2003 ×2 부착",
             "Pico·배터리 부착", "호퍼 접착·구멍", "SG90 패들 장착",
             "SR-04 앞면 장착", "LED·버튼·부저·범퍼", "배선·보정 시험"]
    for i, line in enumerate(steps):
        y = 168 + i * 34
        o.append(C(cx0 + 10, y - 5, 11, fill=NAVY, stroke="#fff", sw=1.5))
        o.append(T(cx0 + 10, y - 1, str(i + 1), 11, weight=800, fill="#fff"))
        o.append(T(cx0 + 30, y, line, 14, "start", 600, "#1f3b52"))

    o.append(T(30, 880, "바퀴: 우드락 3겹 원판 Ø65 + 고무줄 타이어 + D축 구멍 3×5. 앞뒤 미끄럼 받침은 병뚜껑을 쓴다.",
               17, "start", 700, NAVY))
    o.append(T(30, 910, "무게 배치: 뒤쪽 배터리·Pico, 가운데 호퍼, 앞쪽 ULN·SR-04. 바퀴 접지를 살리려 무게 중심을 조금 뒤에 둔다.",
               17, "start", 600, CER))
    o.append(T(30, 940, "호퍼 입구는 뒤 범퍼에서 75mm다. 기지 사일로 출구와 같은 자리라 도킹하면 그대로 떨어진다.",
               17, "start", 600, YALE3))
    o.append('</svg>')
    return "".join(o)


FIGURES = (
    ("system.svg", svg_system),
    ("sensor_wiring.svg", svg_sensor_wiring),
    ("car_wiring.svg", svg_car_wiring),
    ("car_states.svg", svg_car_states),
    ("protocol.svg", svg_protocol),
    ("board_v2.svg", svg_board_v2),
    ("base_plan.svg", svg_base_plan),
    ("car_build.svg", svg_car_build),
)


def main():
    if not os.path.isdir(IMG):
        os.makedirs(IMG)
    for name, fn in FIGURES:
        path = os.path.join(IMG, name)
        body = fn()
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        print("%-22s %7d B" % (name, len(body.encode("utf-8"))))


if __name__ == "__main__":
    main()
