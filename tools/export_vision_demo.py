#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""웹 데모(GitHub Pages)용 사진 인식·최적 경로 자료를 만든다. 서버와 같은 코드(server/vision.py, server/route.py)를 쓴다.

    python3 tools/export_vision_demo.py   → web/public/demo/vision.json, web/public/demo/overlay/*.jpg

입력은 web/public/demo/photos/*.jpg(팀이 찍은 모형 사진, 긴 변 1000px)다.
"""
import base64
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import route, vision  # noqa: E402

DEMO = ROOT / "web" / "public" / "demo"


def main():
    board = json.loads((ROOT / "server" / "board.json").read_text(encoding="utf-8"))
    (DEMO / "overlay").mkdir(exist_ok=True)
    samples = []
    for photo in sorted((DEMO / "photos").glob("*.jpg")):
        found = vision.analyze(np.asarray(Image.open(photo).convert("RGB")), float(board["ROAD_MM"]))
        if found is None:
            print("도로를 못 찾아 건너뜀:", photo.name)
            continue
        decision = route.decide(found["arms"])
        plan = decision.pop("plan")
        (DEMO / "overlay" / photo.name).write_bytes(base64.b64decode(found["view"].split(",", 1)[1]))
        samples.append({"id": photo.stem, "photo": "photos/" + photo.name, "overlay": "overlay/" + photo.name,
                        "arms": found["arms"], "decision": decision, "route": plan})
        print("%s  %s" % (photo.stem, decision["text"]))
    out = {"min_mm2": route.ARM_MIN_MM2, "base": board["BASE_XY"], "samples": samples}
    (DEMO / "vision.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
