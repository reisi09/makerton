"""등굣길 위험 조사관 파이프라인 슬라이드(HTML+SVG) 생성기.

    python3 slides/build_deck.py /tmp/pipeline_deck.html
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --no-pdf-header-footer \
        --print-to-pdf="slides/등굣길_위험_조사관_파이프라인.pdf" file:///tmp/pipeline_deck.html
"""
import html
import math
import sys

OUT = sys.argv[1]

C = {
    "ink": "#1b2433", "sub": "#5b6476", "mute": "#8a94a6", "line": "#d7dce5", "bg": "#f5f7fb",
    "teal": "#119e86", "teal_l": "#e3f6f1", "blue": "#2f6fde", "blue_l": "#e6eefc",
    "orange": "#ec7a14", "orange_l": "#fdf0e3", "purple": "#7c4dde", "purple_l": "#efe8fc",
    "red": "#e0393e", "red_l": "#fde8e8", "navy": "#0f2340", "green": "#1f9d55",
}
TOTAL = 13


def esc(s):
    return html.escape(str(s))


def T(x, y, s, size=18, weight=500, fill=None, anchor="start", family=None, italic=False):
    fill = fill or C["ink"]
    fam = ' font-family="Menlo, monospace"' if family == "mono" else ""
    it = ' font-style="italic"' if italic else ""
    lines = str(s).split("\n")
    if len(lines) == 1:
        return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{fam}{it}>{esc(s)}</text>'
    lh = size * 1.32
    spans = "".join(f'<tspan x="{x}" dy="{0 if i == 0 else lh:.1f}">{esc(l)}</tspan>' for i, l in enumerate(lines))
    return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{fam}{it}>{spans}</text>'


def R(x, y, w, h, fill="#fff", stroke=None, rx=14, sw=2, dash=None, opacity=None):
    st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    da = f' stroke-dasharray="{dash}"' if dash else ""
    op = f' opacity="{opacity}"' if opacity is not None else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{st}{da}{op}/>'


def A(x1, y1, x2, y2, color="gray", sw=2.5, dash=None, both=False):
    col = {"gray": "#5b6476", "teal": C["teal"], "blue": C["blue"], "orange": C["orange"], "purple": C["purple"], "red": C["red"]}[color]
    da = f' stroke-dasharray="{dash}"' if dash else ""
    ms = f' marker-start="url(#ah-{color})"' if both else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="{sw}"{da} marker-end="url(#ah-{color})"{ms}/>'


def P(d, color="gray", sw=2.5, dash=None, end=True):
    col = {"gray": "#5b6476", "teal": C["teal"], "blue": C["blue"], "orange": C["orange"], "purple": C["purple"], "red": C["red"]}[color]
    da = f' stroke-dasharray="{dash}"' if dash else ""
    me = f' marker-end="url(#ah-{color})"' if end else ""
    return f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{sw}"{da}{me}/>'


def pill(x, y, s, fill, color, size=13):
    w = 14 + len(s) * size * 0.92
    return R(x, y, w, size + 12, fill=fill, rx=(size + 12) / 2) + T(x + w / 2, y + size + 3, s, size, 700, color, "middle")


def svg(body, w=1152, h=540):
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">{body}</svg>'


def slide(n, kicker, title, content, note=None):
    nt = f'<div class="note">{note}</div>' if note else ""
    return f'''<section class="slide">
<div class="kicker">{esc(kicker)}</div><h1>{esc(title)}</h1>
<div class="content">{content}</div>{nt}
<div class="footer"><span>등굣길 위험 조사관 · 피코 WH × Command Code 파이프라인</span><span>{n} / {TOTAL}</span></div>
</section>'''


slides = []

# 1. 표지 ---------------------------------------------------------------
stripes = "".join(R(760 + i * 62, 0, 36, 720, fill="#ffffff", rx=0, opacity=0.07) for i in range(9))
slides.append(f'''<section class="slide cover">
<svg class="cover-bg" width="1280" height="720">{stripes}
<circle cx="1040" cy="430" r="150" fill="none" stroke="#ec7a14" stroke-width="3" opacity="0.55"/>
<circle cx="1040" cy="430" r="96" fill="none" stroke="#119e86" stroke-width="3" opacity="0.6"/>
<circle cx="1040" cy="430" r="44" fill="#ec7a14" opacity="0.9"/>
</svg>
<div class="cover-text">
<div class="cover-kicker">2026 수원고교 피지컬 AI 메이커톤</div>
<div class="cover-title">등굣길 위험 조사관</div>
<div class="cover-sub">피코 WH × Command Code LLM 파이프라인</div>
<div class="cover-desc">학교 앞 횡단보도의 "차가 안 보여요"를<br>센서로 측정하고, LLM이 가설을 세워 증거로 확인한다</div>
<div class="cover-meta">수원시 민원 데이터 기반 · Claude × GPT-6-Astra 토론 결과 · 2026-10-31</div>
</div></section>''')

# 2. 한 장 요약 -----------------------------------------------------------
cards = [
    ("문제", C["red"], C["red_l"], "보호자 제보가 서로 엇갈린다", "“오른쪽 트럭 때문에 안 보여요”\n“아니에요, 왼쪽 차가 빨라요”\n어느 쪽, 언제, 왜 위험한지\n측정한 사람이 없다"),
    ("해결", C["teal"], C["teal_l"], "측정하는 조사관", "피코: 아이 눈높이 시야선이\n가려지는지 직접 측정·즉시 경고\nLLM: 제보로 가설을 세우고\n가려낼 실험을 골라 증거로 판정"),
    ("근거", C["blue"], C["blue_l"], "수원 민원 6개 연도", "권익위 수원 키워드 2019~2025\n어린이 보호구역·스쿨존 사고·\n안전 통학·횡단보도 주정차 신고·\n보행자 안전 (2023년은 없음)"),
    ("현재 상태", C["purple"], C["purple_l"], "기본 통신·AI는 실측", "피코↔노트북 통신·사람 승인·\nCommand Code 호출은\n2026-10-31 실호출로 확인\n가설 루프·모형·시야선 센서는\n새로 구현할 설계"),
]
body = ""
for i, (k, col, light, head, txt) in enumerate(cards):
    x = i * 290
    body += R(x, 0, 270, 300, fill=light, rx=18) + R(x, 0, 270, 10, fill=col, rx=4)
    body += T(x + 24, 52, k, 17, 800, col) + T(x + 24, 92, head, 22, 800)
    body += T(x + 24, 140, txt, 17, 500, C["sub"])
body += R(0, 330, 1150, 84, fill=C["navy"], rx=18)
body += T(575, 368, "센서가 측정하고, LLM은 무엇을 측정할지 고르고 결과로 판단을 고치며, 사람이 실행을 승인한다", 20, 800, "#fff", "middle")
body += T(575, 396, "경고는 피코의 규칙이 즉시 켠다 — 인터넷이 끊겨도 계속", 16, 600, "#ffb86b", "middle")
slides.append(slide(2, "SUMMARY", "한 장 요약", svg(body, 1152, 420)))

# 3. 근거 -----------------------------------------------------------------
years = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
rows = [
    ("어린이 교통사고", {2019: 2059}),
    ("어린이 보호구역", {2020: 13975, 2021: 7368, 2022: 5933, 2024: 1411, 2025: 1008}),
    ("스쿨존 사고", {2021: 6439}),
    ("안전 통학", {2022: 8692}),
    ("횡단보도 불법 주정차 신고", {2024: 54662, 2025: 42543}),
    ("보행자 안전", {2025: 769}),
]
x0, cw, y0, rh = 250, 116, 46, 66
body = ""
for j, yv in enumerate(years):
    cx = x0 + j * cw + cw / 2
    if yv == 2023:
        body += R(x0 + j * cw + 6, 20, cw - 12, rh * len(rows) + 30, fill="#f1f2f6", rx=10)
        body += T(cx, y0 + rh * len(rows) + 34, "100위 밖", 13, 600, C["mute"], "middle")
    body += T(cx, 34, str(yv), 18, 800, C["ink"], "middle")
for i, (name, vals) in enumerate(rows):
    cy = y0 + 30 + i * rh
    body += f'<line x1="0" y1="{cy + rh / 2 - 4}" x2="{x0 + cw * 7}" y2="{cy + rh / 2 - 4}" stroke="{C["line"]}" stroke-width="1"/>'
    body += T(0, cy + 6, name, 17, 700)
    for j, yv in enumerate(years):
        if yv in vals:
            v = vals[yv]
            r = 5 + 21 * math.sqrt(v / 54662)
            cx = x0 + j * cw + cw / 2
            body += f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="{C["blue"]}" opacity="0.85"/>'
            body += T(cx + r + 6, cy + 5, f"{v:,}", 13, 700, C["blue"])
body += T(0, y0 + rh * len(rows) + 70, "원 크기 = 문서빈도(df)의 제곱근. df는 키워드가 들어간 민원 문서 수이며 신고 건수가 아니다. 키워드끼리 더하지 않는다.", 14, 500, C["sub"])
body += T(0, y0 + rh * len(rows) + 94, "출처: 국민권익위원회 민원 빅데이터, 수원시(o_area=수원시) 연도별 상위 100 키워드. 2020년은 어린이 보호구역 관련 법 개정 영향일 수 있다[추정].", 14, 500, C["sub"])
slides.append(slide(3, "EVIDENCE", "근거: 수원 민원 키워드에 6개 연도 반복", svg(body, 1152, 560)))

# 4. 전체 파이프라인 ---------------------------------------------------------
b = ""
# 현장 그룹
b += R(0, 40, 300, 380, fill=C["teal_l"], rx=20) + T(24, 76, "현장 모형", 20, 800, C["teal"])
b += R(24, 96, 252, 70, fill="#fff", stroke=C["teal"]) + T(150, 126, "센서", 18, 800, anchor="middle") + T(150, 150, "초음파 · 거리 · 적외선 빔", 14, 500, C["sub"], "middle")
b += A(150, 166, 150, 196, "teal")
b += R(24, 198, 252, 92, fill="#fff", stroke=C["teal"], sw=3) + T(150, 232, "피코 WH", 21, 800, anchor="middle") + T(150, 258, "로컬 규칙: 대기 + 시야 가림", 14, 600, C["teal"], "middle") + T(150, 278, "→ 즉시 판단", 14, 500, C["sub"], "middle")
b += A(150, 290, 150, 320, "teal")
b += R(24, 322, 252, 70, fill="#fff", stroke=C["red"]) + T(150, 352, "경고 LED", 18, 800, C["red"], "middle") + T(150, 376, "운전자용 · 보행자용", 14, 500, C["sub"], "middle")
# 노트북
b += R(410, 40, 320, 380, fill=C["blue_l"], rx=20) + T(434, 76, "노트북 중계 서버", 20, 800, C["blue"])
for i, (h, s) in enumerate([("상태·실험 관리", "노드 상태, 제보, 측정 결과 보관"), ("허용 실험 검사", "LLM 제안이 목록 안인지 확인"), ("API 키 보관", "환경변수에만 · 기기에 두지 않음")]):
    yy = 96 + i * 104
    b += R(434, yy, 272, 84, fill="#fff", stroke=C["blue"]) + T(570, yy + 34, h, 18, 800, anchor="middle") + T(570, yy + 60, s, 14, 500, C["sub"], "middle")
# Command Code
b += R(840, 40, 312, 380, fill=C["orange_l"], rx=20) + T(864, 76, "Command Code API", 20, 800, C["orange"])
b += R(864, 100, 264, 132, fill="#fff", stroke=C["orange"]) + T(996, 132, "typesafe/jev", 19, 800, anchor="middle") + T(996, 158, "/systemone · 상태 분류(확률)", 14, 500, C["sub"], "middle") + T(996, 196, "실측 0.6~2.2초", 15, 800, C["green"], "middle")
b += R(864, 256, 264, 140, fill="#fff", stroke=C["orange"]) + T(996, 288, "deepseek-v4.1-flash", 19, 800, anchor="middle") + T(996, 314, "/chat/completions", 14, 500, C["sub"], "middle") + T(996, 336, "가설 · 실험 선택 · 브리핑", 14, 600, C["orange"], "middle") + T(996, 374, "실측 4.7~7.2초 (추론 low)", 15, 800, C["green"], "middle")
# 화살표 현장↔노트북
b += A(276, 228, 432, 160, "blue") + T(300, 168, "USB @@REQ", 14, 800, C["blue"]) + T(300, 186, "상태 요약(1초)", 13, 500, C["sub"])
b += A(432, 300, 278, 262, "blue") + T(300, 318, "@@RES 측정 명령", 14, 800, C["blue"]) + T(300, 336, "cmd_id로 중복 방지", 13, 500, C["sub"])
b += A(732, 166, 862, 166, "orange", both=True) + T(797, 154, "판단 요청", 13, 800, C["orange"], "middle")
b += A(732, 326, 862, 326, "orange", both=True) + T(797, 314, "가설·브리핑 요청", 13, 800, C["orange"], "middle")
b += T(797, 248, "HTTPS", 13, 800, C["mute"], "middle")
# 대시보드
b += R(410, 450, 320, 76, fill=C["purple_l"], stroke=C["purple"], rx=16) + T(570, 482, "대시보드 · 사람 승인", 19, 800, C["purple"], "middle") + T(570, 506, "가설·실험·브리핑은 승인 뒤에만 실행", 14, 500, C["sub"], "middle")
b += A(570, 420, 570, 448, "purple", both=True)
b += T(864, 470, "실측: 2026-10-31, 스타터 기본 기능(jev 판단·", 13, 500, C["mute"]) + T(864, 490, "chat 제안). 가설 루프 프롬프트는 미측정.", 13, 500, C["mute"])
slides.append(slide(4, "ARCHITECTURE", "전체 파이프라인", svg(b, 1152, 540)))

# 5. 두 속도의 고리 ----------------------------------------------------------
def cycle(cx, cy, r, labels, color, light):
    out = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="3" stroke-dasharray="2 9" stroke-linecap="round"/>'
    n = len(labels)
    for i, lab in enumerate(labels):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        x, y = cx + r * math.cos(ang), cy + r * math.sin(ang)
        w = 26 + len(lab) * 15
        out += R(x - w / 2, y - 21, w, 42, fill="#fff", stroke=color, rx=21) + T(x, y + 6, lab, 16, 800, color, "middle")
    return out


b = R(0, 0, 548, 520, fill=C["teal_l"], rx=22) + T(28, 44, "빠른 고리 · 기기 안", 22, 800, C["teal"])
b += cycle(274, 250, 130, ["센서 읽기", "로컬 규칙", "경고 LED"], C["teal"], C["teal_l"])
b += T(274, 258, "0.5초 주기", 22, 800, C["teal"], "middle")
b += T(28, 440, "· 인터넷이 끊겨도 계속 동작", 16, 600, C["ink"]) + T(28, 466, "· LLM 응답을 기다리지 않음", 16, 600, C["ink"]) + T(28, 492, "· 스타터 루프 주기 0.5초(더 줄일 수 있음)", 16, 600, C["ink"])
b += R(604, 0, 548, 520, fill=C["orange_l"], rx=22) + T(632, 44, "느린 고리 · LLM", 22, 800, C["orange"])
b += cycle(878, 250, 150, ["제보", "가설", "실험 선택", "사람 승인", "피코 측정", "판정"], C["orange"], C["orange_l"])
b += T(878, 248, "수 초 단위", 22, 800, C["orange"], "middle") + T(878, 274, "(실측 4.7~7.2초)", 14, 600, C["sub"], "middle")
b += T(632, 466, "· 실험·브리핑은 사람 승인 뒤에만", 16, 600, C["ink"]) + T(632, 492, "· 경고를 결정하지 않는다", 16, 600, C["ink"])
b += R(476, 228, 200, 44, fill=C["navy"], rx=22) + T(576, 256, "역할 분리", 17, 800, "#fff", "middle")
slides.append(slide(5, "TWO LOOPS", "두 속도의 고리: 경고는 기기, 판단은 LLM", svg(b, 1152, 540)))

# 6. LLM 가설 고리 ----------------------------------------------------------
steps = [("1", "제보 입력", "성인이 검수한 비식별 문장"), ("2", "경쟁 가설", "가설마다 예상 관측·기각 조건"), ("3", "실험 선택", "허용 목록에서 가려낼 실험 1개"),
         ("4", "사람 승인", "대시보드 승인 뒤에만 실행"), ("5", "피코 측정", "60초 동안 지속·동시 시간 집계"), ("6", "판정·다음 실험", "유지 / 기각 / 보류 → 브리핑")]
b = ""
for i, (num, h, s) in enumerate(steps):
    y = i * 82
    col = C["purple"] if num == "4" else (C["teal"] if num == "5" else C["orange"])
    b += f'<circle cx="26" cy="{y + 34}" r="22" fill="{col}"/>' + T(26, y + 41, num, 19, 800, "#fff", "middle")
    b += T(62, y + 30, h, 19, 800) + T(62, y + 54, s, 14, 500, C["sub"])
    if i < len(steps) - 1:
        b += f'<line x1="26" y1="{y + 58}" x2="26" y2="{y + 92}" stroke="{C["line"]}" stroke-width="3"/>'
b += P("M 300 440 C 360 470 360 30 300 40", "orange", 2.5, "6 6")
b += T(372, 250, "반복", 15, 800, C["orange"], "middle")
code = [
    ("제보", "“오른쪽 트럭 때문에 차가 안 보여요”", C["ink"]),
    ("", "“아니에요, 왼쪽 차가 빨라서 위험해요”", C["ink"]),
    ("H1", "우측 정차가 오른쪽 시야를 가린다", C["orange"]),
    ("", "예상: stop_right + sight_right_blocked 동시", C["sub"]),
    ("", "기각: stop_right 중에도 sight_right 연결", C["sub"]),
    ("H2", "왼쪽 접근 차량 속도 문제", C["orange"]),
    ("", "속도는 측정하지 않음 → 측정 불가로 보류", C["sub"]),
    ("실험", "zones: stop_right, sight_right, waiting · 60초", C["blue"]),
    ("결과", "stop_right 42초 · sight_right 차단 40초 · 대기와 겹침 35초", C["teal"]),
    ("판정", "H1 유지 · H2 보류 → 다음 실험 제안", C["purple"]),
]
b += R(430, 0, 722, 500, fill=C["bg"], rx=18) + pill(452, 18, "설계 예시 (아직 구현 전)", C["orange_l"], C["orange"])
for i, (k, v, col) in enumerate(code):
    y = 86 + i * 40
    b += T(456, y, k, 15, 800, C["mute"]) + T(516, y, v, 16, 700 if k else 500, col)
slides.append(slide(6, "LLM LOOP", "LLM의 역할: 가설 → 실험 → 측정 → 판정", svg(b, 1152, 520)))

# 7. 시퀀스 ----------------------------------------------------------------
lanes = [("피코 WH", 90, C["teal"]), ("중계 서버", 420, C["blue"]), ("Command Code", 760, C["orange"]), ("사람", 1060, C["purple"])]
b = ""
for name, x, col in lanes:
    b += R(x - 82, 0, 164, 42, fill=col, rx=12) + T(x, 28, name, 17, 800, "#fff", "middle")
    b += f'<line x1="{x}" y1="44" x2="{x}" y2="520" stroke="{col}" stroke-width="2" stroke-dasharray="4 6"/>'
msgs = [
    (90, 420, "① 상태 요약 (1초마다)", "blue", ""),
    (420, 760, "② 제보 + 상태 + 허용 실험 목록", "orange", ""),
    (760, 420, "③ 가설·실험 JSON", "orange", "실측 4.7~7.2초*"),
    (420, 1060, "④ 승인 대기", "purple", ""),
    (1060, 420, "⑤ 승인", "purple", ""),
    (420, 90, "⑥ 측정 명령 (cmd_id)", "blue", ""),
    (90, 90, "⑦ 60초 측정 · 로컬 경고는 계속", "teal", ""),
    (90, 420, "⑧ 측정 결과", "blue", ""),
    (420, 760, "⑨ 결과 + 가설 → 판정", "orange", ""),
    (420, 1060, "⑩ 브리핑 초안 승인", "purple", "실측 초안 5.0초*"),
]
for i, (xa, xb, lab, col, extra) in enumerate(msgs):
    y = 74 + i * 44
    if xa == xb:
        b += R(8, y - 15, 324, 30, fill=C["teal_l"], stroke=C["teal"], rx=8) + T(170, y + 6, lab, 15, 700, C["teal"], "middle")
        continue
    b += A(xa, y, xb + (-6 if xb > xa else 6), y, col)
    mid = (xa + xb) / 2
    b += R(mid - (len(lab) * 7.6 + 16) / 2, y - 26, len(lab) * 7.6 + 16, 22, fill="#fff", rx=6) + T(mid, y - 9, lab, 14, 700, C["ink"], "middle")
    if extra:
        b += T(mid, y + 20, extra, 13, 800, C["green"], "middle")
b += T(0, 535, "* 실측은 2026-10-31 스타터 기본 기능(에이전트 제안·요청서 초안) 기준. 가설 루프 프롬프트 자체의 지연은 아직 측정하지 않았다.", 13, 500, C["mute"])
slides.append(slide(7, "SEQUENCE", "한 번의 고리: 누가 언제 무엇을 주고받나", svg(b, 1152, 545)))

# 8. 하드웨어 모형(위에서 본 그림) ---------------------------------------------
b = ""
b += R(0, 40, 840, 230, fill="#4a5262", rx=0)  # 도로
b += f'<line x1="0" y1="155" x2="840" y2="155" stroke="#f2c94c" stroke-width="3" stroke-dasharray="26 18"/>'
b += T(14, 74, "먼 차로 ←", 14, 700, "#dfe3ea") + T(826, 258, "→ 가까운 차로", 14, 700, "#dfe3ea", "end")
for i in range(8):
    b += R(380, 48 + i * 28, 90, 16, fill="#f4f6fa", rx=2)
b += R(0, 270, 840, 150, fill="#d9dee7", rx=0) + T(16, 408, "보도", 15, 800, C["sub"])
b += R(372, 386, 106, 30, fill="#c7cfdb", rx=6) + T(425, 406, "학교 정문", 14, 800, C["ink"], "middle")
# 정차 구역
b += R(170, 212, 170, 52, fill="none", stroke="#ffffff", sw=2, dash="7 6", rx=6) + T(255, 205, "정차 구역 L", 14, 800, "#ffffff", "middle")
b += R(510, 212, 170, 52, fill="none", stroke="#ffffff", sw=2, dash="7 6", rx=6) + T(595, 205, "정차 구역 R", 14, 800, "#ffffff", "middle")
b += R(530, 220, 128, 38, fill=C["orange"], rx=6) + T(594, 245, "모형 트럭", 14, 800, "#fff", "middle")
# 아이
b += f'<circle cx="425" cy="300" r="11" fill="{C["purple"]}"/>' + R(414, 312, 22, 26, fill=C["purple"], rx=6) + T(425, 360, "대기 아이(모형)", 13, 800, C["purple"], "middle")
# 시야선
b += f'<line x1="425" y1="300" x2="70" y2="232" stroke="{C["red"]}" stroke-width="3" stroke-dasharray="8 6"/>'
b += f'<line x1="425" y1="300" x2="540" y2="252" stroke="{C["red"]}" stroke-width="3" stroke-dasharray="8 6"/>'
b += f'<line x1="540" y1="252" x2="790" y2="146" stroke="{C["red"]}" stroke-width="3" stroke-dasharray="3 7" opacity="0.45"/>'
b += T(540, 260, "✕", 24, 800, C["red"], "middle")
b += T(62, 222, "시야선 L", 13, 800, "#ffd7d8", "end") + T(782, 132, "시야선 R", 13, 800, "#ffd7d8", "end")
# 센서
def sensor(x, y, label, color):
    return R(x - 16, y - 9, 32, 18, fill=color, rx=4) + f'<circle cx="{x - 7}" cy="{y}" r="5" fill="#fff"/><circle cx="{x + 7}" cy="{y}" r="5" fill="#fff"/>' + T(x, y + 26, label, 12, 800, C["ink"], "middle")
b += sensor(255, 290, "초음파 L", C["teal"]) + sensor(595, 290, "초음파 R", C["teal"]) + sensor(330, 300, "거리(대기)", C["teal"])
b += R(150, 40, 10, 230, fill=C["red"], rx=3, opacity=0.25) + T(155, 30, "접근 차량 빔", 12, 800, C["red"], "middle")
b += R(92, 276, 120, 30, fill="#111", rx=6) + T(152, 296, "보행자 대기", 13, 800, "#ffcf33", "middle") + T(152, 324, "운전자용 LED", 12, 700, C["sub"], "middle")
b += R(520, 334, 140, 30, fill="#111", rx=6) + T(590, 354, "시야 가림·확인", 13, 800, "#ff6b6b", "middle") + T(590, 382, "보행자용 LED", 12, 700, C["sub"], "middle")
# 피코·노트북
b += R(690, 300, 130, 64, fill="#0b6b45", rx=8) + T(755, 328, "피코 WH", 15, 800, "#fff", "middle") + T(755, 350, "RP2040", 12, 600, "#bfe8d2", "middle")
b += R(700, 420, 110, 58, fill=C["blue_l"], stroke=C["blue"], rx=8) + T(755, 455, "노트북", 15, 800, C["blue"], "middle")
b += A(755, 364, 755, 418, "blue") + T(765, 398, "USB", 13, 800, C["blue"])
# 범례
lx = 880
b += T(lx, 56, "부품 (피코 1대 기준)", 18, 800)
items = [(C["teal"], "초음파 ×2", "정차 구역 L/R 점유"), (C["teal"], "거리 센서 ×1", "정지한 대기 보행자(PIR 대신)"), (C["red"], "적외선 발광·수광 ×2쌍", "아이 눈높이 시야선 L/R 차단"),
         (C["red"], "적외선 빔 ×1쌍", "접근 차량 유무·시각만(속도 X)"), ("#111", "LED 표지 ×2", "운전자용·보행자용 경고"), ("#0b6b45", "피코 WH ×1", "로컬 규칙 + 측정 실행"),
         (C["red"], "✕ 표시", "트럭이 시야선 R을 막은 지점")]
for i, (col, h, s) in enumerate(items):
    y = 92 + i * 62
    b += R(lx, y, 14, 14, fill=col, rx=3) + T(lx + 24, y + 12, h, 15, 800) + T(lx + 24, y + 34, s, 13, 500, C["sub"])
b += T(0, 488, "모형 결과를 실제 도로의 사고 위험으로 일반화하지 않는다. 피코 2대면 반대편 보도 노드를 추가한다.", 14, 600, C["sub"])
slides.append(slide(8, "HARDWARE", "모형 배치: 위에서 본 횡단보도", svg(b, 1152, 500)))

# 9. 역할 경계 -------------------------------------------------------------
roles = [
    ("피코 WH", C["teal"], "센서 읽기 · 대기+시야 가림이면 경고 LED 즉시 점등 · 승인된 측정 실행·집계", "LLM 호출 · API 키 보관"),
    ("노트북 중계 서버", C["blue"], "제보·결과 보관 · 허용 실험 검사 · LLM 호출 · 승인 화면 · 늦은 응답 폐기", "실시간 경고 결정"),
    ("LLM (chat)", C["orange"], "경쟁 가설 · 예상 관측·기각 조건 · 구별 실험 선택 · 결과 해석 · 브리핑 초안", "위반 판정 · 경고 결정 · 측정 없는 결론"),
    ("jev", C["orange"], "비식별 센서 요약의 상태 분류(확률)", "자유 문장 처리(ZDR 미지원)"),
    ("사람", C["purple"], "제보 검수·비식별 · 실험·브리핑 승인 · 완료 확인", ""),
]
rows_html = "".join(
    f'<tr><td class="who" style="border-left:8px solid {col}">{esc(w)}</td><td>{esc(do)}</td><td class="dont">{esc(dont) or "—"}</td></tr>'
    for w, col, do, dont in roles)
slides.append(slide(9, "BOUNDARIES", "누가 무엇을 하고, 무엇을 하지 않나",
                    f'<table class="roles"><tr><th>담당</th><th>하는 일</th><th>하지 않는 일</th></tr>{rows_html}</table>'
                    '<div class="callout">핵심 원칙: 안전에 직결되는 반응은 기기의 규칙이, 판단과 글쓰기는 LLM이, 실행 허가는 사람이 맡는다.</div>'))

# 10. 실제 API 검증 --------------------------------------------------------
b = ""
ax0, ax1, scale = 250, 690, 55
b += T(0, 22, "응답 시간 (초)", 16, 800)
for s in range(0, 9):
    x = ax0 + s * scale
    b += f'<line x1="{x}" y1="40" x2="{x}" y2="356" stroke="{C["line"]}" stroke-width="1"/>' + T(x, 374, str(s), 13, 600, C["mute"], "middle")
bars = [
    ("jev 판단 (10건)", 0.59, 2.2, C["teal"], "0.59~2.2"),
    ("chat 제안 · 추론 low (3건)", 4.7, 6.5, C["orange"], "4.7~6.5 · 3/3 정확"),
    ("chat 제안 · 추론 off (6건)", 2.1, 3.0, "#c9a27a", "2.1~3.0 · 5/6 정확"),
    ("서버 경유 제안 생성", 7.2, 7.2, C["blue"], "7.2"),
    ("요청서 초안", 5.0, 5.0, C["purple"], "5.0 · 201자"),
]
for i, (lab, lo, hi, col, txt) in enumerate(bars):
    y = 64 + i * 60
    b += T(0, y + 6, lab, 15, 700)
    if lo == hi:
        b += f'<circle cx="{ax0 + lo * scale}" cy="{y}" r="9" fill="{col}"/>'
    else:
        b += R(ax0 + lo * scale, y - 11, (hi - lo) * scale, 22, fill=col, rx=11)
    b += T(ax0 + hi * scale + 16, y + 5, txt, 14, 800, col)
cards2 = [
    (C["teal"], "jev 10건", "가장 높은 선택지는 10건 모두 예상과 일치\n5건은 확률 0.47~0.76 → review로 내려감\n→ 시연 전 프로필별 기준 재설정 필요"),
    (C["red"], "버그 발견 → 수정", "chat 모델이 추론에 토큰을 다 써서 빈 응답\n(에이전트 제안 2번 모두 실패)\n→ reasoning_effort=low, max_tokens 2000"),
    (C["blue"], "개인정보(ZDR)", "x-cmd-zdr: 1 헤더 요청 → HTTP 200\n(deepseek-v4.1-flash, jev는 미지원)"),
]
for i, (col, h, s) in enumerate(cards2):
    y = i * 138
    b += R(880, y, 272, 124, fill="#fff", stroke=col, rx=14) + R(880, y, 8, 124, fill=col, rx=4)
    b += T(902, y + 30, h, 17, 800, col) + T(902, y + 56, s, 13, 600, C["sub"])
b += T(0, 412, "측정: 2026-10-31, 새 키, 스타터 기본 기능(access_space·route_guide·boarding_handoff 프로필)", 13, 500, C["mute"])
b += T(0, 432, "가설 루프 프롬프트, cmd가 붙은 제안의 피코 적용, 스피커 음성은 아직 확인하지 않았다.", 13, 500, C["mute"])
slides.append(slide(10, "VERIFIED", "실제 API로 확인한 것 (2026-10-31)", svg(b, 1152, 440)))

# 11. 12시간 계획 ----------------------------------------------------------
b = ""
d1x, d2x, hw = 170, 950, 82   # 1일차 09~18(9시간), 2일차 09~12(3시간)
b += T(d1x, 20, "10/31 (토) 09:00 ~ 18:00", 15, 800, C["ink"]) + T(d2x, 20, "11/1 (일) 09~12", 15, 800, C["ink"])
for h in range(10):
    x = d1x + h * hw
    b += f'<line x1="{x}" y1="34" x2="{x}" y2="390" stroke="{C["line"]}" stroke-width="1"/>' + T(x, 404, f"{9 + h:02d}", 12, 600, C["mute"], "middle")
for h in range(4):
    x = d2x + h * hw * 0.73
    b += f'<line x1="{x}" y1="34" x2="{x}" y2="390" stroke="{C["line"]}" stroke-width="1"/>' + T(x, 404, f"{9 + h:02d}", 12, 600, C["mute"], "middle")
lanes2 = [("하드웨어·모형", C["teal"]), ("펌웨어·로컬 규칙", C["teal"]), ("LLM·서버", C["orange"]), ("팀 공동", C["blue"])]
for i, (name, col) in enumerate(lanes2):
    y = 50 + i * 84
    b += T(0, y + 36, name, 16, 800, col)
def blk(day, start, end, lane, label, col, light=False):
    if day == 1:
        x, w = d1x + (start - 9) * hw, (end - start) * hw
    else:
        x, w = d2x + (start - 9) * hw * 0.73, (end - start) * hw * 0.73
    y = 50 + lane * 84
    fill = col if not light else "#eef0f4"
    tc = "#fff" if not light else C["mute"]
    return R(x + 3, y + 8, w - 6, 56, fill=fill, rx=10) + T(x + w / 2, y + 42, label, 14 if w > 120 else 12, 800, tc, "middle")
b += blk(1, 9, 12, 0, "모형·센서 배치", C["teal"])
b += blk(1, 9, 11, 1, "로컬 경고", C["teal"]) + blk(1, 11, 12, 1, "측정 실행기", "#0e8a75")
b += blk(1, 9, 12, 2, "가설·실험 루프 + 승인 화면", C["orange"])
b += blk(1, 12, 13, 3, "점심·여유", None, True)
b += blk(1, 13, 15, 3, "통합: 측정 명령 왕복", C["blue"]) + blk(1, 15, 17, 3, "반례 + 고정 규칙 비교", "#2457b8") + blk(1, 17, 18, 3, "예비", "#7d93c4")
b += blk(2, 9, 11, 3, "보정·리허설", C["purple"]) + blk(2, 11, 12, 3, "발표", "#5b36b0")
b += T(0, 440, "계획 예시: 작업 배분(모형·센서 3h, 로컬 경고·측정 2h, LLM 루프 3h, 반례·규칙 비교 2h, 발표 1h, 예비 1h)을 시간표로 펼친 것. 구현 보장이 아니며 행사 실제 시간표를 확인해야 한다.", 13, 500, C["mute"])
slides.append(slide(11, "PLAN", "12시간 계획 (3인 병렬)", svg(b, 1152, 450)))

# 12. 90초 시연 ------------------------------------------------------------
panels = [
    ("0~15초", "상충 제보 입력", "“오른쪽 트럭 때문에 안 보여요”\n“왼쪽 차가 빨라요”", C["ink"]),
    ("15~35초", "가설·실험 제안", "H1·H2 + 예상 관측·기각 조건\n구별 실험 1개 → 사람 승인", C["orange"]),
    ("35~55초", "측정과 즉시 경고", "트럭을 정차 구역 R에 놓으면\n오른쪽 시야선 차단 → LED 점등", C["teal"]),
    ("55~75초", "판정", "H1 유지 · H2 “속도 미측정” 보류\n다음 실험 제안", C["purple"]),
    ("75~90초", "브리핑 + 장애 시험", "학생용 수칙·학교/구청용 근거\n인터넷 끊어도 경고는 계속", C["blue"]),
]
b = ""
for i, (t, h, s, col) in enumerate(panels):
    x = i * 232
    b += R(x, 0, 216, 250, fill=C["bg"], rx=16) + R(x, 0, 216, 56, fill=col, rx=16) + R(x, 40, 216, 16, fill=col, rx=0)
    b += T(x + 108, 36, t, 20, 800, "#fff", "middle") + T(x + 108, 104, h, 19, 800, col, "middle") + T(x + 108, 146, s, 15, 600, C["sub"], "middle")
    if i < len(panels) - 1:
        b += A(x + 218, 140, x + 230, 140, "gray", 2)
b += R(0, 280, 1152, 76, fill=C["orange_l"], rx=14) + T(24, 314, "보여 줄 것: “LLM이 측정할 것을 고르고, 결과로 판단을 고친다.” 그리고 경고는 LLM 없이도 켜진다.", 17, 800, C["orange"])
b += T(24, 340, "같은 반례를 고정 규칙에도 주고 비교한 결과를 발표에 넣는다(차이가 없으면 LLM 필수성 주장을 철회).", 14, 600, C["sub"])
slides.append(slide(12, "DEMO", "90초 시연 스토리보드", svg(b, 1152, 370)))

# 13. 위험과 남은 일 ---------------------------------------------------------
risks = ["주정차와 맞닿은 주제라 ‘다른 주제’로 안 느껴질 수 있다", "모형 측정은 실제 도로를 대표하지 않는다",
         "LLM 필수성은 고정 규칙과 비교하기 전까지 미입증", "jev 0.80 기준이면 review가 잦다(실측 10건 중 5건)", "미성년 제보: 성인 검수·비식별, ZDR 헤더 필수"]
todo = ["피코 2대 확보 여부 확인(1인당 키트 구성 미확인)", "가설·실험 루프 프롬프트와 허용 실험 검사 구현", "측정 명령 실행기 + 결과 보고 필드(피코)",
        "적외선 시야선·거리 센서 실물 시험", "ZDR 헤더 추가, cmd 포함 제안의 실호출 확인", "고정 규칙 기준선 vs LLM 비교표 만들기"]
rh = "".join(f'<li>{esc(r)}</li>' for r in risks)
th = "".join(f'<li>{esc(t)}</li>' for t in todo)
slides.append(slide(13, "RISKS & NEXT", "위험과 남은 일",
                    f'<div class="two"><div class="col risk"><h2>위험</h2><ul>{rh}</ul></div><div class="col todo"><h2>남은 일</h2><ul class="check">{th}</ul></div></div>'
                    '<div class="callout decide"><b>결정 필요</b> — 이 주제(주정차와 맞닿음)로 확정할지, 5년 근거 요건을 완화해 '
                    '완전히 다른 분야(사생활·채광 합의창 등)로 갈지. 근거 요건을 지키면 이 주제가 사실상 유일하다(Claude·GPT 합의).</div>'))

CSS = f"""
@page {{ size: 1280px 720px; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #fff; }}
body {{ font-family: "Apple SD Gothic Neo", "AppleSDGothicNeo", sans-serif; color: {C['ink']};
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
svg text {{ font-family: "Apple SD Gothic Neo", "AppleSDGothicNeo", sans-serif; }}
.slide {{ width: 1280px; height: 720px; position: relative; overflow: hidden; padding: 44px 64px 40px;
  break-after: page; page-break-after: always; background: #fff; }}
.slide:last-of-type {{ break-after: auto; page-break-after: auto; }}
.kicker {{ font-size: 14px; letter-spacing: 3px; font-weight: 800; color: {C['blue']}; }}
h1 {{ font-size: 36px; font-weight: 800; letter-spacing: -0.5px; margin: 6px 0 22px; }}
.footer {{ position: absolute; left: 64px; right: 64px; bottom: 18px; display: flex; justify-content: space-between;
  font-size: 12px; color: {C['mute']}; border-top: 1px solid {C['line']}; padding-top: 8px; }}
.cover {{ background: {C['navy']}; padding: 0; }}
.cover-bg {{ position: absolute; left: 0; top: 0; }}
.cover-text {{ position: absolute; left: 88px; top: 150px; color: #fff; }}
.cover-kicker {{ font-size: 18px; font-weight: 700; color: #9fb4d8; letter-spacing: 1px; }}
.cover-title {{ font-size: 72px; font-weight: 800; letter-spacing: -2px; margin-top: 14px; }}
.cover-sub {{ font-size: 30px; font-weight: 700; color: #ffb86b; margin-top: 8px; }}
.cover-desc {{ font-size: 21px; line-height: 1.6; color: #dbe4f3; margin-top: 34px; }}
.cover-meta {{ font-size: 15px; color: #9fb4d8; margin-top: 56px; }}
table.roles {{ width: 100%; border-collapse: separate; border-spacing: 0 10px; font-size: 17px; }}
table.roles th {{ text-align: left; font-size: 14px; color: {C['mute']}; font-weight: 800; padding: 0 16px; }}
table.roles td {{ background: {C['bg']}; padding: 16px; line-height: 1.45; }}
table.roles td.who {{ font-weight: 800; width: 200px; border-radius: 10px 0 0 10px; }}
table.roles td.dont {{ color: {C['red']}; font-weight: 700; width: 300px; border-radius: 0 10px 10px 0; }}
.callout {{ margin-top: 14px; background: {C['navy']}; color: #fff; border-radius: 12px; padding: 16px 22px; font-size: 17px; font-weight: 700; }}
.callout.decide {{ margin-top: 22px; background: #fff7ed; color: #9a4d00; border: 2px solid {C['orange']}; font-weight: 600; line-height: 1.55; }}
.two {{ display: flex; gap: 32px; }}
.col {{ flex: 1; border-radius: 18px; padding: 24px 28px; }}
.col h2 {{ margin: 0 0 12px; font-size: 22px; }}
.col ul {{ margin: 0; padding-left: 22px; font-size: 18px; line-height: 1.75; }}
.risk {{ background: {C['red_l']}; }} .risk h2 {{ color: {C['red']}; }}
.todo {{ background: {C['teal_l']}; }} .todo h2 {{ color: {C['teal']}; }}
ul.check {{ list-style: none; padding-left: 0; }}
ul.check li::before {{ content: "☐  "; color: {C['teal']}; font-weight: 800; }}
"""

COLORS = {"gray": "#5b6476", "teal": C["teal"], "blue": C["blue"], "orange": C["orange"], "purple": C["purple"], "red": C["red"]}
markers = "".join(
    f'<marker id="ah-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0,0 L10,5 L0,10 z" fill="{v}"/></marker>' for k, v in COLORS.items())
doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>등굣길 위험 조사관 파이프라인</title>
<style>{CSS}</style></head><body>
<svg width="0" height="0" style="position:absolute"><defs>{markers}</defs></svg>
{''.join(slides)}
</body></html>"""
open(OUT, "w", encoding="utf-8").write(doc)
print("slides:", len(slides), "->", OUT)
