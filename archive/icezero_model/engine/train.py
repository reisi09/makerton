#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ICE-ZERO 사거리 엔진 학습 CLI.

    python3 engine/train.py           models/가 없으면 학습·저장하고 지표를 출력한다
    python3 engine/train.py --force   무조건 다시 학습한다

출력: 시점별 RMSE(모델 vs persistence vs 공기온도), 2025 Brier, 기본 시연 밤과
그 밤의 시간별 표(관측 지면온도, h1·h3 예측, 갈래별 p_max, 선정).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from icezero_cross import Engine, HORIZONS, MODEL_NAME, DISPATCH_P  # noqa: E402


def fmt(value, width=8, digits=2, suffix=""):
    if value is None:
        return "-".rjust(width)
    return ("%.*f%s" % (digits, value, suffix)).rjust(width)


def print_metrics(engine):
    metrics = engine.metrics
    data = metrics.get("data", {})
    print("자료: %s" % data.get("path"))
    print("      시간 격자 %s행(자료 %s행), %s ~ %s" % (
        data.get("rows"), data.get("observed_rows"), data.get("start"), data.get("end")))
    print("분할: 학습 %s · 시험 %s · 보정 %s" % (
        metrics["split"]["train"], metrics["split"]["test"], metrics["split"]["calibration"]))
    print("행수: 학습 %s · 시험 %s" % (metrics["rows"]["train"], metrics["rows"]["test"]))
    print("모델: %s" % metrics["model"])
    print("피처 %d개(일사·일조 제외): %s" % (len(metrics["features"]), ", ".join(metrics["features"])))
    print("")

    print("[2025 시험 구간 시점별 지표]")
    print(" 시점 | 모델RMSE  persRMSE  공기RMSE | 모델MAE  persMAE  공기MAE | Brier  Brier(하드)  동결비율")
    print("-" * 96)
    for h in HORIZONS:
        row = metrics["horizons"]["h%d" % h]
        print(" +%dh | %s  %s  %s | %s  %s  %s | %s   %s      %s" % (
            h,
            fmt(row["rmse"]), fmt(row["persistence_rmse"]), fmt(row["air_rmse"]),
            fmt(row["mae"]), fmt(row["persistence_mae"]), fmt(row["air_mae"]),
            fmt(row["brier"], 6, 4), fmt(row["brier_hard"], 8, 4), fmt(row["freeze_rate"], 6, 3),
        ))
    print("-" * 96)
    print("pers = persistence(발행 시각 지면온도, h0는 gt_lag1), Brier(하드) = 임계값 보정 없는 비교값")
    print("")


def print_nights(engine):
    print("[후보 밤 %d개, 점수순(2025)]" % len(engine.nights()))
    print(" 순위 | 밤        | 18시지면  최저   최저시각          하강   젖음12h  점수")
    print("-" * 84)
    for rank, night in enumerate(engine.nights()[:10], 1):
        print(" %4d | %s | %s %s %s %s %s %s" % (
            rank, night["night"], fmt(night["t18"], 6), fmt(night["t_min"], 6),
            night["min_time"].ljust(16), fmt(night["drop"], 6), fmt(night["wet_12h"], 7),
            fmt(night["score"], 6),
        ))
    if len(engine.nights()) == 0:
        print(" 조건을 만족하는 밤이 없다")
    print("-" * 84)


def print_night_table(engine, night):
    print("")
    print("[기본 시연 밤 %s 시간별 표]" % night)
    print(" 시각     | 관측지면  h1예측  h3예측 |       N       E       S       W | 선정")
    print("-" * 84)
    first_dispatch = None
    for stamp in engine.timeline(night):
        result = engine.step(stamp)
        obs = result["obs"].get("ground_temp")
        arms = result["arms"]
        picks = result["dispatch"]["selected"]
        if picks and first_dispatch is None:
            first_dispatch = (result["time"], picks)
        print(" %s | %s  %s  %s | %s %s %s %s | %s" % (
            result["time"].replace("T", " ")[5:16],
            fmt(obs, 8, 1), fmt(result["forecast"]["h1"], 8, 1), fmt(result["forecast"]["h3"], 8, 1),
            fmt(arms["N"]["p_max"], 7, 2), fmt(arms["E"]["p_max"], 7, 2),
            fmt(arms["S"]["p_max"], 7, 2), fmt(arms["W"]["p_max"], 7, 2),
            ",".join(picks) if picks else "-",
        ))
    print("-" * 84)
    if first_dispatch:
        print("출동 권고가 처음 나오는 시각: %s → 선정 %s (문턱 p_max ≥ %.1f, 예산 %d)" % (
            first_dispatch[0], ", ".join(first_dispatch[1]), DISPATCH_P,
            engine.step(first_dispatch[0])["dispatch"]["budget"]))
    else:
        print("출동 권고가 나오지 않는다(전 구간 p_max < %.1f)" % DISPATCH_P)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    force = "--force" in argv or "-f" in argv
    started = time.perf_counter()

    engine = Engine()
    print("== ICE-ZERO 사거리 엔진 ==")
    if force or not engine.models_exist():
        print("학습을 시작한다(시점별 4개 + 보정용 4개)...")
        engine.train()
        engine.save()
        print("학습·저장 완료: %s" % engine.models_dir)
    else:
        engine.load()
        print("저장본을 불러왔다: %s (--force로 다시 학습)" % engine.models_dir)
    if not engine.models:
        engine.load()
    print("경과 %.1f초" % (time.perf_counter() - started))
    print("")

    print_metrics(engine)
    print_nights(engine)
    if engine.default_night:
        print("기본 시연 밤: %s" % engine.default_night)
        print_night_table(engine, engine.default_night)
    else:
        print("기본 시연 밤이 없다(조건을 만족하는 2025년 밤 없음)")

    sizes = sorted(engine.models_dir.glob("*.json"))
    print("")
    print("[models/] %s" % ", ".join("%s %.1fKB" % (p.name, p.stat().st_size / 1024.0) for p in sizes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
