"""ICE-ZERO-lite 계획 계산 (순수 함수).

계약 4절을 그대로 옮긴다. 파일·네트워크·시계·하드웨어에 의존하지 않으므로
CPython 시험에서 그대로 돌려 볼 수 있다.

    점수 = 3.0×확인된 제보 + 2.0×관측 주의(교량 칸) + 1.5×구조물(교량) + 1.0×그늘
    이번 밤 이미 살포한 칸은 0점. 단 살포 뒤 새로 확인된 제보가 있으면 다시 점수를 받는다.
    후보 = 점수 > 0. 정렬 기준 (-점수, 루프 순서). 앞에서 budget개를 고르고 실행 순서는 루프 순서.
"""

import os

# 주행(루프) 순서. 계획의 실행 순서와 보드 LED 체인 순서가 모두 이 순서를 따른다.
LOOP = ["U1", "U2", "U3", "U4", "D4", "D3", "D2", "D1"]
CELLS = tuple(LOOP)

# 구간별 칸. S1 일반(서쪽) / S2 교량 / S3 그늘 / S4 일반(동쪽)
SECTION_OF = {"U1": "S1", "U2": "S2", "U3": "S3", "U4": "S4",
              "D1": "S1", "D2": "S2", "D3": "S3", "D4": "S4"}
SECTION_NAMES = {"S1": "일반(서쪽)", "S2": "교량", "S3": "그늘", "S4": "일반(동쪽)"}
BRIDGE = ("U2", "D2")
SHADE = ("U3", "D3")

# 점수 가중치 (계약 4절)
W_REPORT = 3.0
W_WATCH = 2.0
W_STRUCT = 1.5
W_SHADE = 1.0

BUDGET_MIN = 0
BUDGET_MAX = 8
BUDGET_FALLBACK = 4

REASON_REPORT = "확인된 제보"
REASON_WATCH = "관측 주의"
REASON_STRUCT = "구조물(교량)"
REASON_SHADE = "그늘"
REASON_SALTED = "이미 살포"


def default_budget():
    """환경변수 BUDGET_DEFAULT(기본 4). 값이 이상하면 4로 돌아간다."""
    raw = os.environ.get("BUDGET_DEFAULT", "")
    try:
        return clamp_budget(int(str(raw).strip()))
    except (TypeError, ValueError):
        return BUDGET_FALLBACK


def clamp_budget(value):
    """예산을 0~8 정수로 맞춘다. None·변환 불가는 기본값."""
    if value is None or isinstance(value, bool):
        return default_budget()
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default_budget()
    if n < BUDGET_MIN:
        return BUDGET_MIN
    if n > BUDGET_MAX:
        return BUDGET_MAX
    return n


def risk_bucket(score):
    """점수 → 위험 단계. 0=risk1(초록), 0< 2.5 미만=risk2(노랑), 2.5 이상=risk3(빨강)."""
    s = float(score or 0.0)
    if s <= 0:
        return "risk1"
    if s < 2.5:
        return "risk2"
    return "risk3"


def _as_cells(values):
    """칸 목록을 루프 순서로 정리한다(중복 제거, 8칸 밖은 버린다)."""
    if not values:
        return []
    if isinstance(values, str):
        values = values.replace(",", " ").split()
    seen = set()
    for v in values:
        if isinstance(v, str):
            c = v.strip().upper()
            if c in CELLS:
                seen.add(c)
    return [c for c in LOOP if c in seen]


def cells_of(values):
    """칸 목록을 루프 순서로 정리한다(중복 제거, 8칸 밖은 버린다)."""
    return _as_cells(values)


def salted_cells(reports, salt_times):
    """아직 0점으로 둘 살포 칸. 살포 뒤 새 확인 제보가 있는 칸은 빠진다.

    reports: [{"cells": [...], "at": epoch}, ...] 확인된 제보 이력
    salt_times: {칸: epoch} 마지막 살포 시각
    """
    salted = set()
    for cell, at in (salt_times or {}).items():
        if cell not in CELLS:
            continue
        renewed = False
        for r in reports or ():
            if float(r.get("at") or 0.0) > float(at) and cell in (r.get("cells") or ()):
                renewed = True
                break
        if not renewed:
            salted.add(cell)
    return salted


def plan_rows(confirmed=(), bridge_warn=False, manual_watch=None, salted=()):
    """칸별 점수·이유·위험 단계.

    confirmed: 확인된 제보가 있는 칸 목록
    bridge_warn: 보드 텔레메트리의 warn (교량 칸에만 적용)
    manual_watch: True=수동 관측 주의 켬, False=끔, None=보드 값을 따른다
    salted: 0점으로 둘 살포 칸 목록(salted_cells 결과)
    """
    confirmed_set = set(_as_cells(confirmed))
    salted_set = set(_as_cells(salted))
    watch = bool(bridge_warn) if manual_watch is None else bool(manual_watch)

    rows = {}
    for cell in LOOP:
        score = 0.0
        reasons = []
        if cell in confirmed_set:
            score += W_REPORT
            reasons.append(REASON_REPORT)
        if cell in BRIDGE:
            score += W_STRUCT
            reasons.append(REASON_STRUCT)
            if watch:
                score += W_WATCH
                reasons.append(REASON_WATCH)
        if cell in SHADE:
            score += W_SHADE
            reasons.append(REASON_SHADE)
        is_salted = cell in salted_set
        if is_salted:
            # 이미 뿌린 칸은 이번 밤 후보에서 뺀다. 화면에는 살포 사실만 남긴다.
            score = 0.0
            reasons = [REASON_SALTED]
        score = round(score, 2)
        rows[cell] = {"score": score, "reasons": reasons, "risk": risk_bucket(score), "salted": is_salted}
    return rows


def propose(rows, budget=None):
    """점수표에서 예산 안의 칸을 고른다. cells 와 order 는 같은 목록(루프 순서)이다."""
    budget = clamp_budget(budget)
    candidates = [c for c in LOOP if rows.get(c, {}).get("score", 0.0) > 0]
    # 1) (-점수, 루프 순서)로 줄 세워 앞에서 budget개를 고른다
    ranked = sorted(candidates, key=lambda c: (-rows[c]["score"], LOOP.index(c)))
    picked = set(ranked[:budget])
    # 2) 실행 순서는 루프 순서로 다시 정렬한다
    order = [c for c in LOOP if c in picked]
    return {
        "cells": order,
        "order": list(order),
        "budget": budget,
        "scores": {c: rows[c]["score"] for c in LOOP},
        "reasons": {c: list(rows[c]["reasons"]) for c in LOOP},
        "risk": {c: rows[c]["risk"] for c in LOOP},
    }


def make_plan(confirmed=(), bridge_warn=False, manual_watch=None, salted=(), budget=None):
    """plan_rows + propose 를 한 번에. 서버가 쓰는 편의 함수."""
    rows = plan_rows(confirmed=confirmed, bridge_warn=bridge_warn,
                     manual_watch=manual_watch, salted=salted)
    return propose(rows, budget)


def confirmed_cells(reports):
    """확인된 제보 이력에서 칸 목록을 뽑는다(루프 순서)."""
    cells = []
    for r in reports or ():
        cells.extend(r.get("cells") or ())
    return _as_cells(cells)
