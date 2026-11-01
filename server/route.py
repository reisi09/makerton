"""사진에서 센 갈래별 눈 → 기지에서 출발해 눈 있는 갈래를 도는 가장 빠른 순서(최적 경로).

차가 실제로 도는 경로는 펌웨어(pico/car/car_core.py)의 plan_for_order 하나로만 만든다.
여기서는 그 함수로 가능한 순서를 모두(최대 4! = 24가지) 만들어 펌웨어 시간 모형(car_core.estimate_seconds)으로 가장 빠른 것을 고른다.
구간마다 정지에서 가감속하므로 시간은 스텝 수에 비례하지 않는다(전체 청소: 스텝이 가장 적은 E→S→W→N 141.7초, S→E→W→N 140.3초).
갈래 하나는 '중심에서 그 방위로 돌기 → 끝까지 밀기 → 같은 길 후진'이라, 순서가 바꾸는 것은 회전량이다.
시간이 같으면(1ms 이내) 눈이 많은 갈래를 먼저 간다.
"""

import importlib.util
import itertools
import os
import sys

CAR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pico", "car")
ARM_MIN_MM2 = 100      # 갈래 눈이 이 이상이면 치우러 간다
ARM_VAGUE_MM2 = 30     # 이 이상 ARM_MIN_MM2 미만은 눈인지 반사인지 애매하다 → 전체 청소(위에서 찍은 눈 없는 사진은 갈래당 14 이하)
REAL_FACTOR = 1.05     # 실기는 루프 지연으로 계산보다 느리다. 2026-11-01 N 드라이런이 계산 101.8초에 104.2초(스텝마다 약 0.03ms)라 0.6ms 간격에서 약 5%
PATH_POINTS = 240      # 화면 애니메이션용으로 남기는 자세 수
NAMES = {"C": "교차로", "N": "N 갈래", "E": "E 갈래", "S": "S 갈래", "W": "W 갈래"}
ALL = {a: {"area_mm2": ARM_MIN_MM2} for a in NAMES}    # 전체 청소: 네 갈래 모두


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(CAR_DIR, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_car_core():
    """펌웨어 car_core를 펌웨어 config로 읽는다. car_core가 import config를 하므로 잠깐 끼운다."""
    saved = sys.modules.get("config")
    sys.modules["config"] = _load("config")
    try:
        return _load("car_core")
    finally:
        if saved is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = saved


car_core = _load_car_core()


def seconds(order):
    return car_core.estimate_seconds(list(order)) * REAL_FACTOR


def path(order):
    """계획을 스텝 단위로 밀어 보며 자세 [x, y, 방위]를 고르게 남긴다(지도 애니메이션·경로 선)."""
    segs = car_core.plan_for_order(list(order))
    mission = car_core.Mission(segs, car_core.Pose())
    every = max(1, car_core.plan_steps(segs) // PATH_POINTS)
    out = [[round(mission.pose.x), round(mission.pose.y), round(mission.pose.h)]]
    n = 0
    while not mission.done:
        mission.step()
        n += 1
        if n % every == 0 or mission.done:
            p = mission.pose
            out.append([round(p.x), round(p.y), round(p.h)])
    return out


def plan(arms):
    """arms: {갈래: {"area_mm2": …}} (C·N·E·S·W). 치울 갈래가 없으면 None."""
    need = [a for a in "NESW" if arms[a]["area_mm2"] >= ARM_MIN_MM2]
    if not need and arms["C"]["area_mm2"] >= ARM_MIN_MM2:
        need = [min("NESW", key=lambda a: seconds([a]))]    # 교차로 눈만 있으면 가장 빨리 다녀오는 갈래로 밀어낸다
    if not need:
        return None
    ranked = sorted(itertools.permutations(need),
                    key=lambda o: (round(seconds(o), 3), [-arms[a]["area_mm2"] for a in o]))
    best, worst = ranked[0], ranked[-1]
    return {"order": list(best), "seconds": round(seconds(best)),
            "worst_order": list(worst), "worst_seconds": round(seconds(worst)),
            "tried": len(ranked), "path": path(best)}


def _doubt(arms, sure, eye):
    """판단이 애매한 이유(없으면 None). eye는 claude_vision.judge 결과 또는 None(꺼짐·실패)."""
    if not sure:
        return "사진이 비스듬하거나 노란 코트가 안 보여 판단이 애매함"
    vague = [a for a in NAMES if ARM_VAGUE_MM2 <= arms[a]["area_mm2"] < ARM_MIN_MM2]
    if vague:
        return "눈이 덮인 면적이 기준 근처여서 판단이 애매함(%s)" % ", ".join("%s %dmm²" % (NAMES[a], arms[a]["area_mm2"]) for a in vague)
    if eye is None:
        return None
    if not eye["usable"]:
        return "Claude가 사진으로는 판단하기 어렵다고 봄"
    rules = [a for a in NAMES if arms[a]["area_mm2"] >= ARM_MIN_MM2]
    claude = [a for a in NAMES if eye["arms"][a]]
    if rules != claude:
        return "Claude와 규칙의 판단이 엇갈림(눈 있는 곳: Claude %s, 규칙 %s)" % (
            "·".join(claude) or "없음", "·".join(rules) or "없음")
    return None


def decide(arms, sure=True, eye=None):
    """출동 여부와 화면·로그 문구. 판단이 애매하면(믿기 어려운 사진, 기준 근처의 눈, Claude와 규칙이 다름) 전체 청소로 다 치운다."""
    why = _doubt(arms, sure, eye)
    if why:
        p = plan(ALL)
        return {"go": True, "text": "%s → 전체 청소, 최적 순서 %s, 약 %d초" % (why, "→".join(p["order"]), p["seconds"]),
                "plan": p}
    same = "" if eye is None else " (Claude도 같은 판단)"
    p = plan(arms)
    if p is None:
        return {"go": False, "text": "도로에 치울 눈이 없음" + same, "plan": None}
    snowy = [a for a in "NESW" if arms[a]["area_mm2"] >= ARM_MIN_MM2]
    head = "%s 갈래에 눈" % "·".join(snowy) if snowy else "교차로에만 눈 → %s 갈래로 밀어냄" % p["order"][0]
    text = "%s → 최적 순서 %s, 약 %d초" % (head, "→".join(p["order"]), p["seconds"])
    if p["tried"] > 1:
        text += " (%d가지 순서 중 가장 빠름, 가장 느린 순서보다 %d초 빠름)" % (p["tried"], p["worst_seconds"] - p["seconds"])
    return {"go": True, "text": text + same, "plan": p}
