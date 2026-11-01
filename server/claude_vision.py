"""패드 사진의 두 번째 의견: Claude(claude-opus-5-5)에게 사진을 보여 갈래별 눈 여부를 묻는다. 결합은 route.decide.

키는 ANTHROPIC_API_KEY 환경변수로만 받는다(파일에 두지 않는다). 키가 없으면 서버는 규칙(vision.py)만 쓴다.
공식 SDK는 Python 3.10 이상이라 서버를 돌리는 시스템 python3(3.9)에서 못 쓰므로 표준 라이브러리로 스트리밍을 받는다.
사고 요약을 받는 대로 on_thinking으로 넘겨 조작 화면에 실시간으로 띄운다. 요약은 한국어로 하라고 해도 영어로 오고,
짧게 생각한 사진은 비어 있다(서버 경로 42장 중 5장). 화면에 올리는 한국어 문장은 note다.
2026-11-01 모형 사진 42장 시험(규칙과 같은 1200px, effort medium): 눈 사진 19장을 원본·25% 어둡게·노란 조명·흐리게
모두에서 놓치지 않았다(규칙은 같은 조건에서 최대 3장 놓침). 장당 평균 6.5초, 약 2센트. 갈래별 정답은 아직 없다.
"""

import base64
import io
import json
import os
import time
import urllib.error
import urllib.request

import numpy as np
from PIL import Image

URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-5-5"
TIMEOUT_S = 60
ARMS = ("C", "N", "E", "S", "W")

SYSTEM = """You judge photos of a tabletop model city used in a snow-removal robot demo.

The board is about 925 x 910 mm. Black roads 135 mm wide form one plus-shaped intersection. The roads have yellow dashed centerlines and the intersection square has a yellow outline. Clear tape covers the paint.

Snow is small white styrofoam beads, a few millimetres across, lying on the black road surface. Count it even when there are only a few beads.
Not snow: bright glare streaks from the tape over the yellow paint (thin, long, along a centerline or the intersection outline), white buildings and roofs, signs, the floor or table outside the board, and anything off the black road.

Road parts: orient the board so the yellow sports court (yellow rectangle with two small goals) is at the lower left of the intersection. The photo is usually already turned this way. Then N is the road going up from the intersection, toward the park and the four towers with blue windows. S goes down, E goes right, W goes left, and C is the intersection square itself.

usable is false when the photo does not show the roads clearly enough to judge (not the board, roads cut off, very oblique, too blurry or dark). When usable is false, still give your best guess for each part.
Think in Korean. note: one or two short Korean sentences on what you saw, for display to the operator."""

SCHEMA = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "arms": {"type": "object", "properties": {a: {"type": "boolean"} for a in ARMS},
                 "required": list(ARMS), "additionalProperties": False},
        "note": {"type": "string"},
    },
    "required": ["usable", "arms", "note"],
    "additionalProperties": False,
}


def enabled():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _jpeg_b64(img, turns):
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(np.rot90(img, turns))).save(buf, "JPEG", quality=90)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _request(img, turns):
    body = {
        "model": MODEL, "max_tokens": 16000, "stream": True, "system": SYSTEM,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        "fallbacks": "default",
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _jpeg_b64(img, turns)}},
            {"type": "text", "text": "어느 도로에 눈이 있나요? 생각은 한국어로 해 주세요."}]}],
    }
    return urllib.request.Request(URL, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "content-type": "application/json",
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2026-10-21",
        "anthropic-beta": "server-side-fallback-2026-07-01",
    })


def read_stream(lines, on_thinking):
    """SSE 줄들 → (사고 요약, 본문, stop_reason). 사고 요약은 늘어날 때마다 on_thinking(지금까지 전체)."""
    thinking, text, stop = "", "", None
    for raw in lines:
        line = raw.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        ev = json.loads(line[5:])
        if ev["type"] == "content_block_delta":
            d = ev["delta"]
            if d["type"] == "thinking_delta":
                thinking += d["thinking"]
                on_thinking(thinking)
            elif d["type"] == "text_delta":
                text += d["text"]
        elif ev["type"] == "message_delta":
            stop = ev["delta"].get("stop_reason") or stop
        elif ev["type"] == "error":
            raise RuntimeError(ev["error"].get("message", "스트림 오류"))
    return thinking, text, stop


def judge(img, turns=0, on_thinking=lambda text: None):
    """RGB 배열과 vision.analyze의 turns → {"usable", "arms": {갈래: 눈 있음}, "note", "thinking", "secs"}. 실패하면 예외."""
    t0 = time.time()
    try:
        with urllib.request.urlopen(_request(img, turns), timeout=TIMEOUT_S) as resp:
            thinking, text, stop = read_stream(resp, on_thinking)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read())["error"]["message"]
        except Exception:
            msg = e.reason
        raise RuntimeError("HTTP %d %s" % (e.code, msg))
    if stop != "end_turn":
        raise RuntimeError("응답이 끝나지 않음(%s)" % stop)
    out = json.loads(text)
    return dict(out, thinking=thinking, secs=round(time.time() - t0, 1))
