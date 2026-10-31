#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""지점별 ICE-ZERO 학습 CLI (계약 3절).

    python3 -m model.icezero.train --stn 108
    python3 -m model.icezero.train --stn 119 --force

흐름
1. 지점 자료 읽기(kma) → 피처(features). 일사·일조는 자료에 있을 때만 쓴다.
2. 개선 피처 후보 실험: 2024 검증 RMSE에서 이긴 것만 남긴다(진 것은 metrics에 기록).
3. 시점별 방법 선택: 회귀+isotonic / 직접 분류 / 둘의 평균.
   2024 검증 Brier로 고른다(회귀는 ≤2022 학습·2023 보정, 분류는 ≤2022 학습).
   검증 연도를 보정에 쓰지 않으려고 한 해씩 앞에서 보정한다.
4. 최종 학습 ≤2024, 시험 2025.
5. 연도별 rolling 검증(시험 연도 2022~2025) — RMSE를 persistence·공기온도와 비교.
6. 사건 지표(2025 밤): 결빙 밤 경보 적중률, 첫 경보 선행 시간 중앙값, 비결빙 밤 오경보율.
7. 산출물 model/models/<stn>/: reg_h*.json, clf_h*.json, calib.json, metrics.json,
   nights.json, features.json

지점 자료가 없으면 이유를 출력하고 종료 코드 2로 끝난다.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBClassifier, XGBRegressor

from . import features, kma

HORIZONS = features.HORIZONS
CLASS_HORIZONS = (1, 3, 6)

TRAIN_END = 2024          # 최종 학습 상한(포함)
TEST_YEAR = 2025          # 시험 연도
CALIB_YEAR = 2024         # 최종 보정 연도
ROLLING_YEARS = (2022, 2023, 2024, 2025)

SELECT_FIT_END = 2022     # 방법 선택용 학습 상한
SELECT_CAL_YEAR = 2023    # 방법 선택용 보정 연도
SELECT_VAL_YEAR = 2024    # 방법 선택용 검증 연도

METHODS = ("reg", "clf", "blend")
DISPATCH_P = 0.5
NIGHT_START_HOUR = 18
NIGHT_HOURS = 16          # 18:00 ~ 다음 날 09:00
NIGHT_MIN_OBS = 14        # 밤 창의 관측 지면온도 최소 개수

XGB_PARAMS = dict(
    n_estimators=600,
    learning_rate=0.05,
    max_depth=6,
    subsample=0.9,
    colsample_bytree=0.9,
    random_state=42,
    n_jobs=4,
)
CLF_PARAMS = dict(XGB_PARAMS, eval_metric="logloss")

MODEL_NAME = "ICE-ZERO 고색 경량(XGBoost 시점별 회귀·분류 혼합)"

MODELS_ROOT = kma.MODEL_ROOT / "models"

NIGHT_WET_CAP = 5.0
NIGHT_DROP_CAP = 8.0


# ---------------------------------------------------------------- 지표 함수

def _finite(values):
    return np.asarray(values, dtype="float64")


def rmse(y, pred):
    y = _finite(y)
    pred = _finite(pred)
    ok = np.isfinite(y) & np.isfinite(pred)
    if not ok.any():
        return float("nan")
    return float(np.sqrt(np.mean((y[ok] - pred[ok]) ** 2)))


def mae(y, pred):
    y = _finite(y)
    pred = _finite(pred)
    ok = np.isfinite(y) & np.isfinite(pred)
    if not ok.any():
        return float("nan")
    return float(np.mean(np.abs(y[ok] - pred[ok])))


def brier(y_freeze, prob):
    y = _finite(y_freeze)
    p = _finite(prob)
    ok = np.isfinite(y) & np.isfinite(p)
    if not ok.any():
        return float("nan")
    return float(np.mean((p[ok] - y[ok]) ** 2))


def r4(value):
    """지표용 반올림. NaN·None은 None."""
    if value is None:
        return None
    v = float(value)
    return None if not np.isfinite(v) else round(v, 4)


def isotonic_curve(pred, freeze):
    """예측 지면온도 → P(지면 ≤ 0) 보정곡선(단조 감소)."""
    iso = IsotonicRegression(increasing=False, out_of_bounds="clip")
    iso.fit(_finite(pred), np.asarray(freeze, dtype="float64"))
    xs = np.asarray(iso.X_thresholds_, dtype="float64")
    ys = np.asarray(iso.y_thresholds_, dtype="float64")
    return xs, ys


def apply_curve(values, xs, ys):
    """보정곡선 적용(np.interp, 양끝 고정). 배열·스칼라 모두."""
    v = np.asarray(values, dtype="float64")
    if xs is None or len(xs) == 0:
        return np.zeros_like(v)
    return np.clip(np.interp(v, xs, ys), 0.0, 1.0)


def pick_method(briers):
    """Brier가 가장 낮은 방법. 동점이면 reg → clf → blend 순서."""
    best = None
    for name in METHODS:
        value = briers.get(name)
        if value is None or not np.isfinite(value):
            continue
        if best is None or float(value) < best[1] - 1e-12:
            best = (name, float(value))
    return best[0] if best else "reg"


# ---------------------------------------------------------------- 학습

def fit_regressor(df, cols, target):
    model = XGBRegressor(**XGB_PARAMS)
    model.fit(df[cols], df[target])
    return model


def fit_classifier(df, cols, target):
    y = (df[target] <= 0.0).astype(int)
    model = XGBClassifier(**CLF_PARAMS)
    model.fit(df[cols], y)
    return model


def _rows(frame, cols, h):
    """피처와 목표가 모두 있는 행(h시점 목표)."""
    return frame.dropna(subset=list(cols) + [features.target_column(h)])


def _fit_rows(data, h, last_year):
    """last_year까지의 학습 행. 목표 시각(t+h)이 다음 해로 넘어가는 12/31 밤 행은 뺀다.

    연도로 자르면 12/31 18~23시 행의 +h 목표가 다음 해(검증·보정·시험) 정답이 된다.
    """
    target_year = (data.index + pd.Timedelta(hours=h)).year
    return data[(data.index.year <= last_year) & (target_year <= last_year)]


def _year_rows(data, h, year):
    """그 해 안에서 목표까지 끝나는 행(보정·검증용)."""
    target_year = (data.index + pd.Timedelta(hours=h)).year
    return data[(data.index.year == year) & (target_year == year)]


def evaluate_rmse(frame, cols, year, fit_end):
    """연도 하나의 시점별 RMSE(회귀). 자료가 모자라면 None."""
    out = {}
    for h in HORIZONS:
        data = _rows(frame, cols, h)
        tr = _fit_rows(data, h, fit_end)
        te = _year_rows(data, h, year)
        if len(tr) < 200 or len(te) < 20:
            out["h%d" % h] = None
            continue
        model = fit_regressor(tr, cols, features.target_column(h))
        out["h%d" % h] = r4(rmse(te[features.target_column(h)], model.predict(te[cols])))
    return out


def feature_experiment(frame, base_cols):
    """개선 후보를 하나씩 더해 2024 검증 RMSE를 비교한다(학습 ≤2023).

    네 시점 가운데 두 개 이상에서 RMSE가 좋아진 후보만 채택한다.
    """
    accepted = []
    detail = {"base": evaluate_rmse(frame, base_cols, SELECT_VAL_YEAR, TRAIN_END - 1)}
    current = list(base_cols)
    current_score = detail["base"]

    for cand in features.EXTRA_CANDIDATES:
        if cand not in frame.columns or not frame[cand].notna().any():
            detail[cand] = {"accepted": False, "reason": "자료에 없음"}
            continue
        cols = current + [cand]
        score = evaluate_rmse(frame, cols, SELECT_VAL_YEAR, TRAIN_END - 1)
        wins = [
            key for key in score
            if score[key] is not None and current_score.get(key) is not None
            and score[key] < current_score[key] - 1e-4
        ]
        accepted_flag = len(wins) >= 2
        detail[cand] = {
            "accepted": accepted_flag,
            "rmse": score,
            "rmse_before": current_score,
            "wins": wins,
        }
        if accepted_flag:
            accepted.append(cand)
            current = cols
            current_score = score
    return accepted, detail


def select_methods(frame, cols):
    """시점별 방법 선택(2024 검증 Brier). h0은 회귀 고정."""
    methods = {"h0": "reg"}
    detail = {"h0": {"method": "reg", "reason": "h0은 현재 지면온도라 회귀만 쓴다"}}
    for h in CLASS_HORIZONS:
        key = "h%d" % h
        target = features.target_column(h)
        data = _rows(frame, cols, h)
        tr = _fit_rows(data, h, SELECT_FIT_END)
        cal = _year_rows(data, h, SELECT_CAL_YEAR)
        va = _year_rows(data, h, SELECT_VAL_YEAR)
        if len(tr) < 200 or len(cal) < 50 or len(va) < 50:
            methods[key] = "reg"
            detail[key] = {"method": "reg", "reason": "자료 부족으로 회귀 고정"}
            continue

        reg = fit_regressor(tr, cols, target)
        xs, ys = isotonic_curve(reg.predict(cal[cols]), (cal[target] <= 0.0).astype(float))
        p_reg = apply_curve(reg.predict(va[cols]), xs, ys)
        clf = fit_classifier(tr, cols, target)
        p_clf = clf.predict_proba(va[cols])[:, 1]
        p_blend = (p_reg + p_clf) / 2.0
        y = (va[target] <= 0.0).astype(float)

        briers = {
            "reg": brier(y, p_reg),
            "clf": brier(y, p_clf),
            "blend": brier(y, p_blend),
        }
        chosen = pick_method(briers)
        methods[key] = chosen
        detail[key] = {
            "method": chosen,
            "validation_year": SELECT_VAL_YEAR,
            "fit": "≤%d" % SELECT_FIT_END,
            "calibration": str(SELECT_CAL_YEAR),
            "brier": {name: r4(value) for name, value in briers.items()},
            "rmse_reg": r4(rmse(va[target], reg.predict(va[cols]))),
            "rows": int(len(va)),
        }
    return methods, detail


def fit_final(frame, cols):
    """≤2024 학습. 보정 곡선은 ≤2023 모델의 2024 예측으로 만든다."""
    reg = {}
    clf = {}
    calib = {}
    for h in HORIZONS:
        target = features.target_column(h)
        data = _rows(frame, cols, h)
        tr = _fit_rows(data, h, TRAIN_END)
        reg[h] = fit_regressor(tr, cols, target)
        if h in CLASS_HORIZONS:
            clf[h] = fit_classifier(tr, cols, target)

    for h in HORIZONS:
        target = features.target_column(h)
        data = _rows(frame, cols, h)
        early = _fit_rows(data, h, TRAIN_END - 1)
        cal = _year_rows(data, h, CALIB_YEAR)
        if len(early) < 200 or len(cal) < 50:
            xs, ys = isotonic_curve(data[target], (data[target] <= 0.0).astype(float))
            note = "자료 부족: 지점 전체로 적합"
            rows = int(len(data))
        else:
            early_model = fit_regressor(early, cols, target)
            xs, ys = isotonic_curve(
                early_model.predict(cal[cols]), (cal[target] <= 0.0).astype(float)
            )
            note = "≤%d 학습 모델의 %d 예측 → 지면 ≤ 0" % (TRAIN_END - 1, CALIB_YEAR)
            rows = int(len(cal))
        calib[h] = {"x": xs, "y": ys, "fit": note, "rows": rows}
    return reg, clf, calib


def test_metrics(frame, cols, reg, clf, calib, methods):
    """2025 시험 지표: 방법별 Brier와 RMSE·기준선."""
    out = {}
    for h in HORIZONS:
        key = "h%d" % h
        target = features.target_column(h)
        data = _rows(frame, cols, h)
        te = data[data.index.year == TEST_YEAR]
        if len(te) < 20:
            out[key] = None
            continue
        pred = reg[h].predict(te[cols])
        p_reg = apply_curve(pred, calib[h]["x"], calib[h]["y"])
        p_clf = clf[h].predict_proba(te[cols])[:, 1] if h in clf else None
        p_blend = None if p_clf is None else (p_reg + p_clf) / 2.0

        y_freeze = (te[target] <= 0.0).astype(float)
        method = methods.get(key, "reg")
        if method == "clf" and p_clf is not None:
            p_used = p_clf
        elif method == "blend" and p_blend is not None:
            p_used = p_blend
        else:
            method = "reg"
            p_used = p_reg

        persistence = te["ground_temp"] if h > 0 else te["gt_lag1"]
        out[key] = {
            "method": method,
            "rmse": r4(rmse(te[target], pred)),
            "mae": r4(mae(te[target], pred)),
            "persistence_rmse": r4(rmse(te[target], persistence)),
            "persistence_mae": r4(mae(te[target], persistence)),
            "air_rmse": r4(rmse(te[target], te["temp"])),
            "air_mae": r4(mae(te[target], te["temp"])),
            "brier": r4(brier(y_freeze, p_used)),
            "brier_reg": r4(brier(y_freeze, p_reg)),
            "brier_clf": None if p_clf is None else r4(brier(y_freeze, p_clf)),
            "brier_blend": None if p_blend is None else r4(brier(y_freeze, p_blend)),
            "freeze_rate": r4(np.mean(y_freeze)),
            "rows": int(len(te)),
        }
    return out


def rolling_validation(frame, cols):
    """시험 연도 2022~2025 rolling: 모델·persistence·공기온도 RMSE."""
    out = {}
    for year in ROLLING_YEARS:
        per = {}
        for h in HORIZONS:
            key = "h%d" % h
            target = features.target_column(h)
            data = _rows(frame, cols, h)
            tr = _fit_rows(data, h, year - 1)
            te = data[data.index.year == year]
            if len(tr) < 200 or len(te) < 20:
                per[key] = None
                continue
            model = fit_regressor(tr, cols, target)
            pred = model.predict(te[cols])
            persistence = te["ground_temp"] if h > 0 else te["gt_lag1"]
            per[key] = {
                "rmse": r4(rmse(te[target], pred)),
                "persistence_rmse": r4(rmse(te[target], persistence)),
                "air_rmse": r4(rmse(te[target], te["temp"])),
                "rows": int(len(te)),
            }
        out[str(year)] = per
    return out


# ---------------------------------------------------------------- 밤·사건

def night_windows(frame, year):
    """그 해 밤 창(18:00~다음 날 09:00) 목록. 관측이 모자란 밤은 뺀다."""
    starts = [stamp for stamp in frame.index if stamp.year == year and stamp.hour == NIGHT_START_HOUR]
    windows = []
    for start in starts:
        stamps = [start + pd.Timedelta(hours=i) for i in range(NIGHT_HOURS)]
        stamps = [stamp for stamp in stamps if stamp in frame.index]
        if len(stamps) < NIGHT_HOURS:
            continue
        observed = frame.loc[stamps, "ground_temp"].dropna()
        if len(observed) < NIGHT_MIN_OBS:
            continue
        windows.append((start, stamps, observed))
    return windows


def night_probabilities(frame, cols, reg, clf, calib, methods, stamps):
    """밤 창의 시각별 p_max(h1·h3·h6 최댓값)."""
    x = frame.loc[stamps, cols]
    best = np.zeros(len(stamps), dtype="float64")
    for h in CLASS_HORIZONS:
        key = "h%d" % h
        method = methods.get(key, "reg")
        p_reg = apply_curve(reg[h].predict(x), calib[h]["x"], calib[h]["y"])
        if method == "clf" and h in clf:
            prob = clf[h].predict_proba(x)[:, 1]
        elif method == "blend" and h in clf:
            prob = (p_reg + clf[h].predict_proba(x)[:, 1]) / 2.0
        else:
            prob = p_reg
        best = np.maximum(best, prob)
    return best


def event_metrics(frame, cols, reg, clf, calib, methods, year=TEST_YEAR):
    """밤 사건 지표: 경보 적중률·첫 경보 선행 시간·오경보율."""
    windows = night_windows(frame, year)
    freezing = []
    clear = []
    for start, stamps, observed in windows:
        item = {
            "night": start.strftime("%Y-%m-%d"),
            "t_min": float(observed.min()),
            "freeze": bool(float(observed.min()) <= 0.0),
        }
        (freezing if item["freeze"] else clear).append((item, stamps))

    hits = 0
    leads = []
    onset_leads = []
    start_frozen = 0
    late = 0
    alarm_any = 0
    for item, stamps in freezing + clear:
        prob = night_probabilities(frame, cols, reg, clf, calib, methods, stamps)
        alarm_at = [i for i, p in enumerate(prob) if p >= DISPATCH_P]
        item["alarm"] = bool(alarm_at)
        item["p_max"] = float(np.max(prob)) if len(prob) else 0.0
        if item["alarm"]:
            alarm_any += 1
        if not item["freeze"]:
            continue
        freeze_at = [
            i for i, stamp in enumerate(stamps)
            if pd_notna(frame.at[stamp, "ground_temp"]) and float(frame.at[stamp, "ground_temp"]) <= 0.0
        ]
        if freeze_at and freeze_at[0] == 0:
            start_frozen += 1          # 18시에 이미 결빙: 창 밖이라 선행을 잴 수 없다
        if not (item["alarm"] and freeze_at):
            continue
        hits += 1
        lead = float(freeze_at[0] - alarm_at[0])
        leads.append(lead)
        if lead < 0.0:
            late += 1
        if freeze_at[0] > 0:
            onset_leads.append(lead)

    false_alarms = sum(1 for item, _ in clear if item.get("alarm"))
    return {
        "year": year,
        "definition": {
            "night": "%02d:00~다음 날 09:00(16시간)" % NIGHT_START_HOUR,
            "alarm": "밤 창 어느 시각이든 p_max(h1·h3·h6) ≥ %.1f" % DISPATCH_P,
            "freeze": "밤 창 관측 지면온도 최저 ≤ 0°C",
            "hit_rate": "결빙 밤 가운데 경보가 난 비율",
            "lead_hours": "첫 관측 결빙 시각 − 첫 경보 시각(시간). 양수면 결빙 전에 알린 것",
            "lead_hours_onset": "18시에는 아직 0°C 위였다가 창 안에서 결빙이 시작된 밤만의 선행 시간",
            "false_alarm_rate": "결빙 없던 밤 가운데 경보가 난 비율",
            "min_obs": "밤 창 관측 지면온도 최소 %d개" % NIGHT_MIN_OBS,
        },
        "nights_total": len(windows),
        "freezing_nights": len(freezing),
        "clear_nights": len(clear),
        "alarm_nights": int(alarm_any),
        "hits": int(hits),
        "misses": int(len(freezing) - hits),
        "false_alarms": int(false_alarms),
        "hit_rate": r4(hits / float(len(freezing))) if freezing else None,
        "false_alarm_rate": r4(false_alarms / float(len(clear))) if clear else None,
        "median_lead_hours": r4(float(np.median(leads))) if leads else None,
        "start_frozen_nights": int(start_frozen),
        "onset_nights": int(len(onset_leads)),
        "median_lead_hours_onset": (
            r4(float(np.median(onset_leads))) if onset_leads else None
        ),
        "late_nights": int(late),
        "lead_hours": [round(v, 2) for v in sorted(leads)],
        "p_threshold": DISPATCH_P,
    }


def pd_notna(value):
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def replay_nights(frame, year=TEST_YEAR):
    """재생용 후보 밤(18시 지면 > 0, 다음 날 09시까지 최저 ≤ 0). 점수 내림차순."""
    found = []
    for stamp in frame.index:
        if stamp.year != year or stamp.hour != NIGHT_START_HOUR:
            continue
        gt18 = frame.at[stamp, "ground_temp"]
        if not pd_notna(gt18) or float(gt18) <= 0.0:
            continue
        end = stamp.normalize() + pd.Timedelta(days=1, hours=9)
        if end not in frame.index:
            continue
        window = frame.loc[stamp:end, "ground_temp"].dropna()
        if len(window) == 0:
            continue
        t_min = float(window.min())
        if t_min > 0.0:
            continue
        wet_from = stamp - pd.Timedelta(hours=13)
        wet_to = stamp - pd.Timedelta(hours=1)
        wet = frame.loc[wet_from:wet_to]
        wet_12h = float(wet["precip"].fillna(0.0).sum() + wet["snow"].fillna(0.0).sum())
        drop = float(gt18) - t_min
        score = min(wet_12h, NIGHT_WET_CAP) + min(drop, NIGHT_DROP_CAP)
        found.append({
            "night": stamp.strftime("%Y-%m-%d"),
            "t18": round(float(gt18), 2),
            "t_min": round(t_min, 2),
            "min_time": window.idxmin().isoformat(),
            "drop": round(drop, 2),
            "wet_12h": round(wet_12h, 2),
            "score": round(score, 2),
        })
    found.sort(key=lambda item: (-item["score"], item["night"]))
    return found


# ---------------------------------------------------------------- 저장·출력

def display_path(path):
    """저장소 안이면 상대 경로로 적는다(산출물 JSON에 절대 경로를 남기지 않는다)."""
    folder = Path(path).resolve()
    try:
        return str(folder.relative_to(kma.MODEL_ROOT.parent))
    except ValueError:
        return str(folder)


def save_artifacts(stn, models_dir, cols, reg, clf, calib, metrics, nights):
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    for h, model in reg.items():
        model.save_model(str(models_dir / ("reg_h%d.json" % h)))
    for h, model in clf.items():
        model.save_model(str(models_dir / ("clf_h%d.json" % h)))

    calib_payload = {
        "note": "isotonic 동결확률 보정곡선(임계값 배열). x=예측 지면온도, y=P(지면 ≤ 0)",
        "method": "sklearn.isotonic.IsotonicRegression(increasing=False, out_of_bounds='clip')",
        "applied_to": "갈래 유효온도 t_eff(°C)",
        "horizons": {
            "h%d" % h: {
                "fit": calib[h]["fit"],
                "rows": int(calib[h]["rows"]),
                "x": [round(float(v), 6) for v in calib[h]["x"]],
                "y": [round(float(v), 6) for v in calib[h]["y"]],
            }
            for h in HORIZONS
        },
    }
    features_payload = {
        "station": str(stn),
        "features": list(cols),
        "base": list(features.BASE_FEATURES),
        "lags": list(features.LAG_FEATURES),
        "solar": [c for c in features.SOLAR_FEATURES if c in cols],
        "extras": [c for c in features.EXTRA_CANDIDATES if c in cols],
        "horizons": list(HORIZONS),
        "targets": {"h%d" % h: features.target_column(h) for h in HORIZONS},
    }
    nights_payload = {
        "year": TEST_YEAR,
        "condition": "18시 지면온도 > 0 이고 다음 날 09시까지 최저 ≤ 0",
        "score": "min(직전 12시간 강수+적설, %.0fmm) + min(18시→최저 하강 폭, %.0f°C)"
                 % (NIGHT_WET_CAP, NIGHT_DROP_CAP),
        "default": nights[0]["night"] if nights else None,
        "nights": nights,
    }

    _write_json(models_dir / "calib.json", calib_payload)
    _write_json(models_dir / "features.json", features_payload)
    _write_json(models_dir / "nights.json", nights_payload)
    _write_json(models_dir / "metrics.json", metrics)
    return models_dir


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")


def _fmt(value, width=8, digits=2):
    if value is None:
        return "-".rjust(width)
    return ("%.*f" % (digits, float(value))).rjust(width)


def print_report(metrics):
    """저장본·새 학습 모두 이 함수로 표를 찍는다."""
    data = metrics.get("data", {})
    print("")
    print("[지점 %s %s] %s ~ %s" % (
        metrics.get("station"), metrics.get("station_name", ""),
        data.get("start"), data.get("end"),
    ))
    print("  격자 %s행 / 관측 지면 %s행 / 학습 %s행" % (
        data.get("rows"), data.get("observed_rows"), metrics.get("rows", {}).get("train"),
    ))

    used = metrics.get("features", {}).get("used", [])
    solar = metrics.get("features", {}).get("solar", [])
    extras = metrics.get("features", {}).get("extras", [])
    print("  피처 %d개: %s" % (len(used), ", ".join(used)))
    if solar:
        print("  일사·일조: 사용 %s" % ", ".join(solar))
    else:
        print("  일사·일조: 자료에 없어 제외")

    rejected = metrics.get("features", {}).get("rejected", {})
    if extras:
        print("  개선 피처 채택: %s" % ", ".join(extras))
    if rejected:
        print("  개선 피처 탈락: %s" % ", ".join(sorted(rejected)))

    print("")
    print("[방법 선택 — %d 검증 Brier, 학습 ≤%d·보정 %d]" % (
        SELECT_VAL_YEAR, SELECT_FIT_END, SELECT_CAL_YEAR,
    ))
    print("  %-3s %8s %8s %8s   %s" % ("h", "reg", "clf", "blend", "선택"))
    selection = metrics.get("method_selection", {})
    for h in HORIZONS:
        key = "h%d" % h
        item = selection.get(key, {})
        briers = item.get("brier", {})
        print("  %-3s %s %s %s   %s" % (
            key,
            _fmt(briers.get("reg"), digits=4),
            _fmt(briers.get("clf"), digits=4),
            _fmt(briers.get("blend"), digits=4),
            item.get("method", "-") if briers else "%s(고정)" % item.get("method", "-"),
        ))

    print("")
    print("[%d 시험 — 방법별 확률과 기준선]" % TEST_YEAR)
    print("  %-3s %-6s %8s %8s %8s %8s %8s" % (
        "h", "방법", "RMSE", "지속", "공기온도", "Brier", "결빙비율",
    ))
    horizons = metrics.get("horizons", {})
    for h in HORIZONS:
        key = "h%d" % h
        item = horizons.get(key) or {}
        print("  %-3s %-6s %s %s %s %s %s" % (
            key,
            item.get("method", "-"),
            _fmt(item.get("rmse")),
            _fmt(item.get("persistence_rmse")),
            _fmt(item.get("air_rmse")),
            _fmt(item.get("brier"), digits=4),
            _fmt(item.get("freeze_rate")),
        ))

    print("")
    print("[rolling 검증 — 시험 연도별 RMSE(모델 / persistence / 공기온도)]")
    print("  %-5s %-3s %8s %8s %8s" % ("연도", "h", "모델", "지속", "공기"))
    rolling = metrics.get("rolling", {})
    for year in sorted(rolling):
        for h in HORIZONS:
            key = "h%d" % h
            item = rolling.get(year, {}).get(key) or {}
            print("  %-5s %-3s %s %s %s" % (
                year, key,
                _fmt(item.get("rmse")),
                _fmt(item.get("persistence_rmse")),
                _fmt(item.get("air_rmse")),
            ))

    events = metrics.get("events", {})
    if events:
        print("")
        print("[사건 지표 %d 밤 — 경보 = 18:00~09:00 p_max ≥ %.1f]" % (
            events.get("year", TEST_YEAR), events.get("p_threshold", DISPATCH_P),
        ))
        print("  밤 %d개(결빙 %d / 비결빙 %d), 경보 %d밤" % (
            events.get("nights_total", 0), events.get("freezing_nights", 0),
            events.get("clear_nights", 0), events.get("alarm_nights", 0),
        ))
        print("  결빙 밤 적중률 %s (%d/%d), 첫 경보 선행 중앙값 %s시간, 오경보율 %s" % (
            _fmt(events.get("hit_rate"), digits=3),
            events.get("hits", 0), events.get("freezing_nights", 0),
            _fmt(events.get("median_lead_hours"), digits=1),
            _fmt(events.get("false_alarm_rate"), digits=3),
        ))
        print(" 18시에 이미 지면 ≤ 0이던 밤 %d개(선행 0시간으로 계산), 창 안에서 결빙이 시작된 밤 %d개" % (
            events.get("start_frozen_nights", 0),
            events.get("onset_nights", 0),
        ))
        print("  창 안 시작 밤의 선행 중앙값 %s시간, 결빙보다 늦은 경보 %d밤" % (
            _fmt(events.get("median_lead_hours_onset"), digits=1),
            events.get("late_nights", 0),
        ))

    timing = metrics.get("timing", {})
    print("")
    print("[저장] %s" % metrics.get("models_dir", "-"))
    print("  reg_h0..h6 · clf_h1·h3·h6 · calib.json · metrics.json · nights.json · features.json"
          " (학습 %.1f초)" % float(timing.get("seconds", 0.0)))
    print("")


# ---------------------------------------------------------------- 실행

def train(stn, models_dir=None, quiet=False):
    """지점 학습 한 번. metrics dict를 돌려주고 산출물을 저장한다."""
    started = time.time()
    models_dir = Path(models_dir) if models_dir else MODELS_ROOT / str(stn)

    files = kma.station_files(stn)
    if not files:
        raise kma.StationDataMissing(
            "지점 %s 자료가 없다: %s 안에 CSV가 없다" % (stn, kma.station_dir(stn))
        )

    raw = kma.load_station(stn)
    frame = features.build_features(raw)
    base_cols = features.feature_columns(frame)
    solar_cols = features.solar_used(frame)

    accepted, experiment = feature_experiment(frame, base_cols)
    cols = base_cols + accepted
    rejected = {name: detail for name, detail in experiment.items()
                if name != "base" and isinstance(detail, dict) and not detail.get("accepted")}

    methods, selection = select_methods(frame, cols)
    reg, clf, calib = fit_final(frame, cols)
    horizons = test_metrics(frame, cols, reg, clf, calib, methods)
    rolling = rolling_validation(frame, cols)
    events = event_metrics(frame, cols, reg, clf, calib, methods)
    nights = replay_nights(frame)
    elapsed = time.time() - started

    train_rows = 0
    for h in HORIZONS:
        data = _rows(frame, cols, h)
        train_rows = max(train_rows, int(len(_fit_rows(data, h, TRAIN_END))))

    metrics = {
        "model": MODEL_NAME,
        "station": str(stn),
        "station_name": kma.STATION_NAMES.get(str(stn), ""),
        "trained_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "models_dir": display_path(models_dir),
        "data": {
            "files": [path.name for path in files],
            "rows": int(len(frame)),
            "observed_rows": int(frame["ground_temp"].notna().sum()),
            "start": frame.index.min().isoformat() if len(frame) else None,
            "end": frame.index.max().isoformat() if len(frame) else None,
            "solar": solar_cols,
        },
        "split": {
            "train": "≤%d" % TRAIN_END,
            "test": str(TEST_YEAR),
            "calibration": str(CALIB_YEAR),
            "method_selection": {
                "fit": "≤%d" % SELECT_FIT_END,
                "calibration": str(SELECT_CAL_YEAR),
                "validation": str(SELECT_VAL_YEAR),
            },
        },
        "rows": {"train": int(train_rows)},
        "features": {
            "used": list(cols),
            "base": list(features.BASE_FEATURES),
            "lags": list(features.LAG_FEATURES),
            "solar": list(solar_cols),
            "extras": list(accepted),
            "rejected": rejected,
            "experiment": experiment,
        },
        "params": dict(XGB_PARAMS),
        "baselines": {
            "persistence": "h>0: 그 시각 관측 지면온도, h0: 직전 시각(gt_lag1)",
            "air": "그 시각 기온",
        },
        "methods": methods,
        "method_selection": selection,
        "horizons": horizons,
        "rolling": rolling,
        "events": events,
        "timing": {"seconds": round(elapsed, 2)},
    }
    save_artifacts(stn, models_dir, cols, reg, clf, calib, metrics, nights)
    if not quiet:
        print_report(metrics)
    return metrics


def load_saved(stn, models_dir=None):
    """저장된 metrics.json을 읽는다(없으면 None)."""
    folder = Path(models_dir) if models_dir else MODELS_ROOT / str(stn)
    path = folder / "metrics.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="지점별 ICE-ZERO 학습")
    parser.add_argument("--stn", default="119", help="지점 번호(108 서울, 119 수원)")
    parser.add_argument("--force", action="store_true", help="저장본이 있어도 다시 학습")
    parser.add_argument("--models-dir", default=None, help="산출물 폴더(기본 model/models/<stn>)")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    stn = str(args.stn)
    if not kma.station_files(stn):
        print("[중단] 지점 %s 원본 CSV가 없다: %s" % (stn, kma.station_dir(stn)), file=sys.stderr)
        print("       기상자료개방포털 OBS_ASOS_TIM_*.csv 를 그 폴더에 넣고 다시 실행한다.", file=sys.stderr)
        return 2

    if not args.force:
        saved = load_saved(stn, args.models_dir)
        if saved is not None:
            print("[저장본] %s · %s (다시 학습하려면 --force)" % (
                saved.get("trained_at"), saved.get("models_dir"),
            ))
            print_report(saved)
            return 0

    metrics = train(stn, models_dir=args.models_dir)
    return 0 if metrics else 1


if __name__ == "__main__":
    raise SystemExit(main())
