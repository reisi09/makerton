"""사진에서 센 갈래별 눈 → 기지에서 출발해 눈 있는 갈래를 도는 가장 빠른 순서(최적 경로).

차가 실제로 도는 경로는 펌웨어(pico/car/car_core.py)의 plan_for_order 하나로만 만든다.
여기서는 그 함수로 가능한 순서를 모두(최대 4! = 24가지) 만들어 스텝 수(= 시간)가 가장 적은 것을 고른다.
갈래 하나는 '중심에서 그 방위로 돌기 → 끝까지 밀기 → 같은 길 후진'이라, 순서가 바꾸는 것은 회전량이다.
시간이 같으면 눈이 많은 갈래를 먼저 간다.
"""

import importlib.util
import itertools
import os
import sys

CAR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pico", "car")
ARM_MIN_MM2 = 100      # 갈래 눈이 이보다 크면 치우러 간다(위에서 찍은 눈 없는 사진은 갈래당 30 이하였다)
REAL_FACTOR = 1.14     # 실기는 루프 지연으로 계산보다 느리다(2026-10-31 모터 시험 스텝 1.37ms / 설정 1.2ms)
PATH_POINTS = 240      # 화면 애니메이션용으로 남기는 자세 수


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


def steps(order):
    return car_core.plan_steps(car_core.plan_for_order(list(order)))


def seconds(n_steps):
    return n_steps * car_core.config.STEP_US / 1000000.0 * REAL_FACTOR


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
        need = [min("NESW", key=lambda a: steps([a]))]      # 교차로 눈만 있으면 가장 짧은 갈래로 밀어낸다
    if not need:
        return None
    ranked = sorted(itertools.permutations(need),
                    key=lambda o: (steps(o), [-arms[a]["area_mm2"] for a in o]))
    best, worst = ranked[0], ranked[-1]
    return {"order": list(best), "seconds": round(seconds(steps(best))),
            "worst_order": list(worst), "worst_seconds": round(seconds(steps(worst))),
            "tried": len(ranked), "path": path(best)}


def decide(arms):
    """출동 여부와 화면·로그 문구. plan이 None이면 출동하지 않는다."""
    p = plan(arms)
    if p is None:
        return {"go": False, "text": "도로에 치울 눈이 없음", "plan": None}
    snowy = [a for a in "NESW" if arms[a]["area_mm2"] >= ARM_MIN_MM2]
    head = "%s 갈래에 눈" % "·".join(snowy) if snowy else "교차로에만 눈 → %s 갈래로 밀어냄" % p["order"][0]
    text = "%s → 최적 순서 %s, 약 %d초" % (head, "→".join(p["order"]), p["seconds"])
    if p["tried"] > 1:
        text += " (%d가지 순서 중 가장 빠름, 가장 느린 순서보다 %d초 빠름)" % (p["tried"], p["worst_seconds"] - p["seconds"])
    return {"go": True, "text": text, "plan": p}
