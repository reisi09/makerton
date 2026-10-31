#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""정적 데모(GitHub Pages)용 재생 자료를 만든다.

2025년(시험 연도, 학습에 안 쓴 해) 겨울밤마다 18:00~다음 날 09:00을 한 시간씩 실제 엔진(Engine.step)에
넣고, 예보·갈래별 예측 동결확률을 저장한다. 브라우저는 이 값을 재생하고 출동 규칙만 다시 계산한다.
현장 보정(local_dt)은 엔진 범위 −6~+3°C를 1°C 간격으로 미리 계산해 둔다(얼음팩 슬라이더).

    python3 tools/export_demo.py            → docs/demo/replay.json
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.icezero.engine import (ARM_ORDER, DISPATCH_P, LEVEL_RISK2, LEVEL_RISK3,  # noqa: E402
                                  Engine)

DT_GRID = list(range(-6, 4))         # 현장 보정 °C (엔진이 −6~+3으로 자른다)
P_HORIZONS = ("h1", "h3", "h6")      # 출동 판단에 쓰는 시점(engine.CLASS_HORIZONS)
NIGHT_HOURS = 16                     # 18:00 ~ 다음 날 09:00
CLEAR_NIGHTS = 4                     # 결빙 없던 밤도 몇 개 넣어 '출동 안 함'을 보인다
TEST_YEAR = 2025
OUT = ROOT / "docs" / "demo" / "replay.json"


def _r(value, digits=3):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if v != v else round(v, digits)


def night_stamps(night):
    start = pd.Timestamp(night) + pd.Timedelta(hours=18)
    return [start + pd.Timedelta(hours=i) for i in range(NIGHT_HOURS)]


def export_night(engine, night):
    """밤 하나: 시각별 관측·예보·관측 정답·현장 보정별 동결확률."""
    frame = engine.frame
    steps = []
    for stamp in night_stamps(night):
        if stamp not in frame.index:
            continue
        ts = stamp.strftime("%Y-%m-%dT%H:%M:%S")
        p = {h: [None] * len(DT_GRID) for h in P_HORIZONS}
        base = None
        for i in range(0, len(DT_GRID), len(ARM_ORDER)):
            chunk = DT_GRID[i:i + len(ARM_ORDER)]
            local = {arm: {"dt": dt} for arm, dt in zip(ARM_ORDER, chunk)}
            step = engine.step(ts, local=local)
            base = base or step
            for arm, dt in zip(ARM_ORDER, chunk):
                for h in P_HORIZONS:
                    p[h][DT_GRID.index(dt)] = _r(step["arms"][arm]["p_freeze"][h])
        truth = {}
        for h in P_HORIZONS:
            later = stamp + pd.Timedelta(hours=int(h[1:]))
            truth[h] = _r(frame["ground_temp"].get(later), 1) if later in frame.index else None
        obs = base["obs"]
        steps.append({
            "t": ts,
            "obs": {k: _r(obs.get(k), 1) for k in ("temp", "ground_temp", "humidity", "wind", "snow")},
            "fc": {h: _r(v, 2) for h, v in base["forecast"].items()},
            "truth": truth,
            "p": p,
        })
    gt = [s["obs"]["ground_temp"] for s in steps if s["obs"]["ground_temp"] is not None]
    return {"night": night, "t18": steps[0]["obs"]["ground_temp"] if steps else None,
            "t_min": min(gt) if gt else None, "freezing": bool(gt) and min(gt) <= 0.0, "steps": steps}


def clear_nights(engine, count):
    """시험 연도 겨울밤 가운데 지면이 0°C 아래로 안 내려간 밤, 0°C에 가까운 순."""
    frame = engine.frame
    found = []
    for day in pd.date_range("%d-01-01" % TEST_YEAR, "%d-12-30" % TEST_YEAR, freq="D"):
        if day.month not in (1, 2, 11, 12):
            continue
        stamps = night_stamps(day.strftime("%Y-%m-%d"))
        gt = frame["ground_temp"].reindex(stamps)
        if gt.notna().sum() < NIGHT_HOURS or gt.min() <= 0.5:
            continue
        found.append((float(gt.min()), day.strftime("%Y-%m-%d")))
    return [night for _, night in sorted(found)[:count]]


def export(stn="119", out=OUT, limit=None):
    engine = Engine(stn=stn)
    engine.load()
    curated = [n["night"] for n in engine.nights()]
    names = curated[:limit] if limit else curated
    extra = clear_nights(engine, CLEAR_NIGHTS if not limit else 1)
    nights = [export_night(engine, n) for n in names + [n for n in extra if n not in names]]
    nights = [n for n in nights if n["steps"]]
    nights.sort(key=lambda n: n["night"])
    probe = engine.step(nights[0]["steps"][0]["t"])
    payload = {
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "station": stn,
        "model": probe["model"],
        "arms": {arm: {"name": probe["arms"][arm]["name"], "risk": probe["arms"][arm]["risk"]} for arm in ARM_ORDER},
        "dt_grid": DT_GRID,
        "threshold": DISPATCH_P,
        "levels": {"risk2": LEVEL_RISK2, "risk3": LEVEL_RISK3},
        "nights": nights,
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="정적 데모 재생 자료(JSON) 만들기")
    ap.add_argument("--stn", default="119")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    payload = export(args.stn, args.out)
    steps = sum(len(n["steps"]) for n in payload["nights"])
    print("저장: %s · 밤 %d개(결빙 %d) · 시각 %d개 · %.0fKB" % (
        args.out, len(payload["nights"]), sum(n["freezing"] for n in payload["nights"]), steps,
        args.out.stat().st_size / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
