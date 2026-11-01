#!/usr/bin/env python3
"""갈래별 눈 여부 → 최적 경로 표(web/lib/routeTable.json). 조작 화면이 서버 없이도 AI가 찾은 눈에 맞는 경로를 그린다.

키는 눈이 있는 갈래를 N·E·S·W 순서로 이은 문자열("NS" 등)이고, 교차로에만 눈이 있으면 "C"다.
값은 server/route.py plan()과 같다(펌웨어 경로 계획, 가감속 시간). 경로나 기구 상수를 바꾸면 다시 만든다:
    python3 tools/make_route_table.py
"""

import itertools
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server import route  # noqa: E402

OUT = os.path.join(ROOT, "web", "lib", "routeTable.json")


def keys():
    for n in range(1, 5):
        for arms in itertools.combinations("NESW", n):
            yield "".join(arms)
    yield "C"


def entry(key):
    arms = {a: {"area_mm2": route.ARM_MIN_MM2 if a in key else 0} for a in route.NAMES}
    p = route.plan(arms)
    return {"order": p["order"], "seconds": p["seconds"], "tried": p["tried"],
            "worst_seconds": p["worst_seconds"], "path": p["path"]}


def table():
    return {k: entry(k) for k in keys()}


if __name__ == "__main__":
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(table(), f, separators=(",", ":"))
    print("wrote", OUT, os.path.getsize(OUT), "bytes")
