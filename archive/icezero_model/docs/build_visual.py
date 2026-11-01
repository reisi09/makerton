#!/usr/bin/env python3
"""표지 그림: 사거리 평면 + 엔진 실제 출력(기본 밤 재생) + 모델 흐름.

    python3 icezero_model/docs/build_visual.py  → visual/ICE-ZERO_사거리_시각화.png, visual/ice_zero_cross.html
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from cross_drawings import arms_info, svg_night, svg_pipeline, svg_plan  # noqa: E402
from night_data import replay  # noqa: E402
from svgkit import DEFS, esc  # noqa: E402

ROOT = os.path.dirname(HERE)
VIS = os.path.join(os.path.dirname(ROOT), "visual")
OUT_HTML = os.path.join(VIS, "ice_zero_cross.html")
OUT_PNG = os.path.join(VIS, "ICE-ZERO_사거리_시각화.png")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
W, H = 1800, 1130

CSS = """
*{box-sizing:border-box} body{margin:0;width:%dpx;height:%dpx;background:#f3f4f6;font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;color:#0f172a}
header{padding:22px 34px 8px} h1{margin:0;font-size:38px;letter-spacing:-0.5px} .sub{margin-top:6px;font-size:19px;color:#475569;font-weight:600}
main{display:grid;grid-template-columns:830px 1fr;gap:18px;padding:6px 34px 0}
.card{background:#fff;border:1px solid #d6dae1;border-radius:14px;padding:12px 16px;margin-bottom:12px}
.card h2{margin:0 0 8px;font-size:21px}
table{border-collapse:collapse;width:100%%;font-size:16px} th,td{border-bottom:1px solid #e5e7eb;padding:6px 6px;text-align:left}
th{color:#475569;font-size:14px} .pill{display:inline-block;padding:2px 9px;border-radius:999px;color:#fff;font-weight:800;font-size:14px}
.note{font-size:13.5px;color:#64748b;margin-top:6px;line-height:1.45}
svg.dwg{width:100%%;height:auto;display:block}
footer{padding:0 34px}
""" % (W, H)

LEVEL = {"risk1": ("#16a34a", "낮음"), "risk2": ("#d97706", "주의"), "risk3": ("#dc2626", "높음")}
LABEL = {"bridge": "교량", "general": "일반"}


def main():
    _, night, rows, summary = replay()
    focus = summary["first_general"] or summary["first_rec"] or rows[0]
    arms = arms_info()
    trs = []
    for k in "NESW":
        a = arms[k]
        col, word = LEVEL[focus["level"][k]]
        attr = LABEL.get(a.get("label"), a.get("label"))
        if a.get("shadow_index", 0) >= 0.3:
            attr += " · 그늘 %.2f" % a["shadow_index"]
        sel = ""
        if k in focus["order"]:
            sel = "<b style='color:#1d4ed8'>%d순위 선정</b>" % (focus["order"].index(k) + 1)
        elif focus["pmax"][k] >= 0.5:
            sel = "후보(예산 밖)"
        trs.append("<tr><td><b>%s</b> %s</td><td>%s</td><td>%.3f <span style='color:#64748b'>(상위 %.1f%%)</span></td>"
                   "<td><span class='pill' style='background:%s'>%.2f %s</span></td><td>%s</td></tr>" % (
                       k, esc(a["name"]), esc(attr), a["risk_v2"], 100 * (1 - a["risk_v2_pct"]), col, focus["pmax"][k], word, sel))
    hour = focus["label"]
    lead = summary.get("lead_general_h")
    first_rec = summary["first_rec"]
    ff = summary["first_freeze"]
    facts = []
    if first_rec:
        facts.append("첫 출동 권고 %s(교량 E, −2.5°C 가정 포함)" % first_rec["label"])
    if summary["first_general"]:
        facts.append("일반 갈래 첫 후보 %s" % summary["first_general"]["label"])
    if ff:
        facts.append("관측소 지면온도 첫 0°C 이하 %s" % ff["label"])
    levels = dict(focus["level"])
    body = """
<header><h1>ICE-ZERO 사거리 모형 — 맥북이 예보하고, 피코가 실행한다</h1>
<div class="sub">실제 강남구 교차로(노드 1220041600) 4갈래 · 2025-12-07 겨울밤(2025 시험 구간) 재생 · %s 엔진 판단 · 예산 2</div></header>
<main>
  <div class="card">%s</div>
  <div>
    <div class="card"><h2>%s 엔진 판단 — 네 갈래 모두 후보, 예산 2 → ICE-ZERO 우선순위로 선정</h2>
      <table><tr><th>갈래</th><th>속성</th><th>risk_v2(강남구)</th><th>최대 예측 동결확률</th><th>결정</th></tr>%s</table>
      <div class="note">동결확률 = XGBoost 지면온도 예보(+1·+3·+6h) → isotonic 보정. 교량은 −2.5°C 가정(현장 센서가 있으면 보정). 결빙 '확정'이 아니라 예측·상대 순위다.</div></div>
    <div class="card"><h2>그날 밤 전체(엔진 실제 출력)</h2>%s
      <div class="note">%s</div></div>
  </div>
</main>
<footer><div class="card">%s<div class="note">사람 승인 3단계(제보 확인 → 계획 승인 → 출동 승인) 뒤에만 Pico가 살포기를 연다. 교량 주의 LED는 Pico가 맥북 없이 로컬로 켠다. LLM은 기기를 조종하지 않는다.</div></div></footer>
""" % (hour, svg_plan(levels=levels, order=focus["order"], for_cover=True), hour, "".join(trs),
       svg_night(rows), esc(" · ".join(facts)), svg_pipeline())
    page = "<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'><style>%s</style></head><body>%s%s</body></html>" % (CSS, DEFS, body)
    os.makedirs(VIS, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(page)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=%d,%d" % (W, H),
                    "--screenshot=" + OUT_PNG, "file://" + OUT_HTML], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    print("HTML:", OUT_HTML)
    print("PNG:", OUT_PNG, "| 기준 시각", focus["time"], "선정", focus["order"], "| lead(일반)", lead)


if __name__ == "__main__":
    main()
