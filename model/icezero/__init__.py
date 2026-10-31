# -*- coding: utf-8 -*-
"""ICE-ZERO 고색 모델 패키지 (계약 3절).

    python3 -m model.icezero.train --stn 108      지점 학습·산출물·지표 표
    python3 -m model.icezero.train --stn 119      수원 원본이 있을 때
    from model.icezero import Engine              서버가 쓰는 예측 엔진

구성
- kma      : 정리본·포털 원본(cp949/utf-8-sig)을 표준 열로 읽는다
- features : ICE-ZERO v10 피처 + 개선 후보, 목표(ground_temp.shift(−h))
- train    : 방법 선택·rolling 검증·사건 지표·산출물 저장
- engine   : 갈래 유효온도·동결확률·위험 단계·출동 선정 → step JSON
"""

from . import features, kma
from .engine import (
    ARM_ORDER,
    BUDGET_DEFAULT,
    BRIDGE_DELTA_C,
    DISPATCH_P,
    HORIZONS,
    LEVEL_RISK2,
    LEVEL_RISK3,
    WET_BONUS,
    Engine,
    clamp_budget,
    clamp_local_dt,
    level_of,
    priority_of,
    select_arms,
)
from .features import (
    BASE_FEATURES,
    EXTRA_CANDIDATES,
    LAG_FEATURES,
    SOLAR_FEATURES,
    build_features,
    feature_columns,
    target_column,
)
from .kma import (
    STATION_NAMES,
    StationDataMissing,
    load_station,
    station_files,
)

__all__ = [
    "ARM_ORDER", "HORIZONS", "BASE_FEATURES", "LAG_FEATURES", "SOLAR_FEATURES",
    "EXTRA_CANDIDATES", "BRIDGE_DELTA_C", "DISPATCH_P", "LEVEL_RISK2", "LEVEL_RISK3",
    "BUDGET_DEFAULT", "WET_BONUS", "STATION_NAMES",
    "Engine", "StationDataMissing",
    "build_features", "feature_columns", "target_column", "load_station", "station_files",
    "clamp_budget", "clamp_local_dt", "level_of", "priority_of", "select_arms",
    "features", "kma",
]

__version__ = "1.0"
