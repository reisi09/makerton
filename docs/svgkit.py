"""도면용 SVG 도우미(단위는 도면 좌표, 보통 mm). 가이드 PDF와 표지 그림이 함께 쓴다."""
import html


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


def P(d, fill="none", stroke="#111", sw=2, extra=""):
    return '<path d="%s" fill="%s" stroke="%s" stroke-width="%s" %s/>' % (d, fill, stroke, sw, extra)


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


DEFS = """<svg width="0" height="0" style="position:absolute"><defs>
<marker id="arrE" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#1d4ed8"/></marker>
<marker id="arrS" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10 0 L0 5 L10 10 z" fill="#1d4ed8"/></marker>
<marker id="flow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#334155"/></marker>
<marker id="ord" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#2563eb"/></marker>
<pattern id="dots" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="4" cy="4" r="2" fill="#94a3b8"/></pattern>
<pattern id="waves" width="40" height="18" patternUnits="userSpaceOnUse"><path d="M0 9 q10 -7 20 0 t20 0" fill="none" stroke="#3b82f6" stroke-width="2"/></pattern>
<pattern id="stripes" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="14" fill="#e11d48"/><rect x="7" width="7" height="14" fill="#fff"/></pattern>
<filter id="glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs></svg>"""

LEFT_PINS = {1: "GP0", 2: "GP1", 3: "GND", 4: "GP2", 5: "GP3", 6: "GP4", 7: "GP5", 8: "GND", 9: "GP6", 10: "GP7",
             11: "GP8", 12: "GP9", 13: "GND", 14: "GP10", 15: "GP11", 16: "GP12", 17: "GP13", 18: "GND", 19: "GP14",
             20: "GP15"}
RIGHT_PINS = {40: "VBUS", 39: "VSYS", 38: "GND", 37: "3V3_EN", 36: "3V3", 35: "ADC_VREF", 34: "GP28", 33: "AGND",
              32: "GP27", 31: "GP26", 30: "RUN", 29: "GP22", 28: "GND", 27: "GP21", 26: "GP20", 25: "GP19",
              24: "GP18", 23: "GND", 22: "GP17", 21: "GP16"}


def pico(x, y, used, title):
    """피코 핀 배치(위에서 본 모습, USB 위). 반환: (svg, 핀 좌표 dict). Pico W·Pico 2 W 핀 배치 동일."""
    o, pos = [], {}
    w, step = 230, 25
    h = 20 * step + 40
    o.append(Rc(x, y, w, h, fill="#166534", stroke="#052e16", sw=3, rx=10))
    o.append(Rc(x + 85, y - 18, 60, 26, fill="#9ca3af", stroke="#374151", sw=2, rx=4))
    o.append(T(x + w / 2, y - 26, "USB", 14, weight=800))
    o.append(T(x + w / 2, y + h + 30, title, 22, weight=800, fill="#166534"))
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
    """모듈 상자. pins=[이름...] → 상자 가장자리(side)의 핀 좌표."""
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


def table(head, rows, cls=""):
    h = "".join("<th>%s</th>" % esc(c) for c in head)
    b = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)
    return '<table class="%s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (cls, h, b)
