# -*- coding: utf-8 -*-
"""ICE-ZERO 사거리 엔진 (계약 3절).

맥북이 맡는 계산을 모두 담는다.

    자료 로드(BOM) → 전체 시간 reindex → 피처(v10, 일사·일조 제외)
    → 시점별 XGBoost(≤2024 학습, 2025 시험) → isotonic 동결확률 보정
    → 갈래 유효온도·현장 보정·동결확률·단계·후보·우선순위·선정·순서
    → 밤 찾기(nights) → step(계약 JSON)

설계 원칙
- 학습·평가 수치는 숨기지 않는다. metrics.json에 모두 남기고 step 결과에도 싣는다.
- 결빙을 '확정'하지 않는다. 값은 전부 확률과 상대 순위다.
- step은 피처 행렬과 예측을 시각 단위로 캐시해 0.2초 안에 끝낸다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBRegressor

# ---------------------------------------------------------------- 상수(계약)

ARM_ORDER = ("N", "E", "S", "W")
HORIZONS = (0, 1, 3, 6)

# ICE-ZERO v10 피처. 일사(solar)·일조(sunshine)는 ASOS 겨울 정리본에 없어 뺐다.
BASE_FEATURES = [
    "temp", "temp_6h_mean", "humidity", "dewpoint_depression", "wind",
    "precip_6h", "snow", "new_snow_6h", "hour_sin", "hour_cos", "day_sin", "day_cos",
]
LAG_FEATURES = [
    "gt_lag1", "gt_lag2", "gt_lag3", "gt_lag6", "gt_roll6", "gt_trend3", "air_gt_gap_lag1",
]
FEATURES = BASE_FEATURES + LAG_FEATURES

XGB_PARAMS = dict(
    n_estimators=600,
    learning_rate=0.05,
    max_depth=6,
    subsample=0.9,
    colsample_bytree=0.9,
    random_state=42,
    n_jobs=4,
)

MODEL_NAME = "ICE-ZERO 예보 경량 재현(XGBoost+시차, 일사·일조 제외)"

BRIDGE_DELTA_C = 2.5      # 교량 공학 가정: 교량 노면이 관측소 지면보다 2.5°C 낮다
DISPATCH_P = 0.5          # 출동 후보 문턱
LEVEL_RISK3 = 0.6
LEVEL_RISK2 = 0.3
BUDGET_DEFAULT = 2
BUDGET_MIN = 0
BUDGET_MAX = 4
REPORT_BONUS = 0.5        # 확인된 제보 하나가 더하는 우선순위
SENSOR_MAX_AGE_SEC = 300  # 이보다 오래된 센서값은 현장 보정에 쓰지 않는다

# 밤 점수(계약: "직전 12시간 강수·적설(젖음)과 하강 폭")
NIGHT_WET_CAP = 5.0       # 젖음(mm) 포화점: 5mm 넘으면 '충분히 젖음'
NIGHT_DROP_CAP = 8.0      # 하강 폭(°C) 포화점: 8°C 넘는 하강은 더 세지 않는다

NOTE_CALIB = "동결확률은 관측소 지면온도 보정곡선을 갈래 유효온도에 적용한 값(가정)"
NOTE_RISK = "risk_v2는 ICE-ZERO 상대 순위"
NOTE_SENSOR = "교량 갈래는 현장 센서값으로 보정됨"

_HERE = Path(__file__).resolve().parent
DEFAULT_DATA = _HERE / "data" / "weather_winter_clean.csv"
DEFAULT_MODELS = _HERE / "models"
DEFAULT_ARMS = _HERE / "data" / "cross_arms.json"


# ---------------------------------------------------------------- 순수 함수

def dewpoint(temp, humidity):
    """Magnus 식 이슬점(°C). temp·humidity는 스칼라도 Series도 된다."""
    t = pd.to_numeric(temp, errors="coerce")
    rh = np.clip(pd.to_numeric(humidity, errors="coerce"), 0.1, 100.0)
    gamma = np.log(rh / 100.0) + (17.67 * t) / (243.5 + t)
    return (243.5 * gamma) / (17.67 - gamma)


def clamp_budget(value):
    """예산을 0~4 정수로 맞춘다. None·변환 불가는 기본값 2."""
    if value is None or isinstance(value, bool):
        return BUDGET_DEFAULT
    try:
        n = int(value)
    except (TypeError, ValueError):
        return BUDGET_DEFAULT
    return max(BUDGET_MIN, min(BUDGET_MAX, n))


def level_of(p_max):
    """동결확률 최댓값 → 위험 단계."""
    p = float(p_max or 0.0)
    if p >= LEVEL_RISK3:
        return "risk3"
    if p >= LEVEL_RISK2:
        return "risk2"
    return "risk1"


def priority_of(risk_v2, reported):
    """우선순위 = risk_v2 + 0.5×(확인된 제보)."""
    return float(risk_v2 or 0.0) + (REPORT_BONUS if reported else 0.0)


def select_arms(priorities, candidates, budget=BUDGET_DEFAULT):
    """후보를 (−priority, N·E·S·W 순)으로 정렬해 예산만큼 고른다.

    고른 목록의 순서가 곧 처리 순서다(한 교차로라 경로 = 우선순위).
    """
    limit = clamp_budget(budget)
    if limit <= 0:
        return []
    picked = [a for a in ARM_ORDER if candidates.get(a)]
    picked.sort(key=lambda a: (-float(priorities.get(a, 0.0)), ARM_ORDER.index(a)))
    return picked[:limit]


def apply_isotonic(x, xs, ys):
    """보정곡선 적용. sklearn out_of_bounds='clip'과 같은 선형보간·양끝 고정."""
    if x is None or xs is None or len(xs) == 0:
        return 0.0
    try:
        value = float(x)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(value):
        return 0.0
    return float(min(1.0, max(0.0, np.interp(value, xs, ys))))


def load_raw(path):
    """ASOS 겨울 시간 자료를 읽는다. BOM(utf-8-sig)과 '일시' 열 이름을 처리한다."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
    rename = {"일시": "ts", "일시(KST)": "ts", "날짜": "ts", "time": "ts", "date": "ts"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "ts" not in df.columns:
        raise ValueError("자료에 '일시' 열이 없다: %s" % path)
    keep = ["ts", "temp", "precip", "wind", "humidity", "snow", "ground_temp"]
    missing = [c for c in keep if c not in df.columns]
    if missing:
        raise ValueError("자료에 필요한 열이 없다: %s" % ", ".join(missing))
    df = df[keep].copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.drop_duplicates("ts").sort_values("ts")
    for col in keep[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.set_index("ts")


def reindex_hourly(df):
    """전체 시간 범위로 reindex한다. 겨울 시즌 사이 공백은 NaN → 시차 누수를 막는다."""
    if df.empty:
        return df
    full = pd.date_range(df.index.min(), df.index.max(), freq="h")
    return df.reindex(full).rename_axis("ts")


def add_features(frame):
    """피처(v10 경량 재현)와 목표 열을 붙인다. 시프트는 reindex 뒤에 하므로 안전하다."""
    head = ["temp", "precip", "wind", "humidity", "snow", "ground_temp"]
    d = frame[head].copy()
    gt = d["ground_temp"]

    d["temp_6h_mean"] = d["temp"].rolling(6, min_periods=6).mean()
    d["dewpoint_depression"] = d["temp"] - dewpoint(d["temp"], d["humidity"])
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

    for h in HORIZONS:
        d["target_h%d" % h] = gt.shift(-h)
    return d


def _rmse(y, pred):
    y = np.asarray(y, dtype="float64")
    pred = np.asarray(pred, dtype="float64")
    ok = np.isfinite(y) & np.isfinite(pred)
    if not ok.any():
        return float("nan")
    return float(np.sqrt(np.mean((y[ok] - pred[ok]) ** 2)))


def _mae(y, pred):
    y = np.asarray(y, dtype="float64")
    pred = np.asarray(pred, dtype="float64")
    ok = np.isfinite(y) & np.isfinite(pred)
    if not ok.any():
        return float("nan")
    return float(np.mean(np.abs(y[ok] - pred[ok])))


def _brier(y_freeze, p):
    y = np.asarray(y_freeze, dtype="float64")
    p = np.asarray(p, dtype="float64")
    ok = np.isfinite(y) & np.isfinite(p)
    if not ok.any():
        return float("nan")
    return float(np.mean((p[ok] - y[ok]) ** 2))


def _r4(value):
    """지표용 반올림. NaN은 None으로 내보낸다."""
    v = float(value)
    return None if not np.isfinite(v) else round(v, 4)


# ---------------------------------------------------------------- 엔진

class Engine:
    """사거리 4갈래 예측 엔진. 서버는 Engine().load() 뒤 step()을 부른다."""

    def __init__(self, data_path=None, models_dir=None, arms_path=None):
        self.data_path = Path(data_path or DEFAULT_DATA)
        self.models_dir = Path(models_dir or DEFAULT_MODELS)
        self.arms_path = Path(arms_path or DEFAULT_ARMS)
        self.arms = self._read_arms()

        self.models = {}
        self.calib = {}
        self._iso = {}
        self.metrics = {}
        self.night_list = []
        self.default_night = None
        self.loaded_from = None      # "saved" 또는 "trained"

        self._frame = None
        self._x_cache = {}
        self._pred_cache = {}

    # ------------------------------------------------------------ 준비

    def _read_arms(self):
        with open(self.arms_path, "r", encoding="utf-8") as fp:
            raw = json.load(fp)
        arms = raw.get("arms", raw)
        return {a: dict(arms[a]) for a in ARM_ORDER if a in arms}

    @property
    def frame(self):
        """피처가 붙은 전체 시간 프레임(캐시)."""
        return self.ensure_frame()

    def ensure_frame(self):
        if self._frame is None:
            self._frame = add_features(reindex_hourly(load_raw(self.data_path)))
        return self._frame

    def models_exist(self):
        """models/에 계약이 요구하는 파일이 모두 있는지."""
        need = ["xgb_h%d.json" % h for h in HORIZONS]
        need += ["calib.json", "metrics.json", "nights.json"]
        return all((self.models_dir / name).exists() for name in need)

    # ------------------------------------------------------------ 학습

    def train(self):
        """시점별 모델을 학습하고 보정곡선·지표·밤 목록을 계산한다(저장은 save)."""
        frame = self.ensure_frame()
        horizons = {}
        models = {}
        calib = {}
        iso_arrays = {}
        train_rows = test_rows = 0

        for h in HORIZONS:
            target = "target_h%d" % h
            data = frame.dropna(subset=FEATURES + [target])
            tr = data[data.index.year <= 2024]
            te = data[data.index.year == 2025]
            train_rows, test_rows = len(tr), len(te)
            if len(tr) < 100 or len(te) == 0:
                raise RuntimeError("학습/시험 행이 부족하다(h%d): train=%d test=%d" % (h, len(tr), len(te)))

            model = XGBRegressor(**XGB_PARAMS).fit(tr[FEATURES], tr[target])
            pred_te = model.predict(te[FEATURES])

            # 보정: 2020~2023 학습 모델의 2024 예측 → 실제 ground_temp ≤ 0 여부
            early = data[data.index.year <= 2023]
            cal_year = data[data.index.year == 2024]
            if len(early) > 100 and len(cal_year) > 0:
                early_model = XGBRegressor(**XGB_PARAMS).fit(early[FEATURES], early[target])
                pred_cal = early_model.predict(cal_year[FEATURES])
                y_cal = (cal_year[target].to_numpy(dtype="float64") <= 0).astype("float64")
                iso = IsotonicRegression(increasing=False, out_of_bounds="clip").fit(pred_cal, y_cal)
                xs = np.asarray(iso.X_thresholds_, dtype="float64")
                ys = np.asarray(iso.y_thresholds_, dtype="float64")
                calib_note = "isotonic(2020~2023 학습 모델의 2024 예측 → ground_temp ≤ 0)"
            else:  # 자료가 짧을 때의 안전망: 시험 구간으로 맞춘다(표시에 남긴다)
                y_cal = (te[target].to_numpy(dtype="float64") <= 0).astype("float64")
                iso = IsotonicRegression(increasing=False, out_of_bounds="clip").fit(pred_te, y_cal)
                xs = np.asarray(iso.X_thresholds_, dtype="float64")
                ys = np.asarray(iso.y_thresholds_, dtype="float64")
                calib_note = "isotonic(자료 부족: 시험 구간 적합)"

            y_te = te[target].to_numpy(dtype="float64")
            p_te = np.interp(pred_te, xs, ys) if len(xs) else np.zeros_like(pred_te)
            persistence = (te["ground_temp"] if h > 0 else te["gt_lag1"]).to_numpy(dtype="float64")
            air = te["temp"].to_numpy(dtype="float64")

            models[h] = model
            iso_arrays[h] = (xs, ys)
            calib["h%d" % h] = {
                "fit": calib_note,
                "x": [round(float(v), 6) for v in xs],
                "y": [round(float(v), 6) for v in ys],
            }
            horizons["h%d" % h] = {
                "rmse": _r4(_rmse(y_te, pred_te)),
                "mae": _r4(_mae(y_te, pred_te)),
                "persistence_rmse": _r4(_rmse(y_te, persistence)),
                "persistence_mae": _r4(_mae(y_te, persistence)),
                "air_rmse": _r4(_rmse(y_te, air)),
                "air_mae": _r4(_mae(y_te, air)),
                "brier": _r4(_brier(y_te <= 0, p_te)),
                "brier_hard": _r4(_brier(y_te <= 0, (pred_te <= 0).astype("float64"))),
                "freeze_rate": _r4(float(np.mean(y_te <= 0))),
                "calib_rows": int(len(y_cal)),
            }

        self.models = models
        self.calib = calib
        self._iso = iso_arrays
        self._pred_cache.clear()

        nights = self.find_nights(year=2025)
        self.night_list = nights
        self.default_night = nights[0]["night"] if nights else None

        self.metrics = {
            "model": MODEL_NAME,
            "trained_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "data": {
                "path": str(self.data_path),
                "rows": int(len(frame)),
                "observed_rows": int(frame["ground_temp"].notna().sum()),
                "start": frame.index.min().isoformat() if len(frame) else None,
                "end": frame.index.max().isoformat() if len(frame) else None,
            },
            "split": {"train": "2020~2024", "test": "2025", "calibration": "2024"},
            "rows": {"train": int(train_rows), "test": int(test_rows)},
            "features": list(FEATURES),
            "excluded": ["solar", "solar_3h_sum", "sunshine"],
            "params": dict(XGB_PARAMS),
            "horizons": horizons,
        }
        return self.metrics

    def save(self):
        """models/에 저장한다. 모델은 xgboost JSON, 보정은 thresholds JSON."""
        self.models_dir.mkdir(parents=True, exist_ok=True)
        for h, model in self.models.items():
            model.save_model(str(self.models_dir / ("xgb_h%d.json" % h)))
        calib = {
            "note": "isotonic 동결확률 보정곡선(임계값 배열). x=예측 지면온도, y=P(ground_temp≤0)",
            "method": "sklearn.isotonic.IsotonicRegression(increasing=False, out_of_bounds='clip')",
            "applied_to": "갈래 유효온도(°C)",
            "horizons": self.calib,
        }
        self._write_json(self.models_dir / "calib.json", calib)
        self._write_json(self.models_dir / "metrics.json", self.metrics)
        self._write_json(
            self.models_dir / "nights.json",
            {
                "year": 2025,
                "condition": "18시 지면온도 > 0 이고 다음 날 09시까지 최저 ≤ 0",
                "score": "min(직전 12시간 강수+적설, 5mm) + min(18시→최저 하강 폭, 8°C)",
                "default": self.default_night,
                "nights": [{k: v for k, v in n.items() if not k.startswith("_")} for n in self.night_list],
            },
        )
        return self.models_dir

    @staticmethod
    def _write_json(path, payload):
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
            fp.write("\n")

    # ------------------------------------------------------------ 불러오기

    def load(self, force=False):
        """models/가 있으면 불러오고 없으면 학습한다. 서버는 이것만 부르면 된다."""
        self.ensure_frame()
        if force or not self.models_exist():
            self.train()
            self.save()
            self.loaded_from = "trained"
            return self
        for h in HORIZONS:
            model = XGBRegressor(**XGB_PARAMS)
            model.load_model(str(self.models_dir / ("xgb_h%d.json" % h)))
            self.models[h] = model
        with open(self.models_dir / "calib.json", "r", encoding="utf-8") as fp:
            calib = json.load(fp)
        self.calib = calib.get("horizons", {})
        self._iso = {
            h: (
                np.asarray(self.calib.get("h%d" % h, {}).get("x", []), dtype="float64"),
                np.asarray(self.calib.get("h%d" % h, {}).get("y", []), dtype="float64"),
            )
            for h in HORIZONS
        }
        with open(self.models_dir / "metrics.json", "r", encoding="utf-8") as fp:
            self.metrics = json.load(fp)
        with open(self.models_dir / "nights.json", "r", encoding="utf-8") as fp:
            nights = json.load(fp)
        self.night_list = nights.get("nights", [])
        self.default_night = nights.get("default") or (self.night_list[0]["night"] if self.night_list else None)
        self.loaded_from = "saved"
        return self

    # ------------------------------------------------------------ 예측

    def _resolve(self, ts):
        """시각을 자료 격자(정시)에 맞춘다. 범위 밖은 양끝으로 붙인다."""
        stamp = pd.Timestamp(pd.to_datetime(ts))
        if stamp.tzinfo is not None:
            stamp = stamp.tz_localize(None)
        stamp = stamp.floor("h")
        index = self.frame.index
        if len(index) == 0:
            raise ValueError("자료가 비어 있다")
        if stamp < index[0]:
            stamp = index[0]
        elif stamp > index[-1]:
            stamp = index[-1]
        elif stamp not in index:
            pos = index.searchsorted(stamp)
            before, after = index[pos - 1], index[pos]
            stamp = before if (stamp - before) <= (after - stamp) else after
        return stamp

    def _features_at(self, stamp):
        cached = self._x_cache.get(stamp)
        if cached is None:
            cached = self.frame.loc[[stamp], FEATURES]
            if len(self._x_cache) > 4096:
                self._x_cache.clear()
            self._x_cache[stamp] = cached
        return cached

    def predict(self, ts):
        """h0·h1·h3·h6 지면온도 예측(°C). 시각 단위로 캐시한다."""
        if not self.models:
            raise RuntimeError("모델이 없다. Engine.load()를 먼저 부른다")
        stamp = self._resolve(ts)
        cached = self._pred_cache.get(stamp)
        if cached is not None:
            return cached
        X = self._features_at(stamp)
        out = {h: float(self.models[h].predict(X)[0]) for h in HORIZONS}
        if len(self._pred_cache) > 4096:
            self._pred_cache.clear()
        self._pred_cache[stamp] = out
        return out

    def calib_curve(self, h):
        xs, ys = self._iso.get(h, (np.array([]), np.array([])))
        return xs, ys

    # ------------------------------------------------------------ 밤 찾기

    def find_nights(self, year=2025):
        """18시 지면온도 > 0 이고 다음 날 09시까지 최저 ≤ 0인 밤을 점수순으로 모은다."""
        frame = self.ensure_frame()
        found = []
        for stamp in frame.index[frame.index.hour == 18]:
            if stamp.year != year:
                continue
            gt18 = frame.at[stamp, "ground_temp"]
            if pd.isna(gt18) or float(gt18) <= 0.0:
                continue
            end = stamp.normalize() + pd.Timedelta(days=1, hours=9)
            if end not in frame.index:  # 09시까지 자료가 있어야 재생할 수 있다
                continue
            window = frame.loc[stamp:end, "ground_temp"].dropna()
            if window.empty:
                continue
            t_min = float(window.min())
            if t_min > 0.0:
                continue
            wet_from = stamp - pd.Timedelta(hours=13)
            wet_to = stamp - pd.Timedelta(hours=1)
            wet = frame.loc[wet_from:wet_to]
            wet_12 = float(wet["precip"].fillna(0.0).sum() + wet["snow"].fillna(0.0).sum())
            drop = float(gt18) - t_min
            score = min(wet_12, NIGHT_WET_CAP) + min(drop, NIGHT_DROP_CAP)
            found.append({
                "night": stamp.strftime("%Y-%m-%d"),
                "t18": round(float(gt18), 2),
                "t_min": round(t_min, 2),
                "min_time": window.idxmin().isoformat(),
                "drop": round(drop, 2),
                "wet_12h": round(wet_12, 2),
                "score": round(score, 2),
                "_stamp": stamp,
            })
        found.sort(key=lambda n: (-n["score"], n["night"]))
        return found

    def nights(self, year=2025):
        """그 해 후보 밤 목록(점수 내림차순). 2025는 저장본을 그대로 쓴다."""
        if int(year) == 2025 and self.night_list:
            return [dict(n) for n in self.night_list]
        return [
            {k: v for k, v in n.items() if not k.startswith("_")}
            for n in self.find_nights(year=int(year))
        ]

    def night_info(self, night):
        """밤 하나의 요약(없으면 None). night는 'YYYY-MM-DD'."""
        key = str(night)[:10]
        for item in self.night_list:
            if item.get("night") == key:
                return {k: v for k, v in item.items() if not k.startswith("_")}
        for item in self.find_nights(year=int(key[:4])):
            if item["night"] == key:
                return {k: v for k, v in item.items() if not k.startswith("_")}
        return None

    def timeline(self, night=None):
        """그날 18:00부터 다음 날 09:00까지 정시 목록(ISO 문자열)."""
        key = str(night or self.default_night or "")
        if not key:
            raise ValueError("밤이 없다. nights.json을 먼저 만든다")
        start = pd.Timestamp(key[:10]) + pd.Timedelta(hours=18)
        return [(start + pd.Timedelta(hours=i)).isoformat() for i in range(16)]

    # ------------------------------------------------------------ 센서·제보

    def _bridge_sensor_temp(self, sensor, stamp):
        """신선한 교량 센서값(°C). 없거나 오래됐으면 None."""
        if not sensor or not isinstance(sensor, dict):
            return None
        if sensor.get("use_sensor") is False or sensor.get("use") is False:
            return None
        raw = sensor.get("t_bridge")
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(value):
            return None
        age = sensor.get("age_sec", sensor.get("age"))
        if age is not None:
            try:
                if float(age) > SENSOR_MAX_AGE_SEC:
                    return None
            except (TypeError, ValueError):
                pass
        when = sensor.get("ts") or sensor.get("time")
        if when:
            try:
                skew = abs((stamp - pd.Timestamp(pd.to_datetime(when))).total_seconds())
                if skew > SENSOR_MAX_AGE_SEC:
                    return None
            except (TypeError, ValueError):
                pass
        return value

    @staticmethod
    def _reported_arms(reports):
        """확인된 제보에서 갈래 집합을 뽑는다. dict/리스트/문자열 모두 받는다."""
        out = set()
        if not reports:
            return out
        if isinstance(reports, (str, dict)):
            reports = [reports]
        for item in reports:
            if isinstance(item, str):
                arms = [item]
            elif isinstance(item, dict):
                if item.get("confirmed") is False or item.get("status") in ("pending", "rejected"):
                    continue
                arms = item.get("arms")
                if not arms and item.get("arm"):
                    arms = [item["arm"]]
                if isinstance(arms, str):
                    arms = [arms]
                if not arms:
                    arms = []
            else:
                arms = list(item)
            for arm in arms:
                key = str(arm).strip().upper()
                if key in ARM_ORDER:
                    out.add(key)
        return out

    # ------------------------------------------------------------ step

    def step(self, ts, sensor=None, reports=None, budget=BUDGET_DEFAULT):
        """계약 3절의 step JSON을 만든다. 값은 소수 3자리."""
        stamp = self._resolve(ts)
        pred = self.predict(stamp)
        row = self.frame.loc[stamp]

        def num(value, digits=3, as_int=False):
            if value is None or (isinstance(value, float) and not np.isfinite(value)):
                return None
            if pd.isna(value):
                return None
            return int(round(float(value))) if as_int else round(float(value), digits)

        obs = {
            "temp": num(row.get("temp"), 1),
            "humidity": num(row.get("humidity"), 0, as_int=True),
            "wind": num(row.get("wind"), 1),
            "precip": num(row.get("precip"), 1),
            "snow": num(row.get("snow"), 1),
            "ground_temp": num(row.get("ground_temp"), 1),
        }
        forecast = {"h%d" % h: round(float(pred[h]), 3) for h in HORIZONS}

        bridge_temp = self._bridge_sensor_temp(sensor, stamp)
        reported = self._reported_arms(reports)

        arms_out = {}
        priorities = {}
        candidates = {}
        sensor_used = False
        for arm_id in ARM_ORDER:
            meta = self.arms.get(arm_id, {})
            structure = int(meta.get("structure", 0) or 0)
            risk_v2 = float(meta.get("risk_v2", 0.0) or 0.0)
            shadow = float(meta.get("shadow_index", 0.0) or 0.0)

            offset = None
            if structure and bridge_temp is not None:
                offset = bridge_temp - (pred[0] - BRIDGE_DELTA_C * structure)
                sensor_used = True
            t_eff = {}
            p_freeze = {}
            for h in HORIZONS:
                key = "h%d" % h
                value = pred[h] - BRIDGE_DELTA_C * structure + (offset or 0.0)
                t_eff[key] = round(float(value), 3)
                xs, ys = self.calib_curve(h)
                p_freeze[key] = round(apply_isotonic(t_eff[key], xs, ys), 3)
            best_h = max((1, 3, 6), key=lambda h: (p_freeze["h%d" % h], -h))
            p_max = p_freeze["h%d" % best_h]

            is_reported = arm_id in reported
            priority = round(priority_of(risk_v2, is_reported), 3)
            candidate = bool(p_max >= DISPATCH_P or is_reported)

            reasons = []
            if structure:
                reasons.append("교량(%.1f°C 가정)" % BRIDGE_DELTA_C)
            if shadow >= 0.2:
                reasons.append("그늘 지수 %.2f" % shadow)
            if p_max >= DISPATCH_P:
                reasons.append("예측 동결확률 %.2f(+%dh)" % (p_max, best_h))
            elif p_max > 0.0:
                reasons.append("예측 동결확률 %.2f(+%dh) 낮음" % (p_max, best_h))
            if is_reported:
                reasons.append("확인된 제보")
            if offset is not None:
                reasons.append("교량 센서 보정 %+.1f°C" % offset)
            if not reasons:
                reasons.append("특이 신호 없음")

            arms_out[arm_id] = {
                "name": meta.get("name", arm_id),
                "label": meta.get("label", "general"),
                "structure": structure,
                "shadow_index": round(shadow, 3),
                "risk_v2": round(risk_v2, 3),
                "risk_v2_pct": round(float(meta.get("risk_v2_pct", 0.0) or 0.0), 3),
                "t_eff": t_eff,
                "p_freeze": p_freeze,
                "p_max": p_max,
                "source": "sensor" if offset is not None else "model",
                "level": level_of(p_max),
                "candidate": candidate,
                "priority": priority,
                "reasons": reasons,
            }
            priorities[arm_id] = priority
            candidates[arm_id] = candidate

        limit = clamp_budget(budget)
        selected = select_arms(priorities, candidates, limit)

        notes = [NOTE_CALIB, NOTE_RISK]
        if sensor_used:
            notes.append(NOTE_SENSOR)

        return {
            "time": stamp.isoformat(),
            "obs": obs,
            "forecast": forecast,
            "arms": arms_out,
            "dispatch": {
                "recommend": bool(selected),
                "selected": list(selected),
                "order": list(selected),
                "budget": limit,
                "threshold": DISPATCH_P,
            },
            "model": {
                "name": MODEL_NAME,
                "rmse": self._model_metric("rmse"),
                "persistence_rmse": self._model_metric("persistence_rmse"),
                "brier": self._model_metric("brier"),
            },
            "notes": notes,
        }

    def _model_metric(self, key):
        horizons = self.metrics.get("horizons", {}) if self.metrics else {}
        out = {}
        for h in HORIZONS:
            value = horizons.get("h%d" % h, {}).get(key)
            out["h%d" % h] = value
        return out
