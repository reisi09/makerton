"""ICE-ZERO 사거리 모형 도면(단위 mm, 원점 = 보드 왼쪽 위, 위쪽 = 북). CONTRACT_CROSS.md 6절 기준."""
import json
import math
import os

from svgkit import C, L, P, Rc, T, box, dim_h, dim_v, net, pico, wire

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ARMS_JSON = os.path.join(ROOT, "engine", "data", "cross_arms.json")

B = 900
R0, R1 = 375, 525            # 도로 띠(폭 150)
MID = 450
JOIN_Y = 600                 # 우드락 이음선(900×600 + 900×300)
STREAM = (660, 740)          # 하천(남북)
DECK_X = (610, 790)          # 교량 상판(보도 포함 y 355~545)
DECK_Y = (355, 545)
STRIPS = [(20, 100), (560, 640), (800, 880)]     # 밑면 받침 가로대(전체 폭)
BUILDINGS = [(40, 240, 100, 125), (250, 240, 100, 125), (40, 535, 100, 125), (250, 535, 100, 125)]
UNITS = {  # 살포기 상자(56×56), 미끄럼판 시작→끝
    "N": ((535, 150), (535, 178), (505, 178)),
    "E": ((600, 292), (628, 348), (628, 392)),
    "S": ((309, 692), (365, 720), (395, 720)),
    "W": ((162, 537), (190, 537), (190, 507)),
}
OBS = (650, 575, 110, 62)    # 교량 관측부(물받이)
LEVEL_COLOR = {"risk1": "#22c55e", "risk2": "#f59e0b", "risk3": "#ef4444", "plan": "#3b82f6", "done": "#e5e7eb", "off": "#9ca3af"}


def arms_info():
    try:
        return json.load(open(ARMS_JSON, encoding="utf-8"))["arms"]
    except Exception:  # noqa: BLE001
        return {k: {"name": k} for k in "NESW"}


def _roads(o, asphalt="#4b5563"):
    o.append(Rc(R0, 0, R1 - R0, B, fill=asphalt))
    o.append(Rc(0, R0, B, R1 - R0, fill=asphalt))
    for a, b in ((0, 330), (570, B)):
        o.append(L(MID, a, MID, b, "#f2c230", 4, "22 16"))
        o.append(L(a, MID, b, MID, "#f2c230", 4, "22 16"))
    for k in range(7):  # 횡단보도
        x = R0 + 8 + k * 20
        o.append(Rc(x, 333, 10, 36, fill="#f8fafc"))
        o.append(Rc(x, 531, 10, 36, fill="#f8fafc"))
        y = R0 + 8 + k * 20
        o.append(Rc(333, y, 36, 10, fill="#f8fafc"))
        o.append(Rc(531, y, 36, 10, fill="#f8fafc"))


def svg_plan(levels=None, order=None, for_cover=False):
    """평면도. levels={'N':'risk3',...}, order=['E','W'](승인 순서)를 주면 LED 색·순번을 그린다."""
    arms = arms_info()
    o = ['<svg viewBox="%s" class="dwg">' % ("-40 -60 1190 1000" if for_cover else "-190 -200 1340 1290")]
    o.append(Rc(8, 10, B, B, fill="#d6cfbf", rx=8))
    o.append(Rc(0, 0, B, B, fill="#eef0f2", stroke="#9b9384", sw=2, rx=8))
    # 하천
    o.append(Rc(STREAM[0], 0, STREAM[1] - STREAM[0], B, fill="#bfdbfe"))
    o.append(Rc(STREAM[0], 0, STREAM[1] - STREAM[0], B, fill="url(#waves)", extra='opacity="0.6"'))
    _roads(o)
    # 교량 상판(은박) + 난간
    o.append(Rc(DECK_X[0], DECK_Y[0], DECK_X[1] - DECK_X[0], DECK_Y[1] - DECK_Y[0], fill="#a8b1bb", stroke="#64748b", sw=2))
    o.append(Rc(DECK_X[0], R0, DECK_X[1] - DECK_X[0], R1 - R0, fill="#6b7280"))
    o.append(L(DECK_X[0], MID, DECK_X[1], MID, "#f2c230", 4, "22 16"))
    o.append(L(DECK_X[0], DECK_Y[0] + 3, DECK_X[1], DECK_Y[0] + 3, "#e2e8f0", 5))
    o.append(L(DECK_X[0], DECK_Y[1] - 3, DECK_X[1], DECK_Y[1] - 3, "#e2e8f0", 5))
    # 건물과 그림자(남서 건물이 W 갈래 남쪽 차로에 그늘)
    for (x, y, w, h) in BUILDINGS[2:]:
        o.append('<polygon points="%d,%d %d,%d %d,%d %d,%d" fill="rgba(15,23,42,0.28)"/>' % (
            x, y, x + w, y, x + w - 10, 405, x - 10, 405))
    for (x, y, w, h) in BUILDINGS:
        o.append(Rc(x, y, w, h, fill="#cbd5e1", stroke="#64748b", sw=2, rx=3))
        o.append(Rc(x + 8, y + 8, w - 16, h - 16, fill="#e2e8f0"))
    # 이음선·받침(밑면)
    if not for_cover:
        for a, b in STRIPS:
            o.append(Rc(0, a, B, b - a, fill="none", stroke="#a16207", sw=2, dash="10 8"))
        o.append(L(-20, JOIN_Y, B + 20, JOIN_Y, "#475569", 2, "14 8"))
    # 살포기 + LED
    levels = levels or {}
    for k, ((ux, uy), (cx1, cy1), (cx2, cy2)) in UNITS.items():
        o.append(L(cx1, cy1, cx2, cy2, "#a16207", 9))
        o.append(Rc(ux, uy, 56, 56, fill="#fb923c", stroke="#9a3412", sw=2.5, rx=5))
        col = LEVEL_COLOR.get(levels.get(k, "off"), "#9ca3af")
        o.append(C(ux + 28, uy + 28, 14, fill=col, stroke="#111827", sw=2, extra='filter="url(#glow)"' if levels else ""))
        ly = uy + 56 + 34 if k == "W" else uy - 8
        o.append(T(ux + 28, ly, "살포기 " + k, 17, weight=800, fill="#7c2d12"))
    # 교량 관측부
    x, y, w, h = OBS
    o.append(Rc(x, y, w, h, fill="#e0f2fe", stroke="#0284c7", sw=2.5, rx=4))
    o.append(Rc(x + 8, y + 10, 52, 40, fill="#e5e7eb", stroke="#374151", sw=2))
    o.append(Rc(x + 18, y + 24, 30, 10, fill="#111", rx=5))
    o.append(Rc(x + 68, y + 10, 34, 40, fill="#15803d"))
    o.append(C(x - 14, y + 20, 11, fill="#f59e0b", stroke="#78350f", sw=2))
    # 갈래 이름(도로 위)
    nm = lambda k: "%s · %s" % (k, arms.get(k, {}).get("name", k))
    o.append(T(MID + 6, 200, nm("N"), 21, weight=800, fill="#f8fafc", extra='transform="rotate(-90 %d 200)"' % (MID + 6)))
    o.append(T(MID + 6, 720, nm("S"), 21, weight=800, fill="#f8fafc", extra='transform="rotate(-90 %d 720)"' % (MID + 6)))
    o.append(T(190, MID + 8, nm("W") + "(그늘)", 21, weight=800, fill="#f8fafc"))
    o.append(T(845, MID - 12, "E", 21, weight=800, fill="#f8fafc"))
    o.append(T(845, MID + 26, arms.get("E", {}).get("name", "E"), 17, weight=800, fill="#f8fafc"))
    o.append(T(DECK_X[1] - 45, DECK_Y[0] - 10, "교량(은박)", 18, weight=800, fill="#334155"))
    o.append(T(STREAM[0] + 40, 30, "하천", 18, weight=800, fill="#1d4ed8"))
    # 승인 순서
    if order:
        for i, k in enumerate(order):
            (ux, uy), _, _ = UNITS[k]
            o.append(C(ux + 56, uy + 56, 16, fill="#2563eb", stroke="#fff", sw=3))
            o.append(T(ux + 56, uy + 63, str(i + 1), 18, weight=800, fill="#fff"))
    # 북쪽 표시
    nx, ny = (1100, 900) if for_cover else (-120, -60)
    o.append(L(nx, ny, nx, ny - 70, "#111", 4, extra='marker-end="url(#arrE)"'))
    o.append(T(nx, ny - 80, "북", 20, weight=800))
    if not for_cover:
        o.append(dim_h(0, B, -170, "900 (900×600 + 900×300 이어 붙임)", ext_from=0))
        for a, b in ((0, R0), (R0, R1), (R1, B)):
            o.append(dim_h(a, b, -110, "%d" % (b - a), ext_from=0, size=18))
        o.append(dim_v(0, B, -160, "900", ext_from=0))
        for a, b in ((0, R0), (R0, R1), (R1, B)):
            o.append(dim_v(a, b, -95, "%d" % (b - a), ext_from=0, size=18))
        o.append(dim_h(DECK_X[0], DECK_X[1], B + 60, "교량 상판 180 (x 610~790)", ext_from=B, size=16))
        o.append(dim_h(STREAM[0], STREAM[1], B + 110, "하천 80", ext_from=B, size=16))
        o.append(T(-20, JOIN_Y - 8, "이음선 y=600", 15, "end", 700, "#475569"))
        o.append(T(-150, B + 165, "점선 갈색 = 밑면 받침 가로대(900×80, 2겹=10mm) · 주황 상자 = 서보 살포기(56×56) + 위 LED · 갈색 굵은 선 = 미끄럼판 · 하늘색 = 교량 관측부(시험편·DS18B20·젖음센서) · 주황 원 = 교량 주의 LED",
                   16, "start", 600, "#334155"))
    # 전자부(보드 옆)
    o.append(Rc(950, 250, 180, 280, fill="#f8fafc", stroke="#64748b", sw=2, dash="8 6", rx=10))
    o.append(Rc(970, 290, 140, 52, fill="#166534", rx=4))
    o.append(T(1040, 323, "Pico 2 W", 18, weight=800, fill="#fff"))
    o.append(Rc(970, 352, 140, 48, fill="#fff", stroke="#cbd5e1", sw=2))
    o.append(T(1040, 382, "브레드보드", 15, weight=700))
    o.append(Rc(970, 410, 140, 44, fill="#fde68a", stroke="#b45309", sw=2, rx=6))
    o.append(T(1040, 438, "서보 5V 전원", 15, weight=800, fill="#92400e"))
    o.append(T(1040, 480, "USB → 맥북", 16, weight=800, fill="#1d4ed8"))
    o.append(T(1040, 505, "(ICE-ZERO 엔진)", 14, weight=700, fill="#1d4ed8"))
    o.append(T(1040, 240, "보드 옆 책상", 16, weight=800, fill="#334155"))
    for k, ((ux, uy), _, _) in UNITS.items():
        o.append(P("M 950 %d C 900 %d, %d %d, %d %d" % (330, 330, ux + 80, uy + 28, ux + 56, uy + 28), stroke="#64748b", sw=2.5,
                   extra='stroke-dasharray="8 7" opacity="0.8"'))
    o.append(P("M 950 420 C 880 420, 800 600, %d %d" % (OBS[0] + OBS[2], OBS[1] + 30), stroke="#0284c7", sw=2.5,
               extra='stroke-dasharray="8 7" opacity="0.8"'))
    o.append('</svg>')
    return "".join(o)


def svg_unit_detail():
    """살포기 상세(3배 확대 그림, 치수는 실제 mm). 다리 높이 35mm 아래에 서보와 미끄럼판이 들어간다."""
    s = 3.0
    o = ['<svg viewBox="0 0 1500 600" class="dwg">']
    o.append(T(20, 34, "(a) 옆에서 본 모습(앞벽 = 도로 쪽)", 22, "start", 800))
    ox, top, ground = 170, 70, 385
    plate = ground - 35 * s
    o.append(Rc(40, ground, 300, 14, fill="#f5f5f4", stroke="#111", sw=1.5))
    o.append(Rc(340, ground, 260, 14, fill="#4b5563"))
    o.append(T(470, ground + 40, "도로(갈래 차로)", 15, weight=700, fill="#334155"))
    o.append(Rc(ox, top, 56 * s, ground - top, fill="#fed7aa", stroke="#111", sw=2.5))
    o.append(Rc(ox + 4, plate + 12, 56 * s - 8, ground - plate - 12, fill="#fff7ed"))
    o.append(Rc(ox + 56 * s - 4, plate + 36, 8, ground - plate - 36, fill="#fff7ed"))
    o.append(T(ox + 28 * s, 170, "알갱이 칸", 20, weight=800))
    o.append(T(ox + 28 * s, 196, "56×56×70", 17, weight=700))
    o.append(Rc(ox, plate, 56 * s, 12, fill="#fdba74", stroke="#111", sw=2))
    o.append(Rc(ox + 62, plate, 36, 12, fill="#fff", stroke="#111", sw=1.5))
    o.append(Rc(ox + 6, plate + 22, 62, 34, fill="#2563eb", stroke="#111", sw=1.5))
    o.append(T(ox + 37, plate + 45, "SG90", 14, weight=800, fill="#fff"))
    o.append(Rc(ox + 52, plate + 14, 70, 8, fill="#fb923c", stroke="#111", sw=1.5))
    o.append(P("M %d %d L %d %d" % (ox + 82, plate + 30, ox + 270, ground - 4), stroke="#a16207", sw=9))
    o.append(C(ox + 56 * s - 2, top + 14, 12, fill="#ef4444", stroke="#111", sw=2))
    o.append(T(ox + 56 * s + 18, top + 20, "LED(앞벽 윗부분)", 15, "start", 700))
    o.append(T(ox + 56 * s + 60, plate - 20, "앞벽 아래 구멍 40×30", 14, "start", 700, "#a16207"))
    o.append(T(ox + 56 * s + 60, plate + 2, "미끄럼판 40×80, 약 25°", 14, "start", 700, "#a16207"))
    o.append(dim_v(top, ground, 130, "105", ext_from=ox, size=16))
    o.append(dim_v(plate, ground, 100, "35", size=16))
    o.append(T(20, 470, "덮개(20×35)를 서보 혼에 붙여 바닥 구멍 12×30 바로 아래에서 돌린다.", 15, "start", 700))
    o.append(T(20, 494, "닫힘 0°이면 구멍을 막고, 열림 60°이면 알갱이가 미끄럼판으로 떨어진다.", 15, "start", 700))
    o.append(T(640, 34, "(b) 바닥판(위에서)", 22, "start", 800))
    bx, byy = 660, 70
    o.append(Rc(bx, byy, 56 * s, 56 * s, fill="#fdba74", stroke="#111", sw=2.5))
    o.append(Rc(bx + 28 * s - 18, byy + 39, 36, 90, fill="#fff", stroke="#111", sw=2))
    o.append(Rc(bx + 10, byy + 116, 62, 34, fill="none", stroke="#2563eb", sw=2, dash="6 4"))
    o.append(T(bx + 28 * s, byy + 26, "56×56", 17, weight=800))
    o.append(T(bx + 28 * s + 30, byy + 90, "구멍", 14, "start", 800))
    o.append(T(bx + 28 * s + 30, byy + 108, "12×30", 14, "start", 800))
    o.append(T(bx + 41, byy + 166, "서보 자리(아래)", 12, weight=700, fill="#2563eb"))
    o.append(T(bx, byy + 56 * s + 34, "벽 4장 안쪽, 바닥에서 35mm 높이에 붙인다", 14, "start", 700, "#334155"))
    notes = [
        ("한 번 열림 = 1회분: SPRAY_MS 600ms 동안 열고 닫는다", "#111"),
        ("각도는 config SERVO_OPEN_DEG·SERVO_CLOSED_DEG로 맞춘다", "#1d4ed8"),
        ("펌웨어가 서보를 한 번에 하나만 움직인다(전원 부담)", "#111"),
        ("내용물: 마른 쌀알·스티로폼 알갱이. 실제 제설제 금지", "#b91c1c"),
        ("서보 선·LED 선은 상자 뒤 Ø8 구멍 → 보드 밑 통로", "#111"),
        ("같은 상자 4개(N·E·S·W). 위치는 도면 1의 주황 상자", "#111"),
    ]
    for i, (line, col) in enumerate(notes):
        o.append(T(900, 80 + i * 34, "· " + line, 16, "start", 700, col))
    o.append(T(900, 330, "부재(한 대분)", 18, "start", 800))
    parts = ["벽 56×105 ×4(앞벽 아래에 40×30 구멍)", "바닥판 56×56 ×1", "덮개 20×35 ×1(서보 혼에 붙임)", "미끄럼판 40×80 ×1", "SG90 ×1, 혼 1개, LED 1개"]
    for i, line in enumerate(parts):
        o.append(T(900, 362 + i * 28, "· " + line, 15, "start", 600, "#334155"))
    o.append('</svg>')
    return "".join(o)


def svg_bridge_obs():
    """교량 관측부 단면(축척 없음). 라벨은 지시선으로 분리한다."""
    o = ['<svg viewBox="0 0 1500 430" class="dwg">']
    lead = lambda x1, y1, x2, y2, col="#334155": L(x1, y1, x2, y2, col, 1.4)
    o.append(Rc(40, 300, 1100, 16, fill="#f5f5f4", stroke="#111", sw=2))
    o.append(T(50, 340, "보드 윗면(E 갈래 남쪽, 교량 상판 바로 아래)", 15, "start", 700, "#475569"))
    o.append(Rc(300, 258, 440, 42, fill="#f0f9ff", stroke="#0ea5e9", sw=3))
    o.append(Rc(330, 282, 200, 16, fill="none", stroke="#7c3aed", sw=2, dash="6 4"))
    o.append(Rc(330, 270, 200, 12, fill="#d1d5db", stroke="#111", sw=2))
    o.append(Rc(390, 254, 80, 16, fill="#111", rx=7))
    o.append(Rc(570, 276, 130, 9, fill="#15803d"))
    o.append(P("M 470 262 C 560 262, 700 250, 740 262 L 760 262 L 760 330 L 1180 330", stroke="#111", sw=2.5))
    o.append(P("M 700 280 L 752 280 L 752 330", stroke="#0284c7", sw=2.5))
    o.append(Rc(748, 296, 18, 22, fill="#fff", stroke="#b91c1c", sw=2))
    o.append(T(1180, 356, "보드 밑 통로 → 보드 옆 Pico #1 (GP4·GP26)", 15, "end", 700, "#1d4ed8"))
    o.append(T(778, 312, "Ø8 구멍", 13, "start", 700, "#b91c1c"))
    o.append(T(330, 228, "① 금속 시험편(알루미늄 52×40 이상)", 15, "start", 800))
    o.append(lead(350, 233, 350, 270))
    o.append(T(330, 178, "② DS18B20 방수 프로브(알루미늄 테이프로 밀착)", 15, "start", 800))
    o.append(lead(430, 183, 430, 254))
    o.append(T(570, 128, "③ 젖음센서 기판(빗물·수위 모듈)", 15, "start", 800))
    o.append(lead(635, 133, 635, 276))
    o.append(T(748, 252, "물받이(얕은 플라스틱 뚜껑)", 15, "start", 700, "#0369a1"))
    o.append(T(50, 250, "선택: 밀폐 냉각팩", 15, "start", 700, "#7c3aed"))
    o.append(T(50, 270, "(시험편 아래) → 현장 보정 시연", 15, "start", 700, "#7c3aed"))
    o.append(lead(270, 266, 330, 290, "#7c3aed"))
    o.append(Rc(1003, 220, 14, 80, fill="#e7e5e4", stroke="#111", sw=1.5))
    o.append(C(1010, 210, 12, fill="#f59e0b", stroke="#78350f", sw=2))
    o.append(T(1010, 160, "④ 교량 주의 LED", 15, weight=800))
    o.append(T(1010, 182, "(GP15, 맥북 없이 로컬)", 13, weight=700, fill="#475569"))
    o.append(T(50, 410, "시험편 온도는 맥북 엔진의 E(교량) 갈래 '현장 보정'에 쓴다(센서값 − 모델 유효온도를 모든 시점에 더함). 결빙 확정에는 쓰지 않는다.",
               16, "start", 700, "#b45309"))
    o.append('</svg>')
    return "".join(o)


def svg_cut():
    o = ['<svg viewBox="-40 -60 1960 760" class="dwg">']

    def board(ox, title, parts):
        s = [T(ox, -20, title, 22, "start", 800), Rc(ox, 0, 900, 600, fill="#fffdf7", stroke="#111", sw=3)]
        for x, y, w, h, label, col in parts:
            s.append(Rc(ox + x, y, w, h, fill=col, stroke="#334155", sw=1.5))
            if label:
                size = 16 if w >= 90 and h >= 30 else 12
                s.append(T(ox + x + w / 2, y + h / 2 + 5, label, size, weight=700))
        return "".join(s)
    p2 = [(0, 0, 900, 300, "바닥 남쪽 조각 900×300", "#e2e8f0")]
    for i in range(3):
        p2.append((0, 300 + i * 80, 900, 80, "받침 가로대 900×80 (%d)" % (i + 1), "#fde68a"))
    p2.append((0, 542, 180, 15, "난간", "#e2e8f0"))
    p2.append((200, 542, 180, 15, "난간", "#e2e8f0"))
    p2.append((400, 542, 500, 58, "남는 조각", "#f5f5f4"))
    o.append(board(0, "우드락 2번(900×600)", p2))
    p3 = []
    for i in range(3):
        p3.append((0, i * 80, 900, 80, "받침 가로대 900×80 (%d, 2겹째)" % (i + 4), "#fde68a"))
    for i in range(4):
        p3.append((i * 100, 245, 100, 120, "건물 앞 %d" % (i + 1), "#cbd5e1"))
        p3.append((400 + i * 125, 245, 125, 120, "건물 옆 %d" % (i + 1), "#cbd5e1"))
    for i in range(4):
        p3.append((i * 100, 370, 100, 125, "지붕 %d" % (i + 1), "#e2e8f0"))
    for row in range(2):
        for i in range(8):
            p3.append((405 + i * 58, 370 + row * 108, 56, 105, "벽", "#fed7aa"))
    for i in range(4):
        p3.append((i * 58, 500, 56, 56, "바닥", "#fdba74"))
        p3.append((236 + i * 42, 500, 40, 80, "판", "#fcd34d"))
        p3.append((i * 24, 562, 20, 35, "", "#fdba74"))
    o.append(board(1000, "우드락 3번(900×600)", p3))
    o.append(T(1100, 590, "← 덮개 20×35 ×4", 13, "start", 700))
    o.append(T(0, 670, "1번 우드락(900×600)은 통째로 바닥 북쪽 조각이 된다. 배치는 예시이고 치수는 부재표가 기준이다. 건물은 앞·옆 벽과 지붕으로 만든 L자 상자(높이 120, 뒤는 열림)다.",
               17, "start", 600, "#334155"))
    o.append('</svg>')
    return "".join(o)


def svg_wiring():
    used = {6: "#0f766e", 20: "#f59e0b", 21: "#2563eb", 22: "#a855f7", 24: "#dc2626", 25: "#ea580c", 26: "#16a34a", 27: "#7c3aed",
            31: "#0284c7", 36: "#ea580c", 38: "#111", 40: "#dc2626"}
    o = ['<svg viewBox="0 0 1500 800" class="dwg">']
    ps, pp = pico(620, 120, used, "Pico #1 (Pico 2 W)")
    o.append(ps)
    s1, ds = box(140, 60, 230, 190, "DS18B20 ×2(병렬)", ["VDD", "DQ", "GND"])
    o.append(s1)
    o.append(wire(ds["DQ"], pp[6], "#0f766e", "DQ→GP4", via=480))
    o.append(Rc(392, 105, 60, 16, fill="#ecfeff", stroke="#0f766e", sw=1.5))
    o.append(T(422, 117, "4.7kΩ", 11, weight=800))
    o.append(T(255, 280, "4.7kΩ 풀업: DQ ↔ 3V3(필수)", 14, "middle", 800, "#0f766e"))
    o.append(net(ds["VDD"], "3V3", "#ea580c", "left"))
    o.append(net(ds["GND"], "GND", "#111", "left"))
    s2, wl = box(140, 330, 230, 150, "교량 주의 LED", ["+(220Ω)", "−"])
    o.append(s2)
    o.append(wire(wl["+(220Ω)"], pp[20], "#f59e0b", "GP15", via=500))
    o.append(net(wl["−"], "GND", "#111", "left"))
    s5, sp = box(140, 520, 230, 150, "서보 전용 5V 전원", ["+5V", "GND"])
    o.append(s5)
    o.append(net(sp["+5V"], "서보5V", "#b45309", "right"))
    o.append(net(sp["GND"], "GND", "#111", "right"))
    o.append(T(255, 700, "+5V–GND 사이에 470~1000µF. GND는 Pico와 공통", 13, "middle", 700, "#92400e"))
    o.append(T(255, 722, "보조배터리 USB 단자 또는 AA 니켈수소 4개", 13, "middle", 700, "#92400e"))
    s3, np_ = box(1080, 40, 250, 150, "WS2812 LED ×4 (N→E→S→W)", ["DIN(330Ω)", "5V", "GND"], side="left")
    o.append(s3)
    o.append(wire(pp[21], np_["DIN(330Ω)"], "#2563eb", "GP16", via=960))
    o.append(net(np_["5V"], "5V", "#dc2626", "right"))
    o.append(net(np_["GND"], "GND", "#111", "right"))
    s4, bz = box(1080, 210, 250, 90, "부저(선택)", ["+", "−"], side="left")
    o.append(s4)
    o.append(wire(pp[22], bz["+"], "#a855f7", "GP17", via=985))
    o.append(net(bz["−"], "GND", "#111", "right"))
    s6, sv = box(1080, 320, 250, 250, "서보 살포기 SG90 ×4", ["N 신호", "E 신호", "S 신호", "W 신호", "+ (5V 전용)", "− (GND)"], side="left")
    o.append(s6)
    for name, pin, col in (("N 신호", 24, "#dc2626"), ("E 신호", 25, "#ea580c"), ("S 신호", 26, "#16a34a"), ("W 신호", 27, "#7c3aed")):
        o.append(wire(pp[pin], sv[name], col, None, via=900 + (pin - 24) * 22))
    o.append(net(sv["+ (5V 전용)"], "서보5V", "#b45309", "right"))
    o.append(net(sv["− (GND)"], "GND", "#111", "right"))
    s7, ws = box(1080, 600, 250, 150, "젖음센서 모듈", ["AO", "VCC", "GND"], side="left")
    o.append(s7)
    o.append(wire(pp[31], ws["AO"], "#0284c7", "GP26(ADC0)", via=1010))
    o.append(net(ws["VCC"], "3V3", "#ea580c", "right"))
    o.append(net(ws["GND"], "GND", "#111", "right"))
    o.append(net(pp[40], "5V", "#dc2626", "right"))
    o.append(net(pp[36], "3V3", "#ea580c", "right"))
    o.append(net(pp[38], "GND", "#111", "right"))
    o.append(T(735, 60, "맥북 USB → Pico 전원 + 시리얼(@@TEL·@@EVT ↑ / @@LED·@@SPRAY·@@STOP ↓)", 14, weight=800, fill="#334155"))
    o.append(T(20, 790, "서보 4개를 Pico VBUS에서 바로 먹이지 않는다(맥북 USB 전류 부족 → 재부팅). 단색 LED를 쓸 때: LED_MODE='gpio', N=GP6·E=GP7·S=GP8·W=GP9 (각 220Ω).",
               14, "start", 700, "#b45309"))
    o.append('</svg>')
    return "".join(o)


def svg_system():
    """시스템 구성(반 쪽 폭에서도 읽히도록 좁은 viewBox·큰 글자)."""
    o = ['<svg viewBox="0 0 1000 640" class="dwg">']

    def b(x, y, w, h, title, sub, fill):
        s = Rc(x, y, w, h, fill=fill, stroke="#334155", sw=2.5, rx=14) + T(x + w / 2, y + 38, title, 26, weight=800)
        for k, line in enumerate(sub):
            s += T(x + w / 2, y + 74 + k * 30, line, 20, weight=600, fill="#334155")
        return s
    o.append(b(10, 10, 640, 260, "맥북: ICE-ZERO 엔진 + 서버", ["XGBoost 지면온도 예보(+0/1/3/6h)", "isotonic 동결확률 · 갈래 유효온도",
                                                     "risk_v2 우선순위 · 예산 내 선정·순서", "대시보드 · 승인 · 겨울밤 재생",
                                                     "실제 강남 교차로(노드 1220041600)"], "#eef5ff"))
    o.append(b(700, 40, 290, 200, "Command Code", ["제보 → {갈래, 예산}", "모호하면 되묻기", "기기 조종 안 함"], "#f5f0ff"))
    o.append(b(10, 380, 470, 250, "Pico #1 (USB)", ["갈래 LED 4", "서보 살포기 4(순서대로)", "교량 온도·젖음 → 현장 보정", "교량 주의 LED(로컬)"], "#ecfdf3"))
    o.append(b(530, 380, 460, 250, "사람(담당자)", ["① 제보 해석 확인", "② 계획 승인", "③ 출동 승인", "언제든 비상 정지"], "#fef9c3"))
    o.append(L(650, 140, 698, 140, "#7c3aed", 3, extra='marker-end="url(#flow)"'))
    o.append(L(200, 272, 200, 378, "#166534", 3.5, extra='marker-end="url(#flow)"'))
    o.append(L(270, 378, 270, 274, "#166534", 3.5, extra='marker-end="url(#flow)"'))
    o.append(T(190, 318, "@@LED·@@SPRAY", 18, "end", 800, "#166534"))
    o.append(T(282, 342, "@@TEL·@@EVT", 18, "start", 800, "#166534"))
    o.append(L(760, 378, 600, 274, "#a16207", 3.5, extra='marker-end="url(#flow)"'))
    o.append(T(700, 318, "승인 버튼", 18, "start", 800, "#a16207"))
    o.append('</svg>')
    return "".join(o)


def svg_pipeline():
    steps = [
        ("ASOS 겨울 자료", ["2020~2025 시간별", "기온·습도·바람", "강수·적설·지면온도"], "#f1f5f9"),
        ("피처(v10)", ["지면온도 시차 1·2·3·6h", "6h 평균·3h 추세", "이슬점차·시각 주기"], "#f1f5f9"),
        ("XGBoost ×4", ["+0/+1/+3/+6h 예보", "≤2024 학습", "2025 시험"], "#eef5ff"),
        ("isotonic 보정", ["예측 지면온도 →", "동결확률(≤0°C)", "2024로 맞춤"], "#eef5ff"),
        ("갈래 유효온도", ["교량 −2.5°C(가정)", "또는 현장 센서로", "차이만큼 보정"], "#ecfdf3"),
        ("후보·우선순위", ["동결확률 ≥0.5", "또는 확인된 제보", "ICE-ZERO risk_v2"], "#fff4e5"),
        ("선정·순서", ["예산 n개", "우선순위 순서", "→ 사람 승인"], "#fff4e5"),
        ("Pico 실행", ["LED 표시", "서보 살포기", "순서대로"], "#ecfdf3"),
    ]
    o = ['<svg viewBox="0 0 1500 210" class="dwg">']
    w, gap = 162, 25
    for i, (t, sub, col) in enumerate(steps):
        x = 10 + i * (w + gap)
        o.append(Rc(x, 20, w, 170, fill=col, stroke="#334155", sw=2, rx=10))
        o.append(T(x + w / 2, 52, t, 17, weight=800))
        for k, s in enumerate(sub):
            o.append(T(x + w / 2, 86 + k * 26, s, 13.5, weight=600, fill="#334155"))
        if i < len(steps) - 1:
            o.append(L(x + w + 2, 105, x + w + gap - 2, 105, "#334155", 3, extra='marker-end="url(#flow)"'))
    o.append('</svg>')
    return "".join(o)


def svg_night(rows, title=""):
    """겨울밤 재생 그래프. rows=[{'label':'18시','obs':float|None,'h3':float|None,'pmax':{'N':..},'recommend':bool}, ...]"""
    o = ['<svg viewBox="0 0 1500 545" class="dwg">']
    if not rows:
        o.append(T(750, 260, "엔진 결과 없음", 24, weight=800))
        o.append('</svg>')
        return "".join(o)
    x0, x1, y0, y1 = 110, 1460, 50, 300
    vals = [v for r in rows for v in (r.get("obs"), r.get("h3")) if v is not None]
    lo, hi = min(vals + [-1.0]) - 0.5, max(vals + [1.0]) + 0.5
    n = len(rows)
    X = lambda i: x0 + (x1 - x0) * i / max(1, n - 1)
    Y = lambda v: y1 - (y1 - y0) * (v - lo) / (hi - lo)
    o.append(Rc(x0, y0, x1 - x0, y1 - y0, fill="#f8fafc", stroke="#cbd5e1", sw=1.5))
    o.append(L(x0, Y(0), x1, Y(0), "#ef4444", 2, "8 6"))
    o.append(T(x0 - 8, Y(0) + 5, "0°C", 15, "end", 800, "#ef4444"))
    for v in range(int(math.ceil(lo)), int(math.floor(hi)) + 1, 2):
        o.append(T(x0 - 8, Y(v) + 5, "%d" % v, 13, "end", 600, "#64748b"))
    for key, col, lab in (("obs", "#0f172a", "관측 지면온도"), ("h3", "#2563eb", "+3h 예보(그 시각에 대한)")):
        pts = [(X(i), Y(r[key])) for i, r in enumerate(rows) if r.get(key) is not None]
        if pts:
            o.append(P("M " + " L ".join("%.1f %.1f" % p for p in pts), stroke=col, sw=4))
    o.append(L(x0 + 10, 30, x0 + 50, 30, "#0f172a", 4))
    o.append(T(x0 + 58, 36, "관측 지면온도", 15, "start", 700))
    o.append(L(x0 + 230, 30, x0 + 270, 30, "#2563eb", 4))
    o.append(T(x0 + 278, 36, "+3h 예보(해당 시각 값)", 15, "start", 700, "#2563eb"))
    if title:
        o.append(T(x1, 36, title, 16, "end", 800, "#334155"))
    first = None
    for i, r in enumerate(rows):
        o.append(T(X(i), y1 + 22, r.get("label", ""), 12, weight=600, fill="#475569"))
        if r.get("recommend") and first is None:
            first = i
    if first is not None:
        o.append(L(X(first), y0, X(first), y1, "#16a34a", 3, "6 5"))
        o.append(T(X(first) + 6, y0 + 18, "첫 출동 권고", 15, "start", 800, "#15803d"))
    # 갈래별 p_max 띠
    ty = 350
    for k_i, k in enumerate("NESW"):
        yy = ty + k_i * 38
        o.append(T(x0 - 8, yy + 20, k, 16, "end", 800))
        for i, r in enumerate(rows):
            p = (r.get("pmax") or {}).get(k)
            if p is None:
                continue
            col = "#22c55e" if p < 0.3 else "#f59e0b" if p < 0.6 else "#ef4444"
            wcell = (x1 - x0) / max(1, n - 1)
            o.append(Rc(X(i) - wcell / 2 + 1, yy, wcell - 2, 28, fill=col, extra='opacity="%.2f"' % (0.35 + 0.65 * p)))
            if r.get("selected") and k in r["selected"]:
                o.append(C(X(i), yy + 14, 6, fill="#1d4ed8", stroke="#fff", sw=1.5))
    o.append(T(x0, ty + 4 * 38 + 22, "칸 색 = 갈래별 최대 예측 동결확률(+1/+3/+6h, 초록<0.3≤노랑<0.6≤빨강) · 파란 점 = 그 시각 선정 갈래", 14, "start", 700, "#475569"))
    o.append('</svg>')
    return "".join(o)
