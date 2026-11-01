#!/usr/bin/env python3
"""문서(md) → 인쇄용 PDF. 글꼴은 Pretendard, 그림(img/*.svg)은 한 쪽에 하나씩 크게 넣는다.

    python3 docs/build_design_pdf.py                       → docs/라즈베리파이_시스템_설계도.pdf (SYSTEM_DESIGN.md)
    python3 docs/build_design_pdf.py --doc base            → docs/제설기지_제설차_제작가이드.pdf (BASE_AND_CAR.md)

내용은 md 그대로다(문서가 기준). SVG는 HTML 안에 직접 넣어 같은 @font-face(Pretendard)를 쓰게 한다.
외부 라이브러리 없이 이 문서들에 쓰인 마크다운만 변환한다.
"""
import argparse
import datetime
import html
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONT = os.path.join(ROOT, "server", "static", "fonts", "PretendardVariable.woff2")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DOCS = {
    "design": {"src": "SYSTEM_DESIGN.md", "out": "라즈베리파이_시스템_설계도.pdf", "title": "라즈베리파이 시스템 설계도",
               "sub": "고색고 ICE-ZERO 자동 제설 모형 · 기지 Pico #1(USB) + 제설차 Pico #2(Wi-Fi) + 맥북 서버",
               "cover_img": "img/system.svg", "appendix": True},
    "base": {"src": "BASE_AND_CAR.md", "out": "제설기지_제설차_제작가이드.pdf", "title": "제설기지 · 제설차 제작 가이드",
             "sub": "사거리 보드(사진 기준) · 남쪽 제설기지 · 스텝모터 제설차 · 실측 기입표 · 조립 순서 · 보정",
             "cover_img": "img/board_v2.svg", "appendix": False},
    "real": {"src": "REAL_PARTS.md", "out": "실물부품_배선도_조립도.pdf", "title": "실물 부품 배선도 · 조립도",
             "sub": "키트 실물 모양 그대로 · 제설차 Pico #2 · 기지 Pico #1 · 선 색·핀 번호까지",
             "cover_img": "img/real_car_wiring.svg", "appendix": False},
}

CSS = """
@page { size: A4 landscape; margin: 11mm 13mm; }
:root { --deep:#012a4a; --yale:#013a63; --yale2:#01497c; --yale3:#014f86; --rich:#2a6f97; --cer:#2c7da0;
        --afb:#468faf; --steel:#61a5c2; --sky:#89c2d9; --light:#a9d6e5; }
* { box-sizing: border-box; }
body { font-family: 'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', sans-serif; color: #0f172a; font-size: 10pt; line-height: 1.45; margin: 0; }
h1 { font-size: 22pt; color: var(--deep); margin: 0 0 3mm; }
h2 { font-size: 15pt; color: #fff; background: var(--yale2); padding: 1.5mm 4mm; border-radius: 1.5mm; margin: 5mm 0 2.5mm; break-after: avoid; }
h3 { font-size: 12pt; color: var(--yale3); margin: 3.5mm 0 1.5mm; break-after: avoid; }
p { margin: 1.2mm 0; }
ul, ol { margin: 1mm 0 1mm 6mm; padding-left: 4mm; }
li { margin: 0.6mm 0; }
code { font-family: 'Pretendard Variable', Menlo, monospace; font-size: 9pt; background: #e8f1f6; color: var(--deep); padding: 0 1mm; border-radius: 1mm; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 3mm; font-size: 9.6pt; break-inside: avoid; }
th { background: var(--light); color: var(--deep); text-align: left; }
th, td { border: 1px solid #b8d4e3; padding: 1.2mm 2mm; vertical-align: top; }
tr:nth-child(even) td { background: #f3f8fb; }
.cover { height: 186mm; display: flex; flex-direction: column; break-after: page; }
.cover .band { background: var(--deep); color: #fff; border-radius: 3mm; padding: 6mm 8mm; }
.cover .band h1 { color: #fff; margin: 0; }
.cover .band .sub { color: var(--light); font-size: 12pt; margin-top: 2mm; }
.cover .body { display: grid; grid-template-columns: 1.6fr 1fr; gap: 6mm; margin-top: 5mm; flex: 1; min-height: 0; }
.cover .cimg { height: 132mm; border: 1px solid #b8d4e3; border-radius: 2mm; background: #fff; padding: 2mm; }
.cover .cimg svg { width: 100%; height: 100%; }
.toc { background: #eef6fa; border-left: 2mm solid var(--cer); border-radius: 2mm; padding: 4mm 5mm; font-size: 10.5pt; }
.toc ol { margin: 1mm 0 0 4mm; }
.figpage { break-before: page; break-after: page; height: 186mm; display: flex; flex-direction: column; }
.figpage .ft { font-size: 14pt; font-weight: 800; color: #fff; background: var(--yale3); padding: 1.5mm 4mm; border-radius: 1.5mm; }
.figpage .fb { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; padding-top: 3mm; }
.figpage img { max-width: 100%; max-height: 100%; object-fit: contain; }
.figpage .fb svg.isvg { width: 100%; height: 100%; }
.figpage .fc { font-size: 9pt; color: var(--yale3); text-align: right; }
.figpage .fn { font-size: 9.5pt; background: #eef6fa; border-left: 1.5mm solid var(--cer); border-radius: 1.5mm; padding: 1.5mm 3mm; margin-top: 2mm; }
.figpage .fn ul, .figpage .fn ol { margin: 0 0 0 4mm; }
.note { font-size: 9pt; color: #475569; }
"""


def inline(text):
    """`코드`, **굵게**, [링크](주소)만 변환한다. HTML은 먼저 이스케이프한다."""
    parts = re.split(r"(`[^`]*`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) >= 2:
            out.append("<code>%s</code>" % html.escape(part[1:-1]))
            continue
        s = html.escape(part)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", s)
        out.append(s)
    return "".join(out)


def svg_inline(path):
    """SVG 파일을 HTML 안에 넣을 수 있게 고친다. 고정 width/height를 빼서 쪽 크기에 맞춘다."""
    text = open(path, encoding="utf-8").read()
    text = re.sub(r"<\?xml[^>]*\?>", "", text)
    m = re.search(r"<svg\b[^>]*>", text)
    if not m:
        return text
    tag = re.sub(r'\s(width|height)="[^"]*"', "", m.group(0))
    tag = tag.replace("<svg", '<svg class="isvg" preserveAspectRatio="xMidYMid meet"', 1)
    return text[:m.start()] + tag + text[m.end():]


def figure(alt, src, caption="", notes=""):
    path = os.path.join(HERE, src)
    if src.lower().endswith(".svg") and os.path.exists(path):
        body = svg_inline(path)
    else:
        body = '<img src="%s" alt="%s">' % (html.escape(src), html.escape(alt))
    return ('<section class="figpage"><div class="ft">%s</div><div class="fb">%s</div>%s'
            '<div class="fc">%s</div></section>') % (html.escape(alt), body,
                                                   ('<div class="fn">%s</div>' % notes) if notes else "", html.escape(caption))


def convert(md):
    """이 문서에 쓰인 마크다운(제목·문단·목록·표·이미지·코드 블록)을 HTML로 바꾼다."""
    lines = md.splitlines()
    out, i = [], 0
    para = []
    figures = []
    seen_h2 = [False]
    pending_title = [None]

    def flush_para():
        if para:
            out.append("<p>%s</p>" % inline(" ".join(x.strip() for x in para)))
            del para[:]

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            flush_para()
            i += 1
            continue
        if s.startswith("```"):
            flush_para()
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                buf.append(lines[j])
                j += 1
            out.append("<pre><code>%s</code></pre>" % html.escape("\n".join(buf)))
            i = j + 1
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", s)
        if m:
            flush_para()
            level = len(m.group(1))
            if level == 2:
                seen_h2[0] = True
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if level > 1 and j < len(lines) and re.match(r"^!\[", lines[j].strip()):
                pending_title[0] = m.group(2)  # 제목 바로 뒤가 그림이면 제목을 그림 쪽으로 옮긴다(제목만 남는 쪽 방지)
            elif level > 1:  # h1은 표지가 대신한다
                out.append("<h%d>%s</h%d>" % (level, inline(m.group(2)), level))
            i += 1
            continue
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", s)
        if m:
            flush_para()
            figures.append((m.group(1), m.group(2)))
            i += 1
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            notes = ""
            if j < len(lines) and re.match(r"^([-*]|\d+\.)\s+", lines[j]):  # 그림 바로 뒤 목록은 그림 쪽에 붙인다
                items, i = take_list(lines, j)
                notes = render_list(items)
            title = m.group(1)
            if pending_title[0]:
                alt = m.group(1)
                # 그림 이름이 절 제목에 이미 들어 있으면 절 제목만 쓴다(같은 말 반복 방지)
                title = pending_title[0] if (not alt or alt in pending_title[0]) else "%s — %s" % (pending_title[0], alt)
                pending_title[0] = None
            out.append(figure(title, m.group(2), "docs/%s" % m.group(2), notes))
            continue
        if s.startswith("|"):
            flush_para()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[1:] if not all(re.match(r"^:?-+:?$", c) for c in r)]
            t = "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
                "".join("<th>%s</th>" % inline(c) for c in head),
                "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r) for r in body))
            out.append(t)
            continue
        if re.match(r"^(\s*)([-*]|\d+\.)\s+", line):
            flush_para()
            items, i = take_list(lines, i)
            out.append(render_list(items))
            continue
        if not seen_h2[0]:  # 첫 절 앞 소개 문단은 표지에 있다
            i += 1
            continue
        para.append(s)
        i += 1
    flush_para()
    return "\n".join(out), figures


def take_list(lines, i):
    """i부터 이어지는 목록을 [(들여쓰기, 'ul'|'ol', 글)]로 모은다. 들여쓴 이어지는 줄은 앞 항목에 붙인다."""
    items = []
    while i < len(lines):
        lm = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", lines[i])
        if lm:
            items.append([len(lm.group(1)), "ol" if lm.group(2)[0].isdigit() else "ul", lm.group(3)])
            i += 1
        elif lines[i].strip() and lines[i].startswith(" ") and items:
            items[-1][2] += " " + lines[i].strip()
            i += 1
        else:
            break
    return items, i


def render_list(items):
    html_out, stack = [], []
    for indent, kind, text in items:
        while stack and stack[-1][0] > indent:
            html_out.append("</li></%s>" % stack.pop()[1])
        if stack and stack[-1][0] == indent:
            html_out.append("</li><li>%s" % inline(text))
        else:
            stack.append((indent, kind))
            html_out.append("<%s><li>%s" % (kind, inline(text)))
    while stack:
        html_out.append("</li></%s>" % stack.pop()[1])
    return "".join(html_out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="md → PDF(Pretendard)")
    ap.add_argument("--doc", choices=sorted(DOCS), default="design")
    args = ap.parse_args(argv)
    spec = DOCS[args.doc]
    src = os.path.join(HERE, spec["src"])
    out_pdf = os.path.join(HERE, spec["out"])
    out_html = os.path.join(HERE, "_print_%s.html" % args.doc)
    md = open(src, encoding="utf-8").read()
    body, figures = convert(md)
    toc = "".join("<li>%s</li>" % html.escape(t) for t in re.findall(r"^## (.+)$", md, re.M))
    if spec["appendix"]:
        toc += "<li>부록: 모니터 화면 · 참고 지도</li>"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST")
    cover_svg = svg_inline(os.path.join(HERE, spec["cover_img"])) if os.path.exists(os.path.join(HERE, spec["cover_img"])) else ""
    cover = """<section class="cover">
<div class="band"><h1>%s</h1><div class="sub">%s · %s</div></div>
<div class="body"><div class="cimg">%s</div>
<div><div class="toc"><b>차례</b><ol>%s</ol></div>
<p class="note">기준 문서는 CONTRACT.md다. 이 PDF는 docs/%s를 그대로 옮겨 만든 것이다. 그림 원본은 docs/img/*.svg다.
도로는 임의 도로(모형)이고, 보드 치수는 사진 추정값이라 실측해서 config에 넣는다. 실물 배선·주행은 아직 검증하지 않았다.</p></div></div>
</section>""" % (html.escape(spec["title"]), html.escape(spec["sub"]), now, cover_svg, toc, spec["src"])
    appendix = ""
    if spec["appendix"]:
        appendix = (figure("부록 A. 모니터 화면(/monitor, 1920×1080)", "img/monitor.png", "패드 사진을 규칙과 Claude가 판정한 직후 캡처") +
                    figure("부록 B. 참고: 고색고 주변 실제 도로 위험도(모형 도로와 별개)", "img/gosaek_map.svg",
                           "OSM 기반 상대 우선순위 · 모형 갈래는 임의 도로(cross_arms.json)"))
    font_url = "file://" + FONT
    css = ("@font-face { font-family: 'Pretendard Variable'; src: url('%s') format('woff2'); font-weight: 45 920; }\n" % font_url) + CSS
    page = ("<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'><title>%s</title>"
            "<style>%s</style></head><body>%s%s%s</body></html>") % (html.escape(spec["title"]), css, cover, body, appendix)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(page)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--print-to-pdf=" + out_pdf,
                    "file://" + out_html], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.remove(out_html)
    print("PDF:", out_pdf, "| 그림", len(figures) + (2 if spec["appendix"] else 0), "장")


if __name__ == "__main__":
    sys.exit(main())
