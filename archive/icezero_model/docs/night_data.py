"""기본 시연 밤을 엔진으로 재생해 표·그래프용 행을 만든다(가이드 PDF와 표지 그림 공용)."""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from icezero_cross import ARM_ORDER, Engine  # noqa: E402


def replay(night=None, budget=2):
    """반환: (engine, night, rows, summary). rows는 18:00~다음 날 09:00 정시."""
    eng = Engine()
    eng.load()
    night = night or eng.default_night
    rows = []
    for ts in eng.timeline(night):
        st = eng.step(ts, budget=budget)
        issued = (pd.Timestamp(ts) - pd.Timedelta(hours=3)).isoformat()
        h3_for_now = eng.step(issued, budget=budget)["forecast"].get("h3")
        arms = st["arms"]
        rows.append({
            "time": st["time"],
            "label": "%d시" % pd.Timestamp(st["time"]).hour,
            "obs": st["obs"].get("ground_temp"),
            "air": st["obs"].get("temp"),
            "forecast": st["forecast"],
            "h3": h3_for_now,
            "pmax": {k: arms[k]["p_max"] for k in ARM_ORDER},
            "level": {k: arms[k]["level"] for k in ARM_ORDER},
            "teff3": {k: arms[k]["t_eff"].get("h3") for k in ARM_ORDER},
            "recommend": st["dispatch"]["recommend"],
            "selected": list(st["dispatch"]["selected"]),
            "order": list(st["dispatch"]["order"]),
        })
    first_rec = next((r for r in rows if r["recommend"]), None)
    first_freeze = next((r for r in rows if r["obs"] is not None and r["obs"] <= 0), None)
    lead = None
    if first_rec and first_freeze:
        lead = (pd.Timestamp(first_freeze["time"]) - pd.Timestamp(first_rec["time"])).total_seconds() / 3600.0
    obs = [r for r in rows if r["obs"] is not None]
    low = min(obs, key=lambda r: r["obs"]) if obs else None
    first_general = next((r for r in rows if any(k in r["selected"] for k in ("N", "S", "W"))), None)
    lead_general = None
    if first_general and first_freeze:
        lead_general = (pd.Timestamp(first_freeze["time"]) - pd.Timestamp(first_general["time"])).total_seconds() / 3600.0
    summary = {"night": night, "first_rec": first_rec, "first_freeze": first_freeze, "lead_h": lead, "low": low,
               "first_general": first_general, "lead_general_h": lead_general, "info": eng.night_info(night)}
    return eng, night, rows, summary


if __name__ == "__main__":
    e, n, rows, s = replay()
    print("밤", n, "첫 권고", s["first_rec"] and s["first_rec"]["time"], s["first_rec"] and s["first_rec"]["order"],
          "첫 관측 0°C 이하", s["first_freeze"] and s["first_freeze"]["time"], "앞선 시간", s["lead_h"])
    for r in rows:
        print(r["label"], r["obs"], r["forecast"], r["h3"], r["pmax"], r["order"])
