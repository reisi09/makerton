# -*- coding: utf-8 -*-
"""교차로 4갈래 예측 엔진 (계약 3절).

서버는 `Engine(stn).load()` 뒤 `step(ts, local, treated, budget)`만 부른다.

    지점 모델(model/models/<stn>/) → 시점별 예측 h0·h1·h3·h6(지면온도)
    → 갈래 유효온도 t_eff = pred − 2.5×structure + local_dt
    → 갈래 동결확률(시점별 선택 방법: 회귀+isotonic / 분류 / 평균)
    → 위험 단계·후보·우선순위·선정 순서 → step JSON

원칙
- 결빙을 '확정'하지 않는다. 값은 예측 동결확률과 상대 우선순위다.
- 처리된(treated) 갈래는 단계가 done이고 후보에서 빠진다.
- 예측과 확률은 시각 단위로 캐시해 step 1회가 0.2초를 넘지 않게 한다.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import features, kma

ARM_ORDER = ("N", "E", "S", "W")
HORIZONS = (0, 1, 3, 6)
CLASS_HORIZONS = (1, 3, 6)

MODELS_ROOT = kma.MODEL_ROOT / "models"
DEFAULT_ARMS = kma.DATA_ROOT / "roads" / "cross_arms.json"

MODEL_NAME = "ICE-ZERO 고색 경량(XGBoost 시점별 회귀·분류 혼합)"

BRIDGE_DELTA_C = 2.5        # 교량 공학 가정: 교량 노면이 관측소 지면보다 2.5°C 낮다
DISPATCH_P = 0.5            # 출동 후보 문턱
LEVEL_RISK3 = 0.6
LEVEL_RISK2 = 0.3
BUDGET_DEFAULT = 2
BUDGET_MIN = 0
BUDGET_MAX = 4
WET_BONUS = 0.3             # 젖은 갈래는 우선순위를 0.3만큼 올린다
LOCAL_DT_MIN = -6.0         # 현장 보정 하한
LOCAL_DT_MAX = 3.0          # 현장 보정 상한

# 분류 경로에서 t_eff 차이만큼 옮기는 피처(기온·지면 시차 계열).
# air_gt_gap·dewpoint_depression은 두 항이 같이 움직여 차이가 그대로다.
TEMP_SHIFT_COLUMNS = (
    "temp", "temp_6h_mean", "dewpoint",
    "gt_lag1", "gt_lag2", "gt_lag3", "gt_lag6", "gt_roll6", "gt_min24",
)

NOTE_PROB = "결빙 확정이 아니라 예측 동결확률·상대 우선순위다."
NOTE_PATH = "동결확률은 시점별로 검증에서 고른 경로(회귀+isotonic / 직접 분류 / 평균)로 계산한다."
NOTE_LOCAL = "현장 센서 변화량 local_dt를 −6~+3°C로 잘라 유효온도에 더한다."
NOTE_TREATED = "처리된 갈래는 단계가 done이고 출동 후보에서 빠진다."
NOTE_NEAR = "수원 관측소(119)는 고색고에서 약 0.4km다."


# ---------------------------------------------------------------- 순수 함수

def clamp_budget(value):
    """예산을 0~4 정수로 맞춘다. None·변환 불가는 기본값 2."""
    if value is None or isinstance(value, bool):
        return BUDGET_DEFAULT
    try:
        n = int(value)
    except (TypeError, ValueError):
        return BUDGET_DEFAULT
    return max(BUDGET_MIN, min(BUDGET_MAX, n))


def clamp_local_dt(value):
    """local_dt를 [−6, +3]으로 자른다. 숫자가 아니면 0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(v):
        return 0.0
    return float(max(LOCAL_DT_MIN, min(LOCAL_DT_MAX, v)))


def level_of(p_max):
    """동결확률 최댓값 → 위험 단계."""
    p = float(p_max or 0.0)
    if p >= LEVEL_RISK3:
        return "risk3"
    if p >= LEVEL_RISK2:
        return "risk2"
    return "risk1"


def priority_of(risk, wet):
    """우선순위 = risk + 0.3×(젖음)."""
    return float(risk or 0.0) + (WET_BONUS if wet else 0.0)


def select_arms(priorities, candidates, budget=BUDGET_DEFAULT):
    """후보를 (−priority, N·E·S·W)로 정렬해 예산만큼 고른다. 순서 = 처리 순서."""
    limit = clamp_budget(budget)
    if limit <= 0:
        return []
    picked = [arm for arm in ARM_ORDER if candidates.get(arm)]
    picked.sort(key=lambda arm: (-float(priorities.get(arm, 0.0)), ARM_ORDER.index(arm)))
    return picked[:limit]


def apply_isotonic(value, xs, ys):
    """보정곡선 적용(out_of_bounds='clip'과 같은 선형보간·양끝 고정)."""
    if xs is None or len(xs) == 0:
        return 0.0
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(x):
        return 0.0
    return float(np.clip(np.interp(x, xs, ys), 0.0, 1.0))


def _num(value, digits=3, as_int=False):
    """JSON용 숫자. NaN·None은 None."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return int(round(v)) if as_int else round(v, digits)


# ---------------------------------------------------------------- 엔진

class Engine:
    """4갈래 예측 엔진. 갈래 정보는 cross_arms.json(roads.py 산출물)을 읽는다."""

    def __init__(self, stn="119", models_dir=None, arms_path=None):
        self.stn = str(stn)
        self.models_dir = Path(models_dir) if models_dir else MODELS_ROOT / self.stn
        self.arms_path = Path(arms_path) if arms_path else DEFAULT_ARMS
        self.arms = self._read_arms()

        self.reg = {}
        self.clf = {}
        self.calib = {}
        self.metrics = {}
        self.feature_list = []
        self.night_list = []
        self.default_night = None
        self.loaded_from = None

        self._frame = None
        self._pred_cache = {}
        self._prob_cache = {}
        self._loaded = False

    # ------------------------------------------------------------ 준비

    def _read_arms(self):
        if not self.arms_path.exists():
            raise FileNotFoundError(
                "갈래 파일이 없다: %s — python3 -m model.icezero.roads 를 먼저 실행한다"
                % self.arms_path
            )
        with open(self.arms_path, "r", encoding="utf-8") as fp:
            raw = json.load(fp)
        arms = raw.get("arms", raw)
        return {arm: dict(arms[arm]) for arm in ARM_ORDER if arm in arms}

    def required_files(self):
        names = ["reg_h%d.json" % h for h in HORIZONS]
        names += ["calib.json", "metrics.json", "nights.json", "features.json"]
        return [self.models_dir / name for name in names]

    def available(self):
        """지점 모델 파일이 모두 있는지."""
        return all(path.exists() for path in self.required_files())

    @property
    def frame(self):
        return self._ensure_frame()

    def _ensure_frame(self):
        if self._frame is None:
            try:
                raw = kma.load_station(self.stn)
            except kma.StationDataMissing:
                return None
            self._frame = features.build_features(raw)
        return self._frame

    def _curve(self, h):
        item = self.calib.get("h%d" % h, {})
        return (
            np.asarray(item.get("x", []), dtype="float64"),
            np.asarray(item.get("y", []), dtype="float64"),
        )

    @property
    def methods(self):
        return self.metrics.get("methods", {})

    def load(self):
        """저장된 지점 모델을 읽는다. 없으면 FileNotFoundError."""
        if not self.available():
            missing = [path.name for path in self.required_files() if not path.exists()]
            raise FileNotFoundError(
                "지점 %s 모델이 없다: %s (%s) — python3 -m model.icezero.train --stn %s"
                % (self.stn, self.models_dir, ", ".join(missing), self.stn)
            )
        from xgboost import XGBClassifier, XGBRegressor

        for h in HORIZONS:
            model = XGBRegressor()
            model.load_model(str(self.models_dir / ("reg_h%d.json" % h)))
            self.reg[h] = model
        for h in CLASS_HORIZONS:
            path = self.models_dir / ("clf_h%d.json" % h)
            if path.exists():
                model = XGBClassifier()
                model.load_model(str(path))
                self.clf[h] = model

        with open(self.models_dir / "calib.json", "r", encoding="utf-8") as fp:
            self.calib = json.load(fp).get("horizons", {})
        with open(self.models_dir / "metrics.json", "r", encoding="utf-8") as fp:
            self.metrics = json.load(fp)
        with open(self.models_dir / "features.json", "r", encoding="utf-8") as fp:
            self.feature_list = list(json.load(fp).get("features", []))
        with open(self.models_dir / "nights.json", "r", encoding="utf-8") as fp:
            nights = json.load(fp)
        self.night_list = nights.get("nights", [])
        self.default_night = nights.get("default") or (
            self.night_list[0]["night"] if self.night_list else None
        )

        self._ensure_frame()
        if not self.feature_list and self._frame is not None:
            self.feature_list = features.feature_columns(self._frame)
        self._pred_cache.clear()
        self._prob_cache.clear()
        self._loaded = True
        self.loaded_from = "saved"
        return self

    # ------------------------------------------------------------ 예측

    def _resolve(self, ts):
        """시각을 자료 격자(정시)에 맞춘다. 범위 밖은 양끝으로 붙인다."""
        frame = self._ensure_frame()
        if frame is None or len(frame) == 0:
            raise RuntimeError("지점 %s 관측 자료가 없어 예측할 수 없다" % self.stn)
        stamp = pd.Timestamp(pd.to_datetime(ts))
        if stamp.tzinfo is not None:
            stamp = stamp.tz_localize(None)
        stamp = stamp.floor("h")
        index = frame.index
        if stamp < index[0]:
            return index[0]
        if stamp > index[-1]:
            return index[-1]
        if stamp in index:
            return stamp
        pos = index.searchsorted(stamp)
        before, after = index[pos - 1], index[pos]
        return before if (stamp - before) <= (after - stamp) else after

    def _features_at(self, stamp):
        frame = self._ensure_frame()
        return frame.loc[[stamp], self.feature_list]

    def predict(self, ts):
        """h0·h1·h3·h6 지면온도 예측(°C)."""
        if not self.reg:
            raise RuntimeError("모델이 없다. Engine.load()를 먼저 부른다")
        stamp = self._resolve(ts)
        cached = self._pred_cache.get(stamp)
        if cached is not None:
            return cached
        x = self._features_at(stamp)
        out = {h: float(self.reg[h].predict(x)[0]) for h in HORIZONS}
        if len(self._pred_cache) > 4096:
            self._pred_cache.clear()
        self._pred_cache[stamp] = out
        return out

    def _prob(self, stamp, h, x, pred_h, t_eff):
        """갈래 유효온도의 동결확률(시점별 선택 방법)."""
        key = (stamp, h, round(float(t_eff), 2))
        cached = self._prob_cache.get(key)
        if cached is not None:
            return cached

        xs, ys = self._curve(h)
        p_reg = apply_isotonic(t_eff, xs, ys)
        method = self.methods.get("h%d" % h, "reg")
        if method == "reg" or h not in self.clf:
            value = p_reg
        else:
            delta = float(t_eff) - float(pred_h)
            shifted = x.copy()
            for col in TEMP_SHIFT_COLUMNS:
                if col in shifted.columns:
                    shifted[col] = shifted[col] + delta
            p_clf = float(self.clf[h].predict_proba(shifted)[0, 1])
            value = p_clf if method == "clf" else (p_reg + p_clf) / 2.0

        if len(self._prob_cache) > 8192:
            self._prob_cache.clear()
        self._prob_cache[key] = value
        return value

    # ------------------------------------------------------------ 현장·처리

    @staticmethod
    def _local_entry(local, arm):
        """(local_dt, wet). 빠진 갈래는 0, False."""
        if not local:
            return 0.0, False
        item = local.get(arm)
        if item is None:
            return 0.0, False
        if isinstance(item, dict):
            dt = item.get("dt", 0.0)
            wet = bool(item.get("wet", False))
        else:
            dt = item
            wet = False
        return clamp_local_dt(dt), wet

    @staticmethod
    def _is_treated(ts, treated, arm):
        """treated[arm] = 효과가 끝나는 시각. ts가 그보다 앞이면 처리됨."""
        if not treated:
            return False
        end = treated.get(arm)
        if not end:
            return False
        try:
            end_ts = pd.Timestamp(pd.to_datetime(end))
        except (TypeError, ValueError):
            return False
        if end_ts.tzinfo is not None:
            end_ts = end_ts.tz_localize(None)
        start = pd.Timestamp(pd.to_datetime(ts))
        if start.tzinfo is not None:
            start = start.tz_localize(None)
        return start < end_ts

    # ------------------------------------------------------------ step

    def step(self, ts, local=None, treated=None, budget=BUDGET_DEFAULT):
        """계약 3절의 step JSON. 값은 소수 3자리."""
        if not self._loaded:
            self.load()
        frame = self._ensure_frame()
        if frame is None:
            raise RuntimeError("지점 %s 관측 자료가 없어 step을 만들 수 없다" % self.stn)

        stamp = self._resolve(ts)
        pred = self.predict(stamp)
        row = frame.loc[stamp]
        x = self._features_at(stamp)
        limit = clamp_budget(budget)

        arms_out = {}
        priorities = {}
        candidates = {}
        local_used = False
        treated_used = False

        for arm in ARM_ORDER:
            meta = self.arms.get(arm, {})
            structure = int(meta.get("structure", 0) or 0)
            shadow = float(meta.get("shadow_index", 0.0) or 0.0)
            risk = float(meta.get("risk", meta.get("risk_v2", 0.0)) or 0.0)
            risk_pct = float(meta.get("risk_pct", meta.get("risk_v2_pct", 0.0)) or 0.0)

            local_dt, wet = self._local_entry(local, arm)
            is_treated = self._is_treated(ts, treated, arm)
            if local_dt != 0.0 or wet:
                local_used = True
            if is_treated:
                treated_used = True

            t_eff = {}
            p_freeze = {}
            for h in HORIZONS:
                key = "h%d" % h
                value = float(pred[h]) - BRIDGE_DELTA_C * structure + local_dt
                t_eff[key] = round(value, 3)
                p_freeze[key] = round(self._prob(stamp, h, x, pred[h], value), 3)

            best_h = max(CLASS_HORIZONS, key=lambda h: (p_freeze["h%d" % h], -h))
            p_max = p_freeze["h%d" % best_h]
            priority = round(priority_of(risk, wet), 3)
            candidate = bool((not is_treated) and p_max >= DISPATCH_P)

            reasons = []
            if structure:
                reasons.append("교량(%.1f°C 가정)" % BRIDGE_DELTA_C)
            if shadow >= 0.2:
                reasons.append("그늘 지수 %.2f" % shadow)
            if local_dt != 0.0:
                reasons.append("현장 %+.1f°C" % local_dt)
            if wet:
                reasons.append("젖음 감지")
            if p_max >= DISPATCH_P:
                reasons.append("예측 동결확률 %.2f(+%dh)" % (p_max, best_h))
            elif p_max > 0.0:
                reasons.append("예측 동결확률 %.2f(+%dh) 낮음" % (p_max, best_h))
            if is_treated:
                reasons.append("처리 완료(효과 지속)")
            if not reasons:
                reasons.append("특이 신호 없음")

            arms_out[arm] = {
                "name": meta.get("name", arm),
                "label": meta.get("label", "general"),
                "structure": structure,
                "shadow_index": round(shadow, 3),
                "risk": round(risk, 3),
                "risk_pct": round(risk_pct, 3),
                "local_dt": round(local_dt, 3),
                "wet": wet,
                "t_eff": t_eff,
                "p_freeze": p_freeze,
                "p_max": p_max,
                "source": "model+local" if (local_dt != 0.0 or wet) else "model",
                "level": "done" if is_treated else level_of(p_max),
                "candidate": candidate,
                "treated": is_treated,
                "priority": priority,
                "reasons": reasons,
            }
            priorities[arm] = priority
            candidates[arm] = candidate

        selected = select_arms(priorities, candidates, limit)

        notes = [NOTE_PROB, NOTE_PATH]
        if local_used:
            notes.append(NOTE_LOCAL)
        if treated_used:
            notes.append(NOTE_TREATED)
        if self.stn == "119":
            notes.append(NOTE_NEAR)
        if not self.arms:
            notes.append("갈래 파일에 N·E·S·W가 하나도 없다: %s" % self.arms_path)

        return {
            "time": stamp.isoformat(),
            "station": self.stn,
            "obs": {
                "temp": _num(row.get("temp"), 1),
                "humidity": _num(row.get("humidity"), 0, as_int=True),
                "wind": _num(row.get("wind"), 1),
                "precip": _num(row.get("precip"), 1),
                "snow": _num(row.get("snow"), 1),
                "ground_temp": _num(row.get("ground_temp"), 1),
            },
            "forecast": {"h%d" % h: round(float(pred[h]), 3) for h in HORIZONS},
            "arms": arms_out,
            "dispatch": {
                "recommend": bool(selected),
                "selected": list(selected),
                "order": list(selected),
                "budget": limit,
                "threshold": DISPATCH_P,
            },
            "model": {
                "name": self.metrics.get("model", MODEL_NAME),
                "station": self.stn,
                "method": {key: value for key, value in self.methods.items()},
                "rmse": self._metric("rmse"),
                "persistence_rmse": self._metric("persistence_rmse"),
                "brier": self._metric("brier"),
            },
            "notes": notes,
        }

    def _metric(self, key):
        horizons = self.metrics.get("horizons", {}) if self.metrics else {}
        out = {}
        for h in HORIZONS:
            item = horizons.get("h%d" % h) or {}
            out["h%d" % h] = item.get(key)
        return out

    # ------------------------------------------------------------ 밤

    def nights(self):
        """재생 후보 밤 목록(점수 내림차순)."""
        return [dict(item) for item in self.night_list]

    def timeline(self, night=None):
        """그 밤 18:00부터 다음 날 09:00까지 정시 ISO 목록(16개)."""
        key = str(night or self.default_night or "")
        if not key:
            raise ValueError("밤이 없다. nights.json을 먼저 만든다")
        start = pd.Timestamp(key[:10]) + pd.Timedelta(hours=18)
        return [(start + pd.Timedelta(hours=i)).isoformat() for i in range(16)]
