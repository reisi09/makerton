# -*- coding: utf-8 -*-
"""피처 만들기 (계약 3절).

ICE-ZERO v10 피처(경량 재현)에 개선 후보를 더한다. 모든 피처는 시각 t까지의
자료만 쓴다. 목표는 ground_temp를 미래로 당긴 값(shift(−h))이라, 겨울 시즌
사이 공백에서 당겨지지 않도록 계절 경계가 NaN 행으로 남아 있어야 한다
(kma.load_station이 매시 reindex로 그 일을 한다).

일사·일조는 자료에 실제로 있을 때만 쓴다. 없으면 빼고 metrics에 적는다.

개선 후보(검증에서 이긴 것만 남긴다)
- dewpoint            : 절대 이슬점(°C). 복사 냉각이 시작되는 온도를 직접 준다.
- humidity_trend3     : 3시간 습도 변화. 결로·서리 직전의 습윤화를 잡는다.
- gt_min24            : 직전 24시간 최저 지면온도. 냉각의 출발점(바닥 상태)을 준다.
"""

import numpy as np
import pandas as pd

HORIZONS = (0, 1, 3, 6)

# ICE-ZERO v10 기준 피처
BASE_FEATURES = [
    "temp", "temp_6h_mean", "humidity", "dewpoint_depression", "wind",
    "precip_6h", "snow", "new_snow_6h", "hour_sin", "hour_cos", "day_sin", "day_cos",
]
LAG_FEATURES = [
    "gt_lag1", "gt_lag2", "gt_lag3", "gt_lag6", "gt_roll6", "gt_trend3", "air_gt_gap_lag1",
]

# 일사·일조(자료에 있을 때만)
SOLAR_FEATURES = ("solar", "solar_3h_sum", "sunshine")

# 개선 후보
EXTRA_CANDIDATES = ("dewpoint", "humidity_trend3", "gt_min24")

RAW_COLUMNS = ("temp", "precip", "wind", "humidity", "snow", "ground_temp", "sunshine", "solar")


def dewpoint(temp, humidity):
    """Magnus 식 이슬점(°C). 스칼라·Series 모두 받는다."""
    t = pd.to_numeric(temp, errors="coerce")
    rh = pd.to_numeric(humidity, errors="coerce").clip(lower=0.1, upper=100.0)
    gamma = np.log(rh / 100.0) + (17.67 * t) / (243.5 + t)
    return (243.5 * gamma) / (17.67 - gamma)


def target_column(h):
    """시점 h의 목표 열 이름."""
    return "target_h%d" % int(h)


def build_features(frame):
    """원자료 표에 피처·목표 열을 붙인다(인덱스 time 유지).

    시프트·롤링은 매시 reindex가 끝난 표에서만 계산하므로 공백을 건너뛰지 않는다.
    """
    d = frame.copy()
    for col in RAW_COLUMNS:
        if col not in d.columns:
            d[col] = np.nan
        d[col] = pd.to_numeric(d[col], errors="coerce")

    gt = d["ground_temp"]

    d["temp_6h_mean"] = d["temp"].rolling(6, min_periods=6).mean()
    d["dewpoint"] = dewpoint(d["temp"], d["humidity"])
    d["dewpoint_depression"] = d["temp"] - d["dewpoint"]
    d["humidity_trend3"] = d["humidity"] - d["humidity"].shift(3)
    d["precip_6h"] = d["precip"].rolling(6, min_periods=6).sum()
    d["new_snow_6h"] = (d["snow"] - d["snow"].shift(6)).clip(lower=0.0)

    hour = d.index.hour.to_numpy(dtype="float64")
    doy = d.index.dayofyear.to_numpy(dtype="float64")
    d["hour_sin"] = np.sin(2.0 * np.pi * hour / 24.0)
    d["hour_cos"] = np.cos(2.0 * np.pi * hour / 24.0)
    d["day_sin"] = np.sin(2.0 * np.pi * doy / 366.0)
    d["day_cos"] = np.cos(2.0 * np.pi * doy / 366.0)

    d["gt_lag1"] = gt.shift(1)
    d["gt_lag2"] = gt.shift(2)
    d["gt_lag3"] = gt.shift(3)
    d["gt_lag6"] = gt.shift(6)
    d["gt_roll6"] = gt.shift(1).rolling(6, min_periods=6).mean()
    d["gt_trend3"] = gt.shift(1) - gt.shift(4)
    d["air_gt_gap_lag1"] = d["temp"] - gt.shift(1)
    d["gt_min24"] = gt.shift(1).rolling(24, min_periods=18).min()

    if d["solar"].notna().any():
        d["solar_3h_sum"] = d["solar"].rolling(3, min_periods=3).sum()

    for h in HORIZONS:
        d[target_column(h)] = gt.shift(-int(h)) if h else gt
    return d


def feature_columns(frame, extras=()):
    """실제로 채워진 열만 골라 피처 목록을 만든다(일사·일조·개선 후보 포함)."""
    names = list(BASE_FEATURES) + list(LAG_FEATURES)
    for col in SOLAR_FEATURES:
        if col in frame.columns and frame[col].notna().any():
            names.append(col)
    names.extend(extras)

    out = []
    for col in names:
        if col in out:
            continue
        if col in frame.columns and frame[col].notna().any():
            out.append(col)
    return out


def solar_used(frame):
    """이 표가 일사·일조를 실제로 쓰는지."""
    return [c for c in SOLAR_FEATURES if c in frame.columns and frame[c].notna().any()]
