#!/usr/bin/env python3
"""ICE-ZERO 사거리 모형 구현 가이드 PDF 생성기.

    python3 icezero_model/docs/build_guide.py            → docs/ICE-ZERO_사거리_구현가이드.pdf
    python3 icezero_model/docs/build_guide.py --html-only

도면 좌표는 cross_drawings.py 상수, 성능·재생 표는 엔진 실제 출력, 설정표는 pico_cross/config.py,
서버 옵션은 실제 --help, 시험 요약은 이 스크립트가 unittest를 돌린 결과다.
"""
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from cross_drawings import (arms_info, svg_bridge_obs, svg_cut, svg_night, svg_pipeline, svg_plan,  # noqa: E402
                            svg_system, svg_unit_detail, svg_wiring)
from night_data import replay  # noqa: E402
from svgkit import DEFS, esc, table  # noqa: E402

ROOT = os.path.dirname(HERE)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT_HTML = os.path.join(HERE, "guide.html")
OUT_PDF = os.path.join(HERE, "ICE-ZERO_사거리_구현가이드.pdf")
COVER_IMG = os.path.join(os.path.dirname(ROOT), "visual", "ICE-ZERO_사거리_시각화.png")
DASH_TOP = os.path.join(HERE, "dashboard_top.png")
DASH_BOTTOM = os.path.join(HERE, "dashboard_bottom.png")
METRICS = os.path.join(ROOT, "engine", "models", "metrics.json")
EVAL_DEV = os.path.join(ROOT, "tests", "eval_cross_result.json")
EVAL_HOLD = os.path.join(ROOT, "tests", "eval_cross_holdout.json")
ORIG_RMSE = {"h0": 0.68, "h1": 1.08, "h3": 1.36, "h6": 1.79}   # ICE-ZERO 발표 v10(일사·일조 포함)
LEVEL_BG = {"risk1": "#dcfce7", "risk2": "#fef3c7", "risk3": "#fee2e2"}
LABEL = {"bridge": "교량", "general": "일반"}


def run_text(args, timeout):
    try:
        p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa: BLE001
        return -1, "실행 실패: %s" % e


def arms_table():
    rows = []
    for k in "NESW":
        a = arms_info()[k]
        attr = LABEL.get(a.get("label"), a.get("label"))
        if a.get("structure"):
            attr += "(structure 1)"
        attr += " · 그림자 %.2f" % a.get("shadow_index", 0)
        rows.append(("<b>%s</b>" % k, esc(a["name"]), esc(attr), "%.3f" % a["risk_v2"], "%.1f%%" % (100 * (1 - a["risk_v2_pct"])),
                     esc(", ".join(a.get("link_ids", [])))))
    return table(["갈래", "도로", "속성", "risk_v2", "강남구 상위", "링크"], rows, "tight arms")


def metrics_table():
    m = json.load(open(METRICS, encoding="utf-8"))
    rows = []
    for h in ("h0", "h1", "h3", "h6"):
        x = m["horizons"][h]
        cut = 100 * (1 - x["rmse"] / x["persistence_rmse"])
        rows.append(("+%sh" % h[1:], "<b>%.2f</b>" % x["rmse"], "%.2f" % x["persistence_rmse"], "%.2f" % x["air_rmse"],
                     "−%.0f%%" % cut, "%.3f (보정 전 %.3f)" % (x["brier"], x["brier_hard"]), "%.2f" % ORIG_RMSE[h]))
    out = table(["시점", "모델 RMSE °C", "persistence", "공기온도", "persistence 대비", "Brier(동결확률)", "원 발표 v10"], rows, "tight")
    out += "<p class='small'>학습 %s행(2020~2024), 시험 %s행(2025), 보정 2024. 피처 %d개(일사·일조 제외). 학습 시각 %s. 원 발표 v10은 일사·일조 포함 수치(참고).</p>" % (
        m["rows"]["train"], m["rows"]["test"], len(m["features"]), esc(m.get("trained_at", "?")))
    return out


def night_blocks():
    eng, night, rows, s = replay()
    info = s["info"] or {}
    fr, fg, ff, low = s["first_rec"], s["first_general"], s["first_freeze"], s["low"]
    intro = ["<p><b>밤</b>: %s 18시 ~ 다음 날 09시(2025 시험 구간, 모델이 학습하지 않은 해). 엔진이 고른 기본 시연 밤이다(조건: 18시 지면온도 &gt; 0, 다음 날 09시까지 최저 ≤ 0, 점수 = 젖음 + 하강 폭)." % esc(night)]
    if info:
        intro.append(" 18시 지면 %.1f°C → 최저 %.1f°C(%s), 직전 12시간 강수·적설 %.1fmm.</p>" % (
            info.get("t18", 0), info.get("t_min", 0), esc(str(info.get("min_time", ""))[11:16]), info.get("wet_12h", 0)))
    else:
        intro.append("</p>")
    facts = []
    if fr:
        facts.append("<li><b>첫 출동 권고 %s</b>: 교량 E만(동결확률 %.2f). 교량 −2.5°C 가정이 들어간 값이다.</li>" % (fr["label"], fr["pmax"]["E"]))
    if fg:
        facts.append("<li><b>일반 갈래 첫 후보 %s</b>: N·S·W 동결확률 %.2f로 네 갈래가 모두 후보다. 예산 2 → risk_v2 순서로 <b>%s</b>를 고른다.</li>" % (
            fg["label"], fg["pmax"]["N"], " → ".join(fg["order"])))
    if ff:
        lead = s.get("lead_general_h")
        facts.append("<li><b>관측소 지면온도 첫 0°C 이하 %s</b>(최저 %.1f°C, %s). 일반 갈래 후보가 %s 앞섰다.</li>" % (
            ff["label"], low["obs"], low["label"], ("%d시간" % lead) if lead is not None else "?"))
    intro.append("<ul>%s</ul>" % "".join(facts))
    intro.append("<p class='small'>N·S·W는 유효온도 식이 같아 동결확률도 같다(그늘은 risk_v2에만 반영). 동결확률 1.00은 보정곡선 저온 포화값이며 확정이 아니다.</p>")
    trs = []
    for r in rows:
        f = r["forecast"]
        cells = []
        for k in "NESW":
            cells.append("<td style='background:%s;text-align:center'>%.2f</td>" % (LEVEL_BG[r["level"][k]], r["pmax"][k]))
        obs = "%.1f" % r["obs"] if r["obs"] is not None else "-"
        trs.append("<tr><td>%s</td><td>%s</td><td>%.1f / %.1f / %.1f</td>%s<td>%s</td></tr>" % (
            r["label"], obs, f["h1"], f["h3"], f["h6"], "".join(cells), " → ".join(r["order"]) or "-"))
    tbl = ("<table class='tight'><thead><tr><th>시각</th><th>관측 지면 °C</th><th>예보 +1/+3/+6h °C</th><th>N</th><th>E</th><th>S</th><th>W</th>"
           "<th>선정·순서(예산 2)</th></tr></thead><tbody>%s</tbody></table>" % "".join(trs))
    if fg:
        s["order_with_w"] = eng.step(fg["time"], reports=["W"])["dispatch"]["order"]
    return "".join(intro), svg_night(rows, "%s 밤 · 엔진 step() 결과" % night), tbl, s


def demo_table(s):
    fr, fg = s["first_rec"], s["first_general"]
    t1 = fr["label"] if fr else "권고 시각"
    t2 = fg["label"] if fg else "후보 시각"
    before = " → ".join(fg["order"]) if fg else "?"
    after = " → ".join(s.get("order_with_w") or []) or "?"
    rows = [
        ("0~10초", "보드 전체를 가리킨다", "실제 강남구 교차로 하나를 옮겼습니다. 동쪽은 올림픽로 교량, 서쪽은 그늘진 테헤란로입니다."),
        ("10~25초", "대시보드에서 기본 밤 18시 → %s로 넘긴다" % t1,
         "작년 12월 7일 실제 날씨를 맥북의 ICE-ZERO 모델이 시간마다 예측합니다. %s, 교량의 동결확률이 먼저 올라 출동 권고가 뜹니다." % t1),
        ("25~35초", "%s로 넘긴다. 제안 %s(예산 2)" % (t2, before),
         "네 갈래가 모두 후보인데 제설제는 2회분입니다. ICE-ZERO 위험 순위로 교량(강남구 상위 2.5%)과 그늘 테헤란로(상위 14%)를 고릅니다."),
        ("35~50초", "제보 입력 \"테헤란로 쪽 미끄럽대요\" → 되묻기 → W 체크 → 확인 → 제안이 %s로 바뀜" % after,
         "LLM이 제보를 정리하는데, 테헤란로는 두 갈래라 되묻습니다. 사람이 확인해야 반영되고, 확인된 제보만 순서를 바꿉니다."),
        ("50~60초", "계획 승인 → LED 파랑 깜박", "계획을 사람이 승인해야 Pico에 표시됩니다."),
        ("60~75초", "출동 승인 → 살포기가 %s 순서로 열림" % after, "Pico가 살포기를 한 번에 하나씩 엽니다. 끝난 갈래는 흰색으로 바뀝니다."),
        ("75~85초", "교량 시험편에 냉각팩 → '현장 보정 사용'", "교량 센서값이 들어오면 모델의 교량 온도를 현장 값으로 보정합니다. 교량 주의 LED는 Pico가 맥북 없이 켭니다."),
        ("85~90초", "비상 정지 버튼을 가리킨다", "결빙을 확정하는 게 아니라, 언제 어디부터 처리할지 사람이 빨리 결정하도록 돕습니다."),
    ]
    return table(["시간", "동작", "말"], [(a, esc(b), esc(c)) for a, b, c in rows], "tight")


def cfg_rows(path):
    """config.py의 `이름 = 값  # 설명` 줄을 행으로(코드와 문서가 어긋나지 않게)."""
    rows = []
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*(?:#\s*(.*))?$", line.rstrip("\n"))
        if not m:
            continue
        rows.append(("<code>%s</code>" % esc(m.group(1)), "<code>%s</code>" % esc(m.group(2)[:30]), esc(m.group(3) or "")))
    return rows


def cfg_table(rows):
    if not rows:
        return "<p class='warn'>설정 파일 없음</p>"
    return table(["이름", "기본값", "설명"], rows, "tight cfg")


def server_help():
    code, out = run_text([sys.executable, "server/icezero_server.py", "--help"], 60)
    if code != 0:
        return "<p class='warn'>--help 실행 실패(코드 %s)</p><pre class='code'>%s</pre>" % (code, esc(out[-800:]))
    return "<pre class='code'>%s</pre>" % esc(out.strip()[:2600])


def test_summary():
    code, out = run_text([sys.executable, "-m", "unittest", "discover", "-s", "tests"], 600)
    tail = [ln for ln in out.strip().splitlines() if ln.startswith("Ran ") or ln.startswith("OK") or ln.startswith("FAILED")]
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST")
    cls = "ok" if code == 0 else "bad"
    files = sorted(f for f in os.listdir(os.path.join(ROOT, "tests")) if f.startswith("test_") and f.endswith(".py"))
    return "<p class='%s'>%s — %s</p><p class='small'>시험 파일: %s</p>" % (cls, esc(" / ".join(tail) or "결과 줄 없음"), stamp, esc(", ".join(files))) + \
        ("" if code == 0 else "<pre class='code'>%s</pre>" % esc(out[-1500:]))


def _mark(item):
    """한 건 결과 → '갈래(모호·예산)' 짧은 표기 + 완전 일치 표시."""
    if not item:
        return "-"
    r, sc = item.get("result", {}), item.get("score", {})
    s = ",".join(r.get("arms") or []) or "—"
    if r.get("ambiguous"):
        s += " (되묻기)"
    if r.get("budget") is not None:
        s += " · 예산 %s" % r["budget"]
    return esc(s) + (" <span class='ok'>○</span>" if sc.get("exact") else " <span class='bad'>✕</span>")


def _summary_row(label, s, latency=None):
    if not s or not s.get("count"):
        return None
    n = s["count"]
    bud = "%d/%d" % (round(s.get("budget_accuracy", 0) * s.get("budget_count", 0)), s.get("budget_count", 0)) if s.get("budget_count") else "-"
    return (label, "%d/%d" % (s["arms_correct"], n), "%d/%d" % (s["ambiguous_correct"], n), bud,
            "<b>%d/%d</b>" % (s["exact_correct"], n), latency or "-")


def eval_block():
    if not (os.path.exists(EVAL_DEV) and os.path.exists(EVAL_HOLD)):
        return ("<p class='warn'>측정 파일이 없다. <code>python3 tests/eval_reports_cross.py</code>(개발 세트)와 "
                "<code>--reports tests/reports_cross_holdout.json --out tests/eval_cross_holdout.json</code>(보류 세트)로 만든다.</p>")
    dev = json.load(open(EVAL_DEV, encoding="utf-8"))
    hold = json.load(open(EVAL_HOLD, encoding="utf-8"))
    lat = [i["latency_ms"] for i in (hold["items"].get("llm") or []) if i.get("engine") == "llm"]
    fails = sum(1 for i in (hold["items"].get("llm") or []) if i.get("engine") != "llm")
    rows = [r for r in (
        _summary_row("개발 세트 · 규칙", dev.get("rule")),
        _summary_row("개발 세트 · LLM(표본 %s건)" % (dev.get("llm") or {}).get("count", 0), dev.get("llm")),
        _summary_row("<b>보류 세트 · 규칙</b>", hold.get("rule")),
        _summary_row("<b>보류 세트 · LLM</b>", hold.get("llm"), "%.0f ms" % (sum(lat) / len(lat)) if lat else None),
    ) if r]
    out = ("<p>개발 세트 12건은 규칙(rule_parse)과 프롬프트를 만들면서 본 문장이다. 그래서 규칙 12/12는 '맞춘 결과'다. "
           "보류 세트 12건은 그 뒤에 새로 쓰고 정답을 먼저 정한 문장이다(동의어·오타·부정·예산 표현). 공정한 비교는 보류 세트다.</p>")
    out += table(["세트 · 해석기", "갈래 일치", "모호 판정", "예산 읽기", "완전 일치", "평균 지연"], rows, "tight")
    hr = hold["items"]["rule"]
    hl = {i["text"]: i for i in (hold["items"].get("llm") or [])}
    det = []
    for item in hr:
        g = item["gold"]
        gold = ",".join(g.get("gold_arms") or []) or "—"
        if g.get("gold_ambiguous"):
            gold += " (되묻기)"
        if g.get("gold_budget") is not None:
            gold += " · 예산 %s" % g["gold_budget"]
        det.append((esc(item["text"]), esc(gold), _mark(item), _mark(hl.get(item["text"]))))
    out += "<h3>보류 세트 한 건씩</h3>" + table(["제보", "정답", "규칙", "LLM"], det, "tight")
    out += ("<p class='small'>모델 %s, reasoning low. 보류 세트 측정 %s, LLM 실호출 %d건, 규칙 대체 %d건. "
            "우리가 쓴 문장 24건뿐이라 일반 성능 주장은 하지 않는다. 화면에서는 LLM이 실패하면 규칙 해석으로 대체되고, 어느 쪽이든 사람이 확인해야 반영된다.</p>") % (
        esc(hold.get("model", "?")), esc(hold.get("generated_at", "?")), len(lat), fails)
    return out


SERVER_RUN_HTML = """<pre class='code'>cd suwon-makeathon-2026/icezero_model

# ① 흐름 익히기: LLM·Pico 없이
python3 server/icezero_server.py --no-llm --pico-serial none

# ② 시연: 키는 환경변수로만(파일·화면에 적지 않는다)
CMD_API_KEY="$(omp token commandcode)" \\
  python3 server/icezero_server.py --pico-serial auto

# Pico 포트 확인(포트가 둘이면 직접 적는다)
ls /dev/tty.usbmodem*</pre>"""


def build_html():
    intro, night_svg, night_tbl, summary = night_blocks()
    rows = cfg_rows(os.path.join(ROOT, "pico_cross", "config.py"))
    half = (len(rows) + 1) // 2
    css = open(os.path.join(HERE, "guide.css"), encoding="utf-8").read()
    body = open(os.path.join(HERE, "guide_body.html"), encoding="utf-8").read()
    target = summary["first_general"] or summary["first_rec"] or {"label": "?"}
    dash_cap = ("실제 서버 화면이다. <code>docs/capture_dashboard.py</code>가 실제 엔진으로 서버를 띄우고(LLM 없음, 가짜 Pico) 다음 순서로 진행한 뒤 찍었다: "
                "%s 밤을 %s까지 넘김 → '그늘진 테헤란로에 살얼음, 제설제 2회분' 제보 확인 → 계획 승인(W가 제보 가점으로 1순위) → 출동 → 모호한 제보 하나 남김.") % (
        esc(summary["night"]), esc(target["label"]))
    repl = {
        "{{DEFS}}": DEFS,
        "{{COVER}}": "file://" + COVER_IMG,
        "{{SVG_SYSTEM}}": svg_system(),
        "{{ARMS_TABLE}}": arms_table(),
        "{{SVG_PIPELINE}}": svg_pipeline(),
        "{{METRICS_TABLE}}": metrics_table(),
        "{{NIGHT_INTRO}}": intro,
        "{{SVG_NIGHT}}": night_svg,
        "{{NIGHT_TABLE}}": night_tbl,
        "{{SVG_PLAN}}": svg_plan(),
        "{{SVG_UNIT}}": svg_unit_detail(),
        "{{SVG_OBS}}": svg_bridge_obs(),
        "{{SVG_CUT}}": svg_cut(),
        "{{SVG_WIRING}}": svg_wiring(),
        "{{SERVER_RUN}}": SERVER_RUN_HTML,
        "{{DASH_TOP}}": "file://" + DASH_TOP,
        "{{DASH_BOTTOM}}": "file://" + DASH_BOTTOM,
        "{{DASH_CAPTION}}": dash_cap,
        "{{PICO_CFG_A}}": cfg_table(rows[:half]),
        "{{PICO_CFG_B}}": cfg_table(rows[half:]),
        "{{SERVER_HELP}}": server_help(),
        "{{README_NOTES}}": "",
        "{{TEST_SUMMARY}}": test_summary(),
        "{{EVAL}}": eval_block(),
        "{{DEMO_TABLE}}": demo_table(summary),
    }
    for k, v in repl.items():
        body = body.replace(k, v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", body)
    if left:
        raise SystemExit("채우지 못한 자리표시자: %s" % left)
    return "<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'><title>ICE-ZERO 사거리 모형 구현 가이드</title><style>%s</style></head><body>%s</body></html>" % (css, body)


def main():
    page = build_html()
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(page)
    print("HTML:", OUT_HTML)
    if "--html-only" in sys.argv:
        return
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--print-to-pdf=" + OUT_PDF,
                    "file://" + OUT_HTML], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("PDF:", OUT_PDF)


if __name__ == "__main__":
    main()
