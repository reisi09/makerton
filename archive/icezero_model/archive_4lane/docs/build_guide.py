#!/usr/bin/env python3
"""ICE-ZERO 4차로 모형 구현 가이드 PDF 생성기.

    python3 icezero_model/docs/build_guide.py          # guide.html + PDF 생성(Chrome headless)

도면 좌표는 CONTRACT.md 3절과 같은 상수에서 계산한다(단위 mm, 원점 = 보드 왼쪽 위, x→동쪽, y→아래).
"""
import html
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # icezero_model/
OUT_HTML = os.path.join(HERE, "guide.html")
OUT_PDF = os.path.join(HERE, "ICE-ZERO_4차로_구현가이드.pdf")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
COVER_IMG = os.path.join(os.path.dirname(ROOT), "visual", "ICE-ZERO_우드락_시각화.png")
EVAL_JSON = os.path.join(ROOT, "tests", "eval_result.json")
DASH_IMG = os.path.join(HERE, "dashboard.png")      # 서버 --no-llm 기동 화면(캡처 스크립트가 만든다)
HAS_HWTEST = os.path.exists(os.path.join(ROOT, "pico_car", "hwtest.py"))
HAS_DIAG = "DIAG" in open(os.path.join(ROOT, "pico_car", "config.py"), encoding="utf-8").read() \
    if os.path.exists(os.path.join(ROOT, "pico_car", "config.py")) else False

# ---------------- 기하(CONTRACT 3절) ----------------
BW, BH = 1800, 600
LANE = 150
SX0, SX1 = 330, 1470
SEG_X = [330, 615, 900, 1185, 1470]
GY_TOP, GY_BOT = 110, 490
R = 190
CXW, CXE, CYC = 330, 1470, 300
TAPE, BAR_L = 19, 70
END_BOT = [345, 394, 1406, 1455]          # 아래(상행) 차로 END 막대 중심 x
END_TOP = [1455, 1406, 394, 345]          # 위(하행) 차로, 진행 순서
SEG_BARS = [615, 900, 1185]
HOME_DEG = [155, 140, 125]
POSTS_X = [472.5, 757.5, 1042.5, 1327.5]   # 칸 LED 기둥(구간 중앙)
STRIPS_X = [(250, 350), (850, 950), (1450, 1550)]  # 밑면 받침 가로대
LOOP = ["U1", "U2", "U3", "U4", "D4", "D3", "D2", "D1"]


def home_pts():
    out = []
    for d in HOME_DEG:
        a = math.radians(d)
        out.append((d, CXW + R * math.cos(a), CYC + R * math.sin(a)))
    return out


LAP_MM = 2 * (SX1 - SX0) + 2 * math.pi * R

# ---------------- SVG 도우미 ----------------


def esc(s):
    return html.escape(str(s))


def L(x1, y1, x2, y2, stroke="#111", sw=2, dash=None, extra=""):
    d = ' stroke-dasharray="%s"' % dash if dash else ""
    return '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%s"%s %s/>' % (
        x1, y1, x2, y2, stroke, sw, d, extra)


def Rc(x, y, w, h, fill="none", stroke="none", sw=0, rx=0, dash=None, extra=""):
    d = ' stroke-dasharray="%s"' % dash if dash else ""
    return '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%s" fill="%s" stroke="%s" stroke-width="%s"%s %s/>' % (
        x, y, w, h, rx, fill, stroke, sw, d, extra)


def T(x, y, s, size=20, anchor="middle", weight=600, fill="#111", extra=""):
    return '<text x="%.1f" y="%.1f" font-size="%s" text-anchor="%s" font-weight="%s" fill="%s" %s>%s</text>' % (
        x, y, size, anchor, weight, fill, extra, esc(s))


def C(cx, cy, r, fill="none", stroke="#111", sw=2, extra=""):
    return '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" stroke-width="%s" %s/>' % (
        cx, cy, r, fill, stroke, sw, extra)


def dim_h(x1, x2, y, label, ext_from=None, size=20, color="#1d4ed8"):
    o = []
    if ext_from is not None:
        o.append(L(x1, ext_from, x1, y + (6 if y > ext_from else -6), color, 1.2))
        o.append(L(x2, ext_from, x2, y + (6 if y > ext_from else -6), color, 1.2))
    o.append(L(x1, y, x2, y, color, 1.6, extra='marker-start="url(#arrS)" marker-end="url(#arrE)"'))
    o.append(T((x1 + x2) / 2, y - 7, label, size, fill=color, weight=700))
    return "".join(o)


def dim_v(y1, y2, x, label, ext_from=None, size=20, color="#1d4ed8"):
    o = []
    if ext_from is not None:
        o.append(L(ext_from, y1, x + (6 if x > ext_from else -6), y1, color, 1.2))
        o.append(L(ext_from, y2, x + (6 if x > ext_from else -6), y2, color, 1.2))
    o.append(L(x, y1, x, y2, color, 1.6, extra='marker-start="url(#arrS)" marker-end="url(#arrE)"'))
    cx, cy = x - 7, (y1 + y2) / 2
    o.append(T(cx, cy, label, size, fill=color, weight=700, extra='transform="rotate(-90 %.1f %.1f)"' % (cx, cy)))
    return "".join(o)


def bar_h(cx, cy):
    """진행 방향(x)에 수직인 막대: 폭 19(x) × 길이 70(y)."""
    return Rc(cx - TAPE / 2, cy - BAR_L / 2, TAPE, BAR_L, fill="#111")


def bar_r(deg, cx, cy):
    return '<g transform="translate(%.1f %.1f) rotate(%d)">%s</g>' % (
        cx, cy, deg, Rc(-BAR_L / 2, -TAPE / 2, BAR_L, TAPE, fill="#111"))


GUIDE_D = "M%d %d L%d %d A%d %d 0 0 0 %d %d L%d %d A%d %d 0 0 0 %d %d" % (
    SX0, GY_BOT, SX1, GY_BOT, R, R, SX1, GY_TOP, SX0, GY_TOP, R, R, SX0, GY_BOT)

DEFS = """<svg width="0" height="0" style="position:absolute"><defs>
<marker id="arrE" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#1d4ed8"/></marker>
<marker id="arrS" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10 0 L0 5 L10 10 z" fill="#1d4ed8"/></marker>
<marker id="flow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#334155"/></marker>
<pattern id="dots" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="4" cy="4" r="2" fill="#94a3b8"/></pattern>
<pattern id="hatch" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="14" stroke="#9ca3af" stroke-width="3"/></pattern>
<pattern id="stripes" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="14" fill="#e11d48"/><rect x="7" width="7" height="14" fill="#fff"/></pattern>
</defs></svg>"""

# ---------------- 도면 1: 전체 평면도 ----------------


def svg_plan_view():
    o = ['<svg viewBox="-200 -250 2240 1000" class="dwg">']
    o.append(Rc(0, 0, SX0, BH, fill="#f8fafc"))
    o.append(Rc(SX1, 0, BW - SX1, BH, fill="#f8fafc"))
    o.append(Rc(615, 0, 285, BH, fill="#dde3ea"))
    o.append(Rc(900, 0, 285, BH, fill="url(#dots)", extra='opacity="0.55"'))
    for a, b in STRIPS_X:
        o.append(Rc(a, 0, b - a, BH, fill="none", stroke="#a16207", sw=2, dash="10 8"))
    o.append(Rc(0, 0, BW, BH, fill="none", stroke="#111", sw=3))
    o.append(L(900, -20, 900, BH + 20, "#475569", 2, "14 8"))
    # 차선
    o.append(L(SX0, 150, SX1, 150, "#64748b", 3, "30 24"))
    o.append(L(SX0, 450, SX1, 450, "#64748b", 3, "30 24"))
    o.append(L(SX0, 295, SX1, 295, "#d4a017", 4))
    o.append(L(SX0, 305, SX1, 305, "#d4a017", 4))
    # 차체 통과 폭(유도선 ±70)
    for y in (GY_TOP - 70, GY_TOP + 70, GY_BOT - 70, GY_BOT + 70):
        o.append(L(SX0, y, SX1, y, "#ef4444", 1.5, "4 6"))
    # 유도선 + 막대
    o.append('<path d="%s" fill="none" stroke="#111" stroke-width="19"/>' % GUIDE_D)
    for x in END_BOT:
        o.append(bar_h(x, GY_BOT))
    for x in END_TOP:
        o.append(bar_h(x, GY_TOP))
    for x in SEG_BARS:
        o.append(bar_h(x, GY_BOT))
        o.append(bar_h(x, GY_TOP))
    for d, x, y in home_pts():
        o.append(bar_r(d, x, y))
    # 원호 중심
    for cx in (CXW, CXE):
        o.append(L(cx - 14, CYC, cx + 14, CYC, "#b91c1c", 2.5))
        o.append(L(cx, CYC - 14, cx, CYC + 14, "#b91c1c", 2.5))
    o.append(L(CXW, CYC, CXW - R * math.cos(math.radians(35)), CYC - R * math.sin(math.radians(35)), "#b91c1c", 1.6, "6 5"))
    o.append(T(CXW - 60, CYC - 40, "R190", 20, fill="#b91c1c", weight=800))
    o.append(T(CXW + 8, CYC + 36, "중심 (330, 300)", 18, "start", fill="#b91c1c", weight=700))
    o.append(L(CXE, CYC, CXE + R * math.cos(math.radians(35)), CYC - R * math.sin(math.radians(35)), "#b91c1c", 1.6, "6 5"))
    o.append(T(CXE + 62, CYC - 40, "R190", 20, fill="#b91c1c", weight=800))
    o.append(T(CXE - 8, CYC + 36, "중심 (1470, 300)", 18, "end", fill="#b91c1c", weight=700))
    # 방음벽, LED 기둥
    o.append(Rc(900, 0, 285, 10, fill="#334155"))
    o.append(Rc(900, BH - 10, 285, 10, fill="#334155"))
    for i, x in enumerate(POSTS_X):
        o.append(Rc(x - 10, BH - 22, 20, 20, fill="#22c55e", stroke="#14532d", sw=2))
        o.append(T(x, BH + 38, "L%d=%s" % (i + 1, LOOP[i]), 18, fill="#14532d", weight=800))
    for i, x in enumerate(reversed(POSTS_X)):
        o.append(Rc(x - 10, 2, 20, 20, fill="#22c55e", stroke="#14532d", sw=2))
        o.append(T(x, -16, "L%d=%s" % (i + 5, LOOP[i + 4]), 18, fill="#14532d", weight=800))
    # 교량 관측부
    o.append(Rc(682, 192, 172, 72, fill="#fff7ed", stroke="#c2410c", sw=2, rx=6, dash="8 5"))
    o.append(Rc(690, 200, 90, 56, fill="#e5e7eb", stroke="#374151", sw=2.5))
    o.append(Rc(712, 220, 34, 13, fill="#111", rx=6))
    o.append(Rc(790, 202, 56, 44, fill="#15803d"))
    o.append(C(645, 300, 13, fill="#f59e0b", stroke="#78350f", sw=2))
    for hx, hy in ((735, 272), (818, 256), (645, 300)):
        o.append(C(hx, hy, 5, fill="#fff", stroke="#b91c1c", sw=2))
    o.append(Rc(1030, 322, 26, 70, fill="url(#stripes)", stroke="#7f1d1d", sw=2))
    # 차고지 표지
    o.append(Rc(232, 270, 90, 40, fill="#ebe5d7", stroke="#8b7f6a", sw=2, rx=6))
    o.append(T(277, 297, "차고지", 18, weight=800))
    # 진행 방향
    o.append(L(450, 570, 560, 570, "#1d4ed8", 4, extra='marker-end="url(#arrE)"'))
    o.append(L(1350, 30, 1240, 30, "#1d4ed8", 4, extra='marker-end="url(#arrE)"'))
    # 구역 이름
    for x, s in ((165, "서쪽 회차"), (472.5, "S1 일반"), (757.5, "S2 교량(은박)"), (1042.5, "S3 그늘(방음벽)"),
                 (1327.5, "S4 일반"), (1635, "동쪽 회차")):
        o.append(T(x, -70, s, 22, weight=800, fill="#0f172a"))
    # 설명 지시선
    notes = [
        (735, 228, 610, 178, "① 금속 시험편 90×56 + ② 온도센서"),
        (818, 224, 990, 178, "③ 젖음센서"),
        (645, 300, 520, 360, "④ 주의 LED(중앙선 위)"),
        (1043, 357, 1150, 420, "1차로 통제 표시(제설차 경로 아님)"),
        (200, 430, 40, 640, "HOME 막대 3개(정차)"),
        (370, GY_BOT, 300, 650, "END 막대 2개"),
        (615, GY_BOT, 640, 650, "SEG 막대 1개"),
    ]
    for x1, y1, x2, y2, s in notes:
        o.append(L(x1, y1, x2, y2 - 6 if y2 > y1 else y2 + 6, "#c2410c", 1.6))
        o.append(T(x2, y2 + (16 if y2 > y1 else -4), s, 18, "middle", 800, "#9a3412"))
    # 치수
    o.append(dim_h(0, BW, -200, "1800 (우드락 900×600 2장)", ext_from=0))
    xs = [0, 330, 615, 900, 1185, 1470, 1800]
    for a, b in zip(xs, xs[1:]):
        o.append(dim_h(a, b, -130, "%d" % (b - a), ext_from=0, size=18))
    o.append(dim_v(0, BH, -150, "600", ext_from=0))
    for a, b in ((0, 150), (150, 300), (300, 450), (450, 600)):
        o.append(dim_v(a, b, -75, "150", ext_from=0, size=17))
    o.append(dim_v(0, GY_TOP, BW + 70, "110", ext_from=BW, size=17))
    o.append(dim_v(GY_TOP, GY_BOT, BW + 70, "380", ext_from=BW, size=17))
    o.append(dim_v(GY_BOT, BH, BW + 70, "110", ext_from=BW, size=17))
    o.append(T(BW + 150, GY_TOP + 6, "유도선 y=110", 17, "start", 700, "#1d4ed8"))
    o.append(T(BW + 150, GY_BOT + 6, "유도선 y=490", 17, "start", 700, "#1d4ed8"))
    o.append(T(0, 735, "원점(0,0)=왼쪽 위 모서리 · x→동쪽 · y→아래 · 점선 빨강=차체 통과 폭(유도선 ±70, 여기에 물건 금지) · 점선 갈색=밑면 받침 가로대 · 빨간 원=배선 구멍 Ø8",
               18, "start", 600, "#334155"))
    o.append('</svg>')
    return "".join(o)

# ---------------- 도면 2: 표식 상세 ----------------


def svg_marker_detail():
    o = ['<svg viewBox="0 0 1500 520" class="dwg">']
    # (a) END
    ox, oy = 60, 120
    o.append(T(ox, 60, "(a) END = 막대 2개", 26, "start", 800))
    o.append(Rc(ox, oy + 75, 420, 19, fill="#111"))
    for i, cx in enumerate((ox + 120, ox + 169)):
        o.append(Rc(cx - 9.5, oy + 49.5, 19, 70, fill="#111"))
    o.append(dim_h(ox + 110.5, ox + 129.5, oy + 30, "19", ext_from=oy + 49.5, size=18))
    o.append(dim_h(ox + 120, ox + 169, oy + 180, "중심 간 49", ext_from=oy + 119.5, size=18))
    o.append(dim_v(oy + 49.5, oy + 119.5, ox + 225, "70", ext_from=ox + 178.5, size=18))
    o.append(T(ox, oy + 260, "막대 사이 빈칸 30mm. 유도선(19mm)과 십자로 붙인다.", 19, "start", 600, "#334155"))
    o.append(T(ox, oy + 290, "진행 방향 →", 19, "start", 800, "#1d4ed8"))
    # (b) SEG
    ox = 560
    o.append(T(ox, 60, "(b) SEG = 막대 1개", 26, "start", 800))
    o.append(Rc(ox, oy + 75, 320, 19, fill="#111"))
    o.append(Rc(ox + 160 - 9.5, oy + 49.5, 19, 70, fill="#111"))
    o.append(T(ox, oy + 260, "구간 경계 x=615, 900, 1185(두 차로 모두).", 19, "start", 600, "#334155"))
    o.append(T(ox, oy + 290, "막대 1개 뒤 0.7초 안에 다음 막대가 없으면 SEG.", 19, "start", 600, "#334155"))
    # (c) HOME
    ox = 1000
    o.append(T(ox, 60, "(c) HOME = 원호 위 막대 3개", 26, "start", 800))
    cx, cy, rr = ox + 330, oy + 20, 260
    o.append('<path d="M %.1f %.1f A %d %d 0 0 0 %.1f %.1f" fill="none" stroke="#111" stroke-width="19"/>' % (
        cx + rr * math.cos(math.radians(190)), cy + rr * math.sin(math.radians(190)), rr, rr,
        cx + rr * math.cos(math.radians(95)), cy + rr * math.sin(math.radians(95))))
    for d in HOME_DEG:
        a = math.radians(d)
        o.append(bar_r(d, cx + rr * math.cos(a), cy + rr * math.sin(a)))
    o.append(T(ox, oy + 330, "실제 반지름 190, 중심 (330,300)에서 각도 155°·140°·125°.", 19, "start", 600, "#334155"))
    o.append(T(ox, oy + 360, "막대는 원의 중심을 향하게(반지름 방향) 붙인다.", 19, "start", 600, "#334155"))
    o.append('</svg>')
    return "".join(o)


def marker_table_rows():
    rows = []
    n = 1
    for x in END_BOT[:2]:
        rows.append((n, "END", "아래(상행, 동쪽으로)", x, GY_BOT, "직선 시작")); n += 1
    for x in SEG_BARS:
        rows.append((n, "SEG", "아래(상행)", x, GY_BOT, "구간 경계")); n += 1
    for x in END_BOT[2:]:
        rows.append((n, "END", "아래(상행)", x, GY_BOT, "직선 끝 → 동쪽 회차")); n += 1
    for x in END_TOP[:2]:
        rows.append((n, "END", "위(하행, 서쪽으로)", x, GY_TOP, "직선 시작")); n += 1
    for x in reversed(SEG_BARS):
        rows.append((n, "SEG", "위(하행)", x, GY_TOP, "구간 경계")); n += 1
    for x in END_TOP[2:]:
        rows.append((n, "END", "위(하행)", x, GY_TOP, "직선 끝 → 서쪽 회차")); n += 1
    for d, x, y in home_pts():
        rows.append((n, "HOME", "서쪽 원호", round(x, 1), round(y, 1), "%d° · 반지름 방향" % d)); n += 1
    return rows

# ---------------- 도면 3: 재단 배치 ----------------


def svg_cut_layout():
    o = ['<svg viewBox="-60 -70 1060 760" class="dwg">']
    o.append(Rc(0, 0, 900, 600, fill="#fffdf7", stroke="#111", sw=3))
    parts = []
    for i in range(6):
        parts.append((i * 100, 0, 100, 600, "받침 %d\n600×100" % (i + 1), "#fde68a"))
    parts += [
        (600, 0, 285, 100, "방음벽 A 285×100", "#cbd5e1"),
        (600, 105, 285, 100, "방음벽 B 285×100", "#cbd5e1"),
        (600, 210, 285, 15, "", "#e2e8f0"),
        (600, 230, 285, 15, "", "#e2e8f0"),
        (600, 255, 30, 30, "", "#cbd5e1"), (635, 255, 30, 30, "", "#cbd5e1"), (670, 255, 30, 30, "", "#cbd5e1"),
    ]
    for j in range(8):
        parts.append((710 + j * 22, 255, 20, 40, "", "#bbf7d0"))
    for j in range(4):
        parts.append((600 + j * 55, 305, 50, 60, "살포통\n벽", "#fed7aa"))
    parts += [
        (820, 305, 50, 50, "바닥", "#fdba74"),
        (600, 375, 25, 45, "", "#fdba74"),
        (635, 375, 90, 40, "차고지 표지", "#e7e5e4"),
        (735, 375, 70, 26, "통제판", "#fecaca"),
        (815, 375, 30, 30, "", "#fde68a"),
        (600, 430, 120, 40, "제설 날(선택) 120×40", "#fef08a"),
    ]
    for x, y, w, h, s, col in parts:
        o.append(Rc(x, y, w, h, fill=col, stroke="#334155", sw=1.5))
        lines = s.split("\n") if s else []
        for k, ln in enumerate(lines):
            size = 17 if w >= 90 else 13
            o.append(T(x + w / 2, y + h / 2 + (k - (len(lines) - 1) / 2) * (size + 3) + 5, ln, size, weight=700))
    o.append(T(742, 222, "교량 난간 285×15 ×2", 14, weight=700))
    o.append(T(652, 300, "삼각 받침 30×30 ×3 → 대각선 절단 = 6개", 13, "start", 700, "#334155",
               extra='transform="translate(0 0)"'))
    o.append(T(797, 252, "LED 기둥 20×40 ×8(2겹으로 붙이면 두께 10)", 13, "middle", 700, "#14532d"))
    o.append(T(612, 425, "덮개 25×45", 12, "start", 700))
    o.append(T(830, 425, "LED 받침 30×30", 12, "middle", 700))
    o.append(dim_h(0, 900, -40, "900", ext_from=0))
    o.append(dim_v(0, 600, -30, "600", ext_from=0))
    o.append(T(0, 660, "세 번째 우드락(5mm) 1장에서 모두 나온다. 받침 6개는 2개씩 겹쳐 10mm 가로대 3개를 만든다(보드 밑 배선 통로).",
               17, "start", 600, "#334155"))
    o.append('</svg>')
    return "".join(o)

# ---------------- 도면 4: 부재 상세 ----------------


def svg_parts_detail():
    o = ['<svg viewBox="0 0 1500 660" class="dwg">']
    # (a) 이음·받침 단면: x 20~480
    o.append(T(20, 40, "(a) 보드 이음과 밑면 받침(단면)", 24, "start", 800))
    o.append(Rc(30, 110, 215, 10, fill="#f5f5f4", stroke="#111", sw=2))
    o.append(Rc(247, 110, 215, 10, fill="#f5f5f4", stroke="#111", sw=2))
    o.append(Rc(196, 120, 100, 10, fill="#fde68a", stroke="#111", sw=1.5))
    o.append(Rc(196, 130, 100, 10, fill="#fde68a", stroke="#111", sw=1.5))
    o.append(L(20, 140, 475, 140, "#57534e", 3))
    o.append(Rc(226, 104, 42, 6, fill="#9ca3af"))
    o.append(T(247, 94, "윗면 이음: 투명 테이프", 16, weight=700, fill="#334155"))
    o.append(T(247, 166, "가로대 600×100 · 2겹 = 10mm", 16, weight=700, fill="#92400e"))
    o.append(T(20, 210, "· 가로대 사이 빈 공간 = 배선 통로", 16, "start", 700, "#1d4ed8"))
    o.append(T(20, 234, "· 위치: x 250~350 · 850~950 · 1450~1550", 16, "start", 600, "#334155"))
    o.append(T(20, 258, "· 가운데 가로대가 이음선 보강을 겸한다", 16, "start", 600, "#334155"))
    # (b) 방음벽: x 520~980
    o.append(T(520, 40, "(b) 방음벽(S3 양쪽 가장자리)", 24, "start", 800))
    o.append(Rc(560, 70, 285, 100, fill="#cbd5e1", stroke="#111", sw=2))
    o.append(T(702, 126, "285×100 (세워서)", 18, weight=800))
    for k in range(3):
        bx = 580 + k * 110
        o.append('<polygon points="%d,170 %d,140 %d,170" fill="#94a3b8" stroke="#111" stroke-width="1.5"/>' % (bx, bx, bx + 30))
    o.append(L(540, 170, 960, 170, "#57534e", 3))
    o.append(T(520, 210, "· 도로 쪽에 30×30 삼각 받침 3개", 16, "start", 600, "#334155"))
    o.append(T(520, 234, "  (차체 통과 폭 y≥40을 넘지 않게)", 16, "start", 600, "#334155"))
    o.append(T(520, 258, "· 바깥에서 탁상 램프를 비추면", 16, "start", 600, "#334155"))
    o.append(T(520, 282, "  S3에 그림자가 진다(그늘 표현)", 16, "start", 600, "#334155"))
    # (c) LED 기둥: x 1020~1480
    o.append(T(1020, 40, "(c) 칸 LED 기둥", 24, "start", 800))
    o.append(Rc(1070, 86, 20, 40, fill="#bbf7d0", stroke="#111", sw=2))
    o.append(C(1080, 79, 9, fill="#22c55e", stroke="#14532d", sw=2))
    o.append(L(1030, 126, 1250, 126, "#57534e", 3))
    o.append(L(1095, 126, 1095, 168, "#64748b", 2, "6 4"))
    o.append(C(1095, 126, 4, fill="#fff", stroke="#b91c1c", sw=2))
    o.append(T(1110, 92, "WS2812 픽셀 또는 5mm LED", 15, "start", 700))
    o.append(T(1110, 158, "구멍 Ø6 → 선을 밑면으로", 15, "start", 700))
    o.append(T(1020, 210, "· 체인 순서 = 루프 순서", 16, "start", 700, "#334155"))
    o.append(T(1020, 234, "· L1=U1 … L4=U4: 아래쪽 가장자리, 서→동", 16, "start", 600, "#334155"))
    o.append(T(1020, 258, "· L5=D4 … L8=D1: 위쪽 가장자리, 동→서", 16, "start", 600, "#334155"))
    o.append(T(1020, 282, "· 동쪽 끝을 돌아 체인을 이어 준다", 16, "start", 600, "#334155"))
    # (d) 살포통
    o.append(L(20, 310, 1480, 310, "#e2e8f0", 2))
    o.append(T(20, 350, "(d) 살포통(제설차 뒤) — 옆에서 본 모습 / 밑에서 본 모습", 24, "start", 800))
    o.append(Rc(80, 390, 120, 144, fill="#fed7aa", stroke="#111", sw=2))
    o.append(T(140, 470, "50×50×60", 17, weight=800))
    o.append(T(140, 494, "윗면 열림", 15, weight=700))
    o.append(Rc(80, 534, 120, 10, fill="#fdba74", stroke="#111", sw=1.5))
    o.append(Rc(200, 520, 46, 24, fill="#2563eb", stroke="#111", sw=1.5))
    o.append(T(223, 537, "SG90", 13, weight=800, fill="#fff"))
    o.append(L(212, 544, 150, 565, "#111", 4))
    o.append(Rc(100, 558, 60, 10, fill="#fdba74", stroke="#111", sw=1.5, extra='transform="rotate(-8 130 563)"'))
    o.append(T(270, 470, "· 서보 혼에 덮개(25×45)를 붙여", 16, "start", 700))
    o.append(T(270, 494, "  바닥 구멍을 막는다", 16, "start", 700))
    o.append(T(270, 530, "· 닫힘 0° / 열림 60°", 16, "start", 700, "#1d4ed8"))
    o.append(T(270, 554, "  (SERVO_CLOSED_DEG · SERVO_OPEN_DEG)", 16, "start", 700, "#1d4ed8"))
    o.append(Rc(760, 390, 150, 150, fill="#fdba74", stroke="#111", sw=2))
    o.append(Rc(800, 480, 70, 30, fill="#fff", stroke="#111", sw=2))
    o.append(T(835, 500, "15×35", 14, weight=800))
    o.append(T(835, 430, "바닥 50×50", 17, weight=800))
    o.append(T(940, 430, "· 구멍은 뒤쪽 가장자리 가까이", 16, "start", 600))
    o.append(T(940, 458, "· 내용물: 마른 쌀알·스티로폼 알갱이", 16, "start", 600))
    o.append(T(940, 486, "· 실제 제설제(염화칼슘) 사용 금지", 16, "start", 700, "#b91c1c"))
    o.append(T(940, 514, "· 1칸에 1회 열고 닫음 = 1회분(SALT_MS)", 16, "start", 600))
    o.append('</svg>')
    return "".join(o)

# ---------------- 도면 5: 교량 관측부 단면 ----------------


def svg_bridge_section():
    o = ['<svg viewBox="0 0 1500 430" class="dwg">']
    o.append(L(20, 300, 1480, 300, "#57534e", 3))
    o.append(T(30, 330, "책상", 15, "start", 700, "#57534e"))
    o.append(Rc(60, 270, 1380, 14, fill="#f5f5f4", stroke="#111", sw=2))
    o.append(Rc(60, 266, 1380, 4, fill="#cbd5e1"))
    o.append(T(80, 258, "보드 윗면 은박(교량 표시)", 15, "start", 700, "#475569"))
    o.append(Rc(1100, 284, 160, 16, fill="#fde68a", stroke="#111", sw=1.5))
    o.append(T(1180, 297, "받침 가로대(이 위치엔 없음, 참고)", 12, weight=700))
    # 물받이 + 시험편
    o.append(Rc(300, 240, 420, 26, fill="none", stroke="#0ea5e9", sw=3))
    o.append(T(510, 232, "물받이(얕은 플라스틱 뚜껑)", 15, weight=700, fill="#0369a1"))
    o.append(Rc(330, 236, 180, 8, fill="#d1d5db", stroke="#111", sw=2))
    o.append(T(420, 214, "① 금속 시험편(알루미늄 판 90×56)", 15, weight=800))
    o.append(Rc(380, 226, 60, 10, fill="#111", rx=5))
    o.append(T(410, 196, "② DS18B20 방수 프로브", 15, weight=800))
    o.append(Rc(540, 232, 110, 10, fill="#15803d"))
    o.append(T(600, 196, "③ 젖음센서 기판", 15, weight=800))
    o.append(Rc(330, 244, 180, 20, fill="none", stroke="#7c3aed", sw=2, dash="6 4"))
    o.append(T(250, 168, "선택 실험: 시험편 아래 밀폐 냉각팩", 15, "middle", 700, "#7c3aed"))
    o.append(L(300, 172, 360, 246, "#7c3aed", 1.4))
    # 구멍과 배선
    o.append(Rc(470, 270, 12, 14, fill="#fff", stroke="#b91c1c", sw=2))
    o.append('<path d="M 440 231 C 470 231, 476 250, 476 270 L 476 292 L 1400 292" fill="none" stroke="#111" stroke-width="2.5"/>')
    o.append('<path d="M 600 237 C 610 250, 590 262, 560 262 L 488 262" fill="none" stroke="#166534" stroke-width="2.5"/>')
    o.append(T(980, 286, "보드 밑 10mm 통로로 → 보드 옆 Pico #1", 15, weight=700, fill="#1d4ed8"))
    # 주의 LED
    o.append(Rc(860, 200, 16, 70, fill="#e7e5e4", stroke="#111", sw=1.5))
    o.append(C(868, 192, 11, fill="#f59e0b", stroke="#78350f", sw=2))
    o.append(T(868, 170, "④ 주의 LED(중앙선)", 15, weight=800))
    o.append(Rc(862, 270, 12, 14, fill="#fff", stroke="#b91c1c", sw=2))
    o.append(T(60, 395, "시험편 온도와 젖음은 '관측값'이다. 둘을 합쳐도 결빙을 확정하지 않는다. 물 분무는 물받이 안에서만 한다.",
               17, "start", 700, "#b45309"))
    o.append('</svg>')
    return "".join(o)

# ---------------- 도면 6: 제설차 배치 ----------------


def svg_car_layout():
    o = ['<svg viewBox="0 0 1500 560" class="dwg">']
    o.append(T(20, 40, "(a) 위에서 본 모습(예: 2WD 섀시)", 24, "start", 800))
    ox, oy = 120, 90
    o.append(Rc(ox, oy, 380, 280, fill="#fed7aa", stroke="#9a3412", sw=3, rx=20))
    o.append(Rc(ox + 60, oy - 30, 90, 30, fill="#1f2937"))
    o.append(Rc(ox + 60, oy + 280, 90, 30, fill="#1f2937"))
    o.append(C(ox + 330, oy + 140, 16, fill="#9ca3af", stroke="#374151", sw=2))
    o.append(T(ox + 330, oy + 180, "캐스터", 14, weight=700))
    o.append(Rc(ox + 70, oy + 40, 110, 50, fill="#166534"))
    o.append(T(ox + 125, oy + 72, "Pico #2", 16, weight=800, fill="#fff"))
    o.append(Rc(ox + 70, oy + 110, 90, 40, fill="#7c3aed"))
    o.append(T(ox + 115, oy + 136, "드라이버", 14, weight=800, fill="#fff"))
    o.append(Rc(ox + 180, oy + 110, 110, 90, fill="#facc15", stroke="#a16207", sw=2))
    o.append(T(ox + 235, oy + 160, "AA×4", 16, weight=800))
    o.append(Rc(ox + 200, oy + 40, 90, 50, fill="#cbd5e1", stroke="#64748b", sw=2))
    o.append(T(ox + 245, oy + 70, "보조배터리", 13, weight=700))
    # 앞 = 오른쪽
    for k in range(3):
        o.append(Rc(ox + 390, oy + 110 + k * 22, 18, 18, fill="#fff", stroke="#111", sw=2, dash="4 3"))
    o.append(Rc(ox + 420, oy + 105, 60, 70, fill="#0ea5e9"))
    o.append(C(ox + 438, oy + 140, 11, fill="#e0f2fe", stroke="#0369a1", sw=1.5))
    o.append(C(ox + 462, oy + 140, 11, fill="#e0f2fe", stroke="#0369a1", sw=1.5))
    o.append(Rc(ox - 70, oy + 100, 70, 80, fill="#fb923c", stroke="#c2410c", sw=2))
    o.append(T(ox - 35, oy + 145, "살포통", 13, weight=800, fill="#fff"))
    o.append(C(ox + 300, oy + 60, 12, fill="#fbbf24", stroke="#92400e", sw=2))
    o.append(dim_v(oy + 110, oy + 172, ox + 520, "18+18", ext_from=ox + 408, size=15))
    o.append(dim_h(ox, ox + 380, oy + 340, "차 길이(섀시)", ext_from=oy + 280, size=15))
    o.append(dim_v(oy, oy + 280, ox - 95, "차폭 140 이하 권장", ext_from=ox, size=15))
    o.append(T(ox + 400, oy - 20, "라인센서 3개: 중심 간 18mm, 바퀴 축보다 30~40mm 앞", 15, "start", 700))
    o.append(T(ox + 400, oy + 230, "→ 진행 방향(앞)", 18, "start", 800, "#1d4ed8"))
    # (b) 옆
    o.append(T(820, 40, "(b) 옆에서 본 모습", 24, "start", 800))
    gx, gy = 840, 420
    o.append(L(gx - 20, gy, gx + 620, gy, "#57534e", 3))
    o.append(Rc(gx + 60, gy - 120, 380, 60, fill="#fed7aa", stroke="#9a3412", sw=3, rx=8))
    o.append(C(gx + 130, gy - 33, 33, fill="#1f2937"))
    o.append(C(gx + 390, gy - 12, 12, fill="#9ca3af", stroke="#374151", sw=2))
    o.append(Rc(gx + 440, gy - 16, 34, 8, fill="#fff", stroke="#111", sw=2, dash="3 2"))
    o.append(dim_v(gy - 8, gy, gx + 500, "5~8", ext_from=gx + 474, size=15))
    o.append(Rc(gx + 445, gy - 100, 30, 50, fill="#0ea5e9"))
    o.append(dim_v(gy - 75, gy, gx + 560, "30~40", ext_from=gx + 475, size=15))
    o.append(Rc(gx, gy - 160, 60, 100, fill="#fb923c", stroke="#c2410c", sw=2))
    o.append(dim_v(gy - 60, gy, gx - 25, "≥30", ext_from=gx, size=15))
    o.append(T(gx + 240, gy - 135, "라인센서: 바닥에서 5~8mm(모듈 표시등으로 확인)", 15, "middle", 700))
    o.append(T(gx + 240, gy + 40, "초음파는 앞을 가리지 않게. 제설 날을 달면 초음파 아래쪽에.", 15, "middle", 700, "#334155"))
    o.append(T(20, 530, "섀시 크기는 키트마다 다르다. 차로 폭이 150mm라 차폭이 140mm를 넘으면 유도선 위치를 바꾸지 말고 회차 원호가 판 안에 드는지만 확인한다(도면 1 빨간 점선).",
               16, "start", 600, "#b45309"))
    o.append('</svg>')
    return "".join(o)

# ---------------- 도면 7·8: 배선 ----------------

LEFT_PINS = {1: "GP0", 2: "GP1", 3: "GND", 4: "GP2", 5: "GP3", 6: "GP4", 7: "GP5", 8: "GND", 9: "GP6", 10: "GP7",
             11: "GP8", 12: "GP9", 13: "GND", 14: "GP10", 15: "GP11", 16: "GP12", 17: "GP13", 18: "GND", 19: "GP14",
             20: "GP15"}
RIGHT_PINS = {40: "VBUS", 39: "VSYS", 38: "GND", 37: "3V3_EN", 36: "3V3", 35: "ADC_VREF", 34: "GP28", 33: "AGND",
              32: "GP27", 31: "GP26", 30: "RUN", 29: "GP22", 28: "GND", 27: "GP21", 26: "GP20", 25: "GP19",
              24: "GP18", 23: "GND", 22: "GP17", 21: "GP16"}


def pico(x, y, used, title):
    """피코 핀 배치(위에서 본 모습, USB 위). 반환: (svg, 핀 좌표 dict)."""
    o, pos = [], {}
    w, step = 230, 25
    h = 20 * step + 40
    o.append(Rc(x, y, w, h, fill="#166534", stroke="#052e16", sw=3, rx=10))
    o.append(Rc(x + 85, y - 18, 60, 26, fill="#9ca3af", stroke="#374151", sw=2, rx=4))
    o.append(T(x + w / 2, y - 26, "USB", 14, weight=800))
    o.append(T(x + w / 2, y + h / 2, title, 22, weight=800, fill="#ecfdf5"))
    for p, name in LEFT_PINS.items():
        py = y + 30 + (p - 1) * step
        pos[p] = (x, py)
        col = used.get(p, None)
        o.append(C(x, py, 6, fill=col or "#d1d5db", stroke="#052e16", sw=1.5))
        o.append(T(x + 12, py + 5, "%d %s" % (p, name), 13, "start", 800 if col else 500, "#ecfdf5" if col else "#86efac"))
    for p, name in RIGHT_PINS.items():
        py = y + 30 + (40 - p) * step
        pos[p] = (x + w, py)
        col = used.get(p, None)
        o.append(C(x + w, py, 6, fill=col or "#d1d5db", stroke="#052e16", sw=1.5))
        o.append(T(x + w - 12, py + 5, "%s %d" % (name, p), 13, "end", 800 if col else 500, "#ecfdf5" if col else "#86efac"))
    return "".join(o), pos


def box(x, y, w, h, title, pins, fill="#f8fafc", side="right"):
    """모듈 상자. pins=[이름...] → 핀 좌표를 상자 가장자리(side)에 만든다."""
    o = [Rc(x, y, w, h, fill=fill, stroke="#334155", sw=2, rx=8), T(x + w / 2, y + 24, title, 17, weight=800)]
    pos = {}
    n = len(pins)
    for i, name in enumerate(pins):
        py = y + 44 + i * ((h - 54) / max(1, n - 1) if n > 1 else 0)
        px = x + w if side == "right" else x
        pos[name] = (px, py)
        o.append(C(px, py, 5, fill="#fff", stroke="#334155", sw=1.5))
        o.append(T(px - 9 if side == "right" else px + 9, py + 5, name, 13, "end" if side == "right" else "start", 700))
    return "".join(o), pos


def wire(a, b, color, label=None, via=None):
    (x1, y1), (x2, y2) = a, b
    mx = via if via is not None else (x1 + x2) / 2
    d = "M %.1f %.1f L %.1f %.1f L %.1f %.1f L %.1f %.1f" % (x1, y1, mx, y1, mx, y2, x2, y2)
    s = '<path d="%s" fill="none" stroke="%s" stroke-width="3"/>' % (d, color)
    if label:
        s += T(mx + 4, (y1 + y2) / 2 - 4, label, 12, "start", 700, color)
    return s


def net(p, name, color, side):
    x, y = p
    dx = -70 if side == "left" else 70
    return L(x, y, x + dx, y, color, 3) + Rc(x + dx - (54 if side == "left" else 0), y - 11, 54, 22, fill=color, rx=4) + \
        T(x + dx - 27 if side == "left" else x + dx + 27, y + 5, name, 12, weight=800, fill="#fff")


def svg_wiring_car():
    used = {4: "#f97316", 5: "#f97316", 12: "#7c3aed", 14: "#7c3aed", 15: "#7c3aed", 16: "#7c3aed", 17: "#7c3aed",
            19: "#7c3aed", 20: "#7c3aed", 21: "#2563eb", 22: "#eab308", 24: "#111", 25: "#111", 26: "#111", 27: "#16a34a",
            40: "#dc2626", 36: "#ea580c", 38: "#111", 3: "#111"}
    o = ['<svg viewBox="0 0 1500 760" class="dwg">']
    ps, pp = pico(620, 120, used, "Pico #2")
    o.append(ps)
    s1, hc = box(150, 40, 200, 170, "HC-SR04 초음파", ["VCC", "TRIG", "ECHO", "GND"])
    o.append(s1)
    o.append(wire(hc["TRIG"], pp[4], "#f97316", "TRIG→GP2", via=470))
    o.append(wire(hc["ECHO"], pp[5], "#f97316", None, via=430))
    o.append(Rc(408, 194, 44, 14, fill="#fff7ed", stroke="#c2410c", sw=1.5))
    o.append(T(430, 205, "1kΩ", 11, weight=800))
    o.append(T(250, 236, "ECHO → 1kΩ → GP3, GP3 ↔ 2kΩ ↔ GND (5V→3.3V 분압)", 13, "middle", 800, "#c2410c"))
    o.append(net(hc["VCC"], "5V", "#dc2626", "left"))
    o.append(net(hc["GND"], "GND", "#111", "left"))
    s2, tb = box(150, 270, 200, 400, "TB6612FNG", ["STBY", "AIN1", "AIN2", "PWMA", "BIN1", "BIN2", "PWMB", "VCC", "GND"])
    o.append(s2)
    for name, pin in (("STBY", 12), ("AIN1", 14), ("AIN2", 15), ("PWMA", 16), ("BIN1", 17), ("BIN2", 19), ("PWMB", 20)):
        o.append(wire(tb[name], pp[pin], "#7c3aed", None, via=420 + (pin % 7) * 18))
    o.append(net(tb["VCC"], "3V3", "#ea580c", "left"))
    o.append(net(tb["GND"], "GND", "#111", "left"))
    o.append(T(250, 700, "VM ← AA×4(+), GND ← AA×4(−)  ·  AO1/AO2 → 왼쪽 모터  ·  BO1/BO2 → 오른쪽 모터", 13, "middle", 700, "#334155"))
    s3, sv = box(1080, 40, 190, 130, "SG90 살포 서보", ["신호", "+5V", "GND"], side="left")
    o.append(s3)
    o.append(wire(pp[21], sv["신호"], "#2563eb", "GP16", via=960))
    o.append(net(sv["+5V"], "5V", "#dc2626", "right"))
    o.append(net(sv["GND"], "GND", "#111", "right"))
    s4, ld = box(1080, 200, 190, 90, "경광 LED", ["+(220Ω)", "−"], side="left")
    o.append(s4)
    o.append(wire(pp[22], ld["+(220Ω)"], "#eab308", "GP17", via=990))
    o.append(net(ld["−"], "GND", "#111", "right"))
    s5, ls = box(1080, 320, 190, 200, "라인센서 L·C·R", ["L DO", "C DO", "R DO", "VCC", "GND"], side="left")
    o.append(s5)
    for name, pin in (("L DO", 24), ("C DO", 25), ("R DO", 26)):
        o.append(wire(pp[pin], ls[name], "#111", None, via=900 + (pin - 24) * 25))
    o.append(net(ls["VCC"], "3V3", "#ea580c", "right"))
    o.append(net(ls["GND"], "GND", "#111", "right"))
    s6, bt = box(1080, 550, 190, 90, "버튼", ["한쪽", "다른쪽"], side="left")
    o.append(s6)
    o.append(wire(pp[27], bt["한쪽"], "#16a34a", "GP21", via=1010))
    o.append(net(bt["다른쪽"], "GND", "#111", "right"))
    o.append(net(pp[40], "5V", "#dc2626", "right"))
    o.append(net(pp[36], "3V3", "#ea580c", "right"))
    o.append(net(pp[38], "GND", "#111", "right"))
    o.append(T(735, 60, "보조배터리 → USB (VBUS=5V 생김)", 15, weight=800, fill="#334155"))
    o.append(T(20, 735, "같은 이름표(5V·3V3·GND)끼리 연결한다. 모든 GND는 하나로(Pico·드라이버·AA 배터리(−)·서보·센서). 모터 전원(AA×4)은 Pico에 넣지 않는다.",
               15, "start", 700, "#b45309"))
    o.append('</svg>')
    return "".join(o)


def svg_wiring_board():
    used = {6: "#0f766e", 20: "#f59e0b", 21: "#2563eb", 31: "#0284c7", 36: "#ea580c", 40: "#dc2626", 38: "#111"}
    o = ['<svg viewBox="0 0 1500 760" class="dwg">']
    ps, pp = pico(620, 120, used, "Pico #1")
    o.append(ps)
    s1, ds = box(150, 60, 220, 190, "DS18B20 ×2(병렬)", ["VDD", "DQ", "GND"])
    o.append(s1)
    o.append(wire(ds["DQ"], pp[6], "#0f766e", "DQ→GP4", via=480))
    o.append(Rc(400, 105, 60, 16, fill="#ecfeff", stroke="#0f766e", sw=1.5))
    o.append(T(430, 117, "4.7kΩ", 11, weight=800))
    o.append(T(260, 280, "4.7kΩ 풀업: DQ ↔ 3V3(필수)", 14, "middle", 800, "#0f766e"))
    o.append(net(ds["VDD"], "3V3", "#ea580c", "left"))
    o.append(net(ds["GND"], "GND", "#111", "left"))
    s2, wl = box(150, 330, 220, 150, "주의 LED(교량)", ["+(220Ω)", "−"])
    o.append(s2)
    o.append(wire(wl["+(220Ω)"], pp[20], "#f59e0b", "GP15", via=500))
    o.append(net(wl["−"], "GND", "#111", "left"))
    s3, np_ = box(1080, 60, 220, 190, "WS2812 칸 LED ×8", ["DIN(330Ω)", "5V", "GND"], side="left")
    o.append(s3)
    o.append(wire(pp[21], np_["DIN(330Ω)"], "#2563eb", "GP16", via=960))
    o.append(net(np_["5V"], "5V", "#dc2626", "right"))
    o.append(net(np_["GND"], "GND", "#111", "right"))
    s4, ws = box(1080, 320, 220, 150, "젖음센서 모듈", ["AO", "VCC", "GND"], side="left")
    o.append(s4)
    o.append(wire(pp[31], ws["AO"], "#0284c7", "GP26(ADC0)", via=990))
    o.append(net(ws["VCC"], "3V3", "#ea580c", "right"))
    o.append(net(ws["GND"], "GND", "#111", "right"))
    o.append(net(pp[40], "5V", "#dc2626", "right"))
    o.append(net(pp[36], "3V3", "#ea580c", "right"))
    o.append(net(pp[38], "GND", "#111", "right"))
    o.append(T(735, 60, "노트북 USB → 전원 + 데이터(@@TEL / @@LED)", 15, weight=800, fill="#334155"))
    o.append(T(20, 700, "단색 LED를 쓸 때(LED_MODE='gpio'): GP6·GP7·GP8·GP9·GP10·GP11·GP12·GP13 = L1~L8, 각각 220Ω → LED → GND.",
               15, "start", 700, "#334155"))
    o.append(T(20, 730, "젖음센서 모듈은 3V3로 전원을 넣어야 AO가 3.3V를 넘지 않는다. WS2812가 불안정하면 5V 선에 1N4001 다이오드 1개를 넣어 전압을 낮춘다.",
               15, "start", 700, "#b45309"))
    o.append('</svg>')
    return "".join(o)

# ---------------- 도면 9: 시스템 구성 ----------------


def svg_system():
    o = ['<svg viewBox="0 0 1500 560" class="dwg">']

    def b(x, y, w, h, title, sub, fill):
        s = Rc(x, y, w, h, fill=fill, stroke="#334155", sw=2.5, rx=14) + T(x + w / 2, y + 36, title, 22, weight=800)
        for k, line in enumerate(sub):
            s += T(x + w / 2, y + 66 + k * 24, line, 15, weight=600, fill="#334155")
        return s
    o.append(b(560, 30, 380, 210, "노트북: icezero_server.py", ["계획 계산(ICE-ZERO-lite, 코드)", "제보 해석(LLM) · 규칙 비교", "대시보드 http://노트북IP:8000",
                                                             "사람 승인 3단계 · events.jsonl"], "#eef5ff"))
    o.append(b(1080, 30, 380, 150, "Command Code API", ["deepseek-v4.1-flash", "제보 → {칸, 예산, 모호하면 질문}"], "#f5f0ff"))
    o.append(b(40, 300, 420, 210, "Pico #1 보드(USB)", ["교량 시험편 온도·공기 온도", "젖음센서 · 주의 LED(로컬 즉시)", "칸 LED 8개(위험·계획·살포)"], "#ecfdf3"))
    o.append(b(1040, 300, 420, 210, "Pico #2 제설차(Wi-Fi UDP)", ["라인 추종 · 막대 세기 · 위치", "승인 칸에서만 살포 서보", "초음파·버튼·길잃음 → 로컬 정지"], "#fff4e5"))
    o.append(b(560, 330, 380, 180, "사람(담당자)", ["① 제보 해석 확인", "② 계획 승인", "③ 출동 승인 · 비상 정지"], "#fef9c3"))
    o.append(L(940, 105, 1080, 105, "#7c3aed", 3, extra='marker-end="url(#flow)"'))
    o.append(T(1010, 95, "HTTPS", 14, weight=800, fill="#7c3aed"))
    o.append(L(560, 200, 300, 300, "#166534", 3, extra='marker-end="url(#flow)"'))
    o.append(L(300, 300, 560, 200, "#166534", 3, extra='marker-end="url(#flow)"'))
    o.append(T(390, 236, "USB: @@TEL ↑ / @@LED ↓", 15, weight=800, fill="#166534"))
    o.append(L(940, 200, 1200, 300, "#c2410c", 3, extra='marker-end="url(#flow)"'))
    o.append(L(1200, 300, 940, 200, "#c2410c", 3, extra='marker-end="url(#flow)"'))
    o.append(T(1150, 236, "UDP 9100↔9101 (휴대폰 핫스팟 2.4GHz)", 15, weight=800, fill="#c2410c"))
    o.append(L(750, 330, 750, 240, "#a16207", 3, extra='marker-end="url(#flow)"'))
    o.append(T(760, 290, "대시보드 버튼", 14, "start", 800, "#a16207"))
    o.append(T(750, 548, "LLM은 차를 조종하지 않는다 · 확인 전 제보는 계획에 반영되지 않는다 · 안전 정지는 Pico 로컬", 17, "middle", 800, "#b45309"))
    o.append('</svg>')
    return "".join(o)

# ---------------- 본문 ----------------


def table(head, rows, cls=""):
    h = "".join("<th>%s</th>" % esc(c) for c in head)
    b = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)
    return '<table class="%s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (cls, h, b)


def eval_block():
    if not os.path.exists(EVAL_JSON):
        return "<p class='warn'>아직 측정 파일(tests/eval_result.json)이 없다. 4단계 리허설 전에 <code>cd icezero_model &amp;&amp; python3 tests/eval_reports.py</code>로 만든다.</p>"
    try:
        data = json.load(open(EVAL_JSON, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return "<p class='warn'>eval_result.json을 읽지 못했다: %s</p>" % esc(e)
    def pct(s):
        return "%d/%d (%.0f%%)" % (s["cells_ok"], s["cells_total"], 100 * s["cells_accuracy"])

    rule, llm = data.get("rule", {}), data.get("llm_scores", {})
    info = data.get("llm", {})
    head = ["", "칸 완전 일치(모호하지 않은 제보)", "모호 판정(12건)", "예산 읽기(12건)", "평균 지연"]
    rows = []
    for name, s in (("규칙 해석(rule_parse)", rule), ("LLM %s, %s" % (info.get("model", "?"), info.get("reasoning", "")), llm)):
        if not s:
            continue
        rows.append((esc(name), pct(s), "%d/%d" % (s["ambiguous_ok"], s["items"]), "%d/%d" % (s["budget_ok"], s["items"]),
                     "%.0f ms" % s.get("mean_latency_ms", 0)))
    out = table(head, rows, "tight")
    det = []
    for d in data.get("details", []):
        f = d.get("flags", {})
        mark = lambda k: "".join("○" if f.get(k, {}).get(x) else "✕" for x in ("cells_ok", "ambiguous_ok", "budget_ok"))
        det.append((esc(d.get("text", "")), esc(",".join(d.get("expect", {}).get("cells", [])) +
                                                (" (모호)" if d.get("expect", {}).get("ambiguous") else "")),
                    esc(",".join(d.get("rule", {}).get("cells", []))) + " " + mark("rule"),
                    esc(",".join((d.get("llm") or {}).get("cells", []))) + " " + mark("llm")))
    if det:
        out += table(["제보", "정답 칸", "규칙(칸·모호·예산)", "LLM(칸·모호·예산)"], det, "tight")
    out += "<p class='small'>측정 시각 %s · LLM 실패 %s건 · %s</p>" % (
        esc(data.get("generated_at", "?")), esc(info.get("failures", "?")), esc(data.get("cell_scope_note", "")))
    return out


def cfg_rows(path):
    """config.py의 `이름 = 값  # 설명` 줄을 행으로 만든다(코드와 문서가 어긋나지 않게)."""
    import re
    rows = []
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*(?:#\s*(.*))?$", line.rstrip("\n"))
        if not m:
            continue
        name, val, note = m.group(1), m.group(2), m.group(3) or ""
        if "PASSWORD" in name or name == "TOKEN":
            val = val if val in ('""', "''") else "(팀 값)"
        rows.append(("<code>%s</code>" % esc(name), "<code>%s</code>" % esc(val[:30]), esc(note)))
    return rows


def cfg_table(rows):
    if not rows:
        return "<p class='warn'>설정 파일 없음</p>"
    return table(["이름", "기본값", "설명"], rows, "tight cfg")


def run_text(args, timeout):
    try:
        p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa: BLE001
        return -1, "실행 실패: %s" % e


def server_help():
    code, out = run_text([sys.executable, "server/icezero_server.py", "--help"], 20)
    if code != 0:
        return "<p class='warn'>--help 실행 실패(코드 %s)</p><pre class='code'>%s</pre>" % (code, esc(out[-800:]))
    return "<pre class='code'>%s</pre>" % esc(out.strip()[:2200])


def test_summary():
    import datetime
    code, out = run_text([sys.executable, "-m", "unittest", "discover", "-s", "tests"], 300)
    tail = [ln for ln in out.strip().splitlines() if ln.startswith("Ran ") or ln.startswith("OK") or ln.startswith("FAILED")]
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST")
    cls = "ok" if code == 0 else "bad"
    return "<p class='%s'>%s — %s</p>" % (cls, esc(" / ".join(tail) or "결과 줄 없음"), stamp) + \
        ("" if code == 0 else "<pre class='code'>%s</pre>" % esc(out[-1500:]))


SERVER_RUN_HTML = """<pre class='code'>cd suwon-makeathon-2026/icezero_model

# ① 흐름 익히기: LLM·보드 없이(규칙 해석, 수동 관측 버튼)
python3 server/icezero_server.py --no-llm --board-serial none

# ② 시연: 키는 환경변수로만 넘긴다(파일·화면에 적지 않는다)
CMD_API_KEY="$(omp token commandcode)" python3 server/icezero_server.py --board-serial auto

# 노트북 IP(제설차 config SERVER_IP에 넣는다)
ipconfig getifaddr en0</pre>"""


def build_html():
    mrows = [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in marker_table_rows()]
    car_rows = cfg_rows(os.path.join(ROOT, "pico_car", "config.py"))
    half = (len(car_rows) + 1) // 2
    board_rows = cfg_rows(os.path.join(ROOT, "pico_board", "config.py"))
    bhalf = (len(board_rows) + 1) // 2
    css = open(os.path.join(HERE, "guide.css"), encoding="utf-8").read()
    body = open(os.path.join(HERE, "guide_body.html"), encoding="utf-8").read()
    repl = {
        "{{DEFS}}": DEFS,
        "{{COVER}}": "file://" + COVER_IMG,
        "{{SVG_SYSTEM}}": svg_system(),
        "{{SVG_PLAN}}": svg_plan_view(),
        "{{SVG_MARKER}}": svg_marker_detail(),
        "{{MARKER_TABLE_A}}": table(["#", "종류", "차로", "중심 x", "중심 y", "비고"], mrows[:9], "tight"),
        "{{MARKER_TABLE_B}}": table(["#", "종류", "차로", "중심 x", "중심 y", "비고"], mrows[9:], "tight"),
        "{{SVG_CUT}}": svg_cut_layout(),
        "{{SVG_PARTS}}": svg_parts_detail(),
        "{{SVG_BRIDGE}}": svg_bridge_section(),
        "{{SVG_CAR}}": svg_car_layout(),
        "{{SVG_WIRE_CAR}}": svg_wiring_car(),
        "{{SVG_WIRE_BOARD}}": svg_wiring_board(),
        "{{LAP_MM}}": "%d" % round(LAP_MM),
        "{{TAPE_M}}": "%.1f" % (LAP_MM / 1000 + 0.6),
        "{{EVAL}}": eval_block(),
        "{{SERVER_RUN}}": SERVER_RUN_HTML,
        "{{SERVER_HELP}}": server_help(),
        "{{CAR_CFG_A}}": cfg_table(car_rows[:half]),
        "{{CAR_CFG_B}}": cfg_table(car_rows[half:]),
        "{{BOARD_CFG_A}}": cfg_table(board_rows[:bhalf]),
        "{{BOARD_CFG_B}}": cfg_table(board_rows[bhalf:]),
        "{{TEST_SUMMARY}}": test_summary(),
        "{{CAR_EXTRA_FILES}}": " · hwtest.py" if HAS_HWTEST else "",
        "{{HWTEST}}": "<code>pico_car/hwtest.py</code>(Thonny에서 열고 실행)" if HAS_HWTEST else
                      "REPL에서 모터 핀을 직접 켜는 코드",
        "{{DIAG}}": "config.DIAG=True로 올리면 주행하지 않고 200ms마다 L·C·R, 거리, 버튼을 출력한다." if HAS_DIAG else
                    "REPL에서 <code>[Pin(n, Pin.IN).value() for n in (18,19,20)]</code>를 반복 실행한다.",
        "{{DASH}}": "file://" + DASH_IMG,
    }
    for k, v in repl.items():
        body = body.replace(k, v)
    return "<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'><title>ICE-ZERO 4차로 모형 구현 가이드</title><style>%s</style></head><body>%s</body></html>" % (css, body)


def main():
    page = build_html()
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(page)
    print("HTML:", OUT_HTML)
    if "--html-only" in sys.argv:
        return
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--print-to-pdf=" + OUT_PDF,
           "file://" + OUT_HTML]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("PDF:", OUT_PDF)


if __name__ == "__main__":
    main()
