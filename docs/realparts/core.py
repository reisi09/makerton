"""실물 부품 도면의 공통 도구. 모든 부품은 '1단위 = 1mm' 지역 좌표로 그리고 place()로 배치한다.

부품 함수는 Part를 돌려준다.
    Part.svg   : 지역 좌표(mm)로 그린 SVG 조각(원점 = 부품 왼쪽 위)
    Part.w, h  : 부품 외곽 크기(mm, 실제 치수)
    Part.pins  : {"핀 이름": (x_mm, y_mm)} 지역 좌표. 선을 꽂는 점이다.

place(part, x, y, scale, rot)는 화면 좌표(px)에 놓고 (svg, 절대 핀 좌표)를 돌려준다.
rot는 0/90/180/270(시계 방향)만 쓴다. 글꼴은 Pretendard다.
"""
import html
import math

FONT = "'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', sans-serif"
MONO = "'Pretendard Variable', Menlo, monospace"

# 실물에 가까운 색
PCB_GREEN = "#1f7a3a"
PCB_BLUE = "#1d5fa8"
PCB_BLACK = "#1f2329"
PCB_RED = "#b3261e"
GOLD = "#d8b45a"
SILVER = "#c9ced6"
HEADER = "#141414"
SILK = "#f5f5f0"
WIRE = {  # 점퍼 색(실물 관례)
    "red": "#d62f2f", "black": "#202020", "brown": "#7a4a22", "orange": "#f08a24", "yellow": "#f2c230",
    "green": "#2f9e44", "blue": "#2f6fd6", "purple": "#8a4fd8", "gray": "#8a8f98", "white": "#f2f2f2",
    "pink": "#f28bb8",
}


def esc(s):
    return html.escape(str(s))


class Part(object):
    def __init__(self, name, w, h, svg="", pins=None):
        self.name = name
        self.w = float(w)
        self.h = float(h)
        self.svg = svg
        self.pins = dict(pins or {})


# ── 지역 좌표(mm) 그리기 도구 ──────────────────────────────────────────
def rect(x, y, w, h, fill="none", stroke="none", sw=0.2, rx=0, extra=""):
    return '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="%.2f" fill="%s" stroke="%s" stroke-width="%.2f" %s/>' % (
        x, y, w, h, rx, fill, stroke, sw, extra)


def circle(cx, cy, r, fill="none", stroke="none", sw=0.2, extra=""):
    return '<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s" stroke="%s" stroke-width="%.2f" %s/>' % (
        cx, cy, r, fill, stroke, sw, extra)


def line(x1, y1, x2, y2, stroke="#000", sw=0.2, extra=""):
    return '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="%.2f" %s/>' % (
        x1, y1, x2, y2, stroke, sw, extra)


def path(d, fill="none", stroke="#000", sw=0.2, extra=""):
    return '<path d="%s" fill="%s" stroke="%s" stroke-width="%.2f" %s/>' % (d, fill, stroke, sw, extra)


def text(x, y, s, size=1.6, fill=SILK, anchor="middle", weight=700, rot=0, font=FONT):
    tr = ' transform="rotate(%d %.2f %.2f)"' % (rot, x, y) if rot else ""
    return '<text x="%.2f" y="%.2f" font-size="%.2f" text-anchor="%s" font-weight="%d" fill="%s" font-family="%s"%s>%s</text>' % (
        x, y, size, anchor, weight, fill, font, tr, esc(s))


def mount_hole(cx, cy, r=1.6, ring=GOLD):
    return circle(cx, cy, r + 0.6, fill=ring) + circle(cx, cy, r, fill="#ffffff", stroke="#999", sw=0.1)


def pin_header(x, y, n, pitch=2.54, vertical=False, female=False, names=None, label_side=None, label_color=SILK, label_size=1.3):
    """핀 헤더 n개. 반환 (svg, {이름: (x,y)}). 각 핀 중심 좌표를 준다(x,y는 첫 핀 중심)."""
    out, pins = [], {}
    for i in range(n):
        cx = x + (0 if vertical else i * pitch)
        cy = y + (i * pitch if vertical else 0)
        if female:
            out.append(rect(cx - 1.27, cy - 1.27, 2.54, 2.54, fill=HEADER, stroke="#000", sw=0.1))
            out.append(rect(cx - 0.4, cy - 0.4, 0.8, 0.8, fill="#000"))
        else:
            out.append(rect(cx - 1.27, cy - 1.27, 2.54, 2.54, fill=HEADER, stroke="#000", sw=0.1))
            out.append(rect(cx - 0.32, cy - 0.32, 0.64, 0.64, fill=GOLD))
        name = names[i] if names and i < len(names) else str(i + 1)
        pins[name] = (cx, cy)
        if names and label_side:
            dx, dy, anchor, rot = 0, 0, "middle", 0
            if label_side == "top":
                dy = -1.9
            elif label_side == "bottom":
                dy = 2.9
            elif label_side == "left":
                dx, anchor = -1.8, "end"
                dy = 0.45
            elif label_side == "right":
                dx, anchor = 1.8, "start"
                dy = 0.45
            out.append(text(cx + dx, cy + dy, name, label_size, label_color, anchor, 700, rot))
    return "".join(out), pins


# ── 배치 ────────────────────────────────────────────────────────────
def _rot_point(px, py, w, h, rot):
    if rot == 0:
        return px, py
    if rot == 90:
        return h - py, px
    if rot == 180:
        return w - px, h - py
    if rot == 270:
        return py, w - px
    raise ValueError("rot는 0/90/180/270만")


def place(part, x, y, scale=4.0, rot=0, title=None, title_side="top", title_size=13, title_color="#012a4a"):
    """부품을 화면 좌표 (x,y)(회전 후 외곽의 왼쪽 위)에 scale px/mm로 놓는다."""
    w, h = part.w, part.h
    if rot == 0:
        tf = "translate(%.2f %.2f) scale(%.4f)" % (x, y, scale)
    elif rot == 90:
        tf = "translate(%.2f %.2f) scale(%.4f) translate(%.2f 0) rotate(90)" % (x, y, scale, h)
    elif rot == 180:
        tf = "translate(%.2f %.2f) scale(%.4f) translate(%.2f %.2f) rotate(180)" % (x, y, scale, w, h)
    elif rot == 270:
        tf = "translate(%.2f %.2f) scale(%.4f) translate(0 %.2f) rotate(270)" % (x, y, scale, w)
    else:
        raise ValueError("rot는 0/90/180/270만")
    out = ['<g transform="%s">%s</g>' % (tf, part.svg)]
    pins = {}
    for name, (px, py) in part.pins.items():
        rx, ry = _rot_point(px, py, w, h, rot)
        pins[name] = (x + rx * scale, y + ry * scale)
    bw, bh = (w, h) if rot in (0, 180) else (h, w)
    if title:
        if title_side == "top":
            out.append(text_px(x + bw * scale / 2, y - 8, title, title_size, title_color))
        else:
            out.append(text_px(x + bw * scale / 2, y + bh * scale + title_size + 6, title, title_size, title_color))
    return "".join(out), pins


def size_px(part, scale=4.0, rot=0):
    return (part.w * scale, part.h * scale) if rot in (0, 180) else (part.h * scale, part.w * scale)


def text_px(x, y, s, size=13, fill="#012a4a", anchor="middle", weight=800):
    return '<text x="%.1f" y="%.1f" font-size="%s" text-anchor="%s" font-weight="%d" fill="%s" font-family="%s">%s</text>' % (
        x, y, size, anchor, weight, fill, FONT, esc(s))


def wire(points, color="red", width=3.2, dupont=True, label=None, label_at=0.5):
    """점퍼선. points=[(x,y),...] 화면 좌표. 모서리는 둥글게 꺾는다. 양끝에 듀폰 커넥터를 그린다."""
    col = WIRE.get(color, color)
    pts = list(points)
    d = "M %.1f %.1f" % pts[0]
    r = 10.0
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        l1 = math.hypot(x1 - x0, y1 - y0) or 1
        l2 = math.hypot(x2 - x1, y2 - y1) or 1
        rr = min(r, l1 / 2, l2 / 2)
        ax, ay = x1 - (x1 - x0) / l1 * rr, y1 - (y1 - y0) / l1 * rr
        bx, by = x1 + (x2 - x1) / l2 * rr, y1 + (y2 - y1) / l2 * rr
        d += " L %.1f %.1f Q %.1f %.1f %.1f %.1f" % (ax, ay, x1, y1, bx, by)
    d += " L %.1f %.1f" % pts[-1]
    out = ['<path d="%s" fill="none" stroke="#00000055" stroke-width="%.1f" stroke-linecap="round" stroke-linejoin="round" transform="translate(1 1.5)"/>' % (d, width + 1.2),
           '<path d="%s" fill="none" stroke="%s" stroke-width="%.1f" stroke-linecap="round" stroke-linejoin="round"/>' % (d, col, width)]
    if dupont:
        for (x, y) in (pts[0], pts[-1]):
            out.append('<rect x="%.1f" y="%.1f" width="7" height="7" rx="1.2" fill="#1a1a1a" stroke="%s" stroke-width="1.2"/>' % (x - 3.5, y - 3.5, col))
    if label:
        # 가장 긴 구간 가운데에 라벨
        best, bi = -1, 0
        for i in range(len(pts) - 1):
            L = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            if L > best:
                best, bi = L, i
        (x0, y0), (x1, y1) = pts[bi], pts[bi + 1]
        lx, ly = x0 + (x1 - x0) * label_at, y0 + (y1 - y0) * label_at
        tw = 7.2 * len(label) + 10
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="17" rx="8" fill="#ffffff" stroke="%s" stroke-width="1.5"/>' % (lx - tw / 2, ly - 8.5, tw, col))
        out.append(text_px(lx, ly + 4.5, label, 11, "#012a4a", "middle", 800))
    return "".join(out)


def svg_doc(width, height, body, title="", bg="#ffffff"):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" font-family="%s">'
            '<title>%s</title><rect width="100%%" height="100%%" fill="%s"/>%s</svg>') % (
        width, height, width, height, FONT, esc(title), bg, body)
