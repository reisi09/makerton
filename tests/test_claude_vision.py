# -*- coding: utf-8 -*-
"""server/claude_vision.py 시험: 네트워크 없이 Anthropic 스트림(SSE)을 흉내 내 판정과 사고 요약 전달을 본다."""
import base64
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server import claude_vision  # noqa: E402

VERDICT = {"usable": True, "arms": {"C": False, "N": True, "E": False, "S": False, "W": False}, "note": "N 도로에 눈"}


def sse(*events):
    return [("data: %s\n" % json.dumps(e)).encode("utf-8") for e in events]


def stream(stop="end_turn"):
    text = json.dumps(VERDICT, ensure_ascii=False)
    return sse({"type": "message_start", "message": {"model": claude_vision.MODEL}},
               {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "코트가 왼쪽 아래. "}},
               {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "N에 흰 알갱이."}},
               {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": text[:10]}},
               {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": text[10:]}},
               {"type": "message_delta", "delta": {"stop_reason": stop}},
               {"type": "message_stop"})


class FakeResponse(list):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ClaudeVisionTest(unittest.TestCase):
    def setUp(self):
        self.img = np.zeros((90, 120, 3), np.uint8)
        self.env = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_streams_thinking_as_it_grows_and_returns_the_verdict(self):
        seen, sent = [], []
        def urlopen(req, timeout):
            sent.append(req)
            return FakeResponse(stream())
        with mock.patch.object(claude_vision.urllib.request, "urlopen", urlopen):
            out = claude_vision.judge(self.img, 1, seen.append)
        self.assertEqual(seen, ["코트가 왼쪽 아래. ", "코트가 왼쪽 아래. N에 흰 알갱이."])
        self.assertEqual(out["arms"], VERDICT["arms"])
        self.assertEqual(out["thinking"], seen[-1])
        req = sent[0]
        self.assertEqual(req.get_header("X-api-key"), "test-key")    # 키는 환경변수에서만
        body = json.loads(req.data)
        self.assertTrue(body["stream"])
        image = body["messages"][0]["content"][0]["source"]["data"]
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(image))).size, (90, 120), "turns만큼 돌려서 보낸다")

    def test_unfinished_answer_or_http_error_raises(self):
        with mock.patch.object(claude_vision.urllib.request, "urlopen", lambda req, timeout: FakeResponse(stream("max_tokens"))):
            with self.assertRaises(RuntimeError):
                claude_vision.judge(self.img)
        def refuse(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {},
                                         io.BytesIO(b'{"error": {"message": "invalid x-api-key"}}'))
        with mock.patch.object(claude_vision.urllib.request, "urlopen", refuse):
            with self.assertRaisesRegex(RuntimeError, "401 invalid x-api-key"):
                claude_vision.judge(self.img)

    def boxes_stream(self, boxes, note="N 도로에 눈", stop="end_turn"):
        text = json.dumps({"boxes": boxes, "note": note}, ensure_ascii=False)
        return FakeResponse(sse({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "도로 위 알갱이."}},
                                {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": text[:20]}},
                                {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": text[20:]}},
                                {"type": "message_delta", "delta": {"stop_reason": stop}}))

    def test_boxes_sends_the_unrotated_photo_and_returns_clamped_ordered_fractions(self):
        sent, seen = [], []
        raw = [{"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4},          # 정상
               {"x0": 0.6, "y0": 0.5, "x1": 0.2, "y1": -0.1},         # 뒤집힘 + 위로 벗어남
               {"x0": -0.5, "y0": 0.9, "x1": 1.7, "y1": 1.2}]         # 양쪽으로 벗어남
        def urlopen(req, timeout):
            sent.append(req)
            return self.boxes_stream(raw)
        with mock.patch.object(claude_vision.urllib.request, "urlopen", urlopen):
            out = claude_vision.boxes(self.img, seen.append)
        self.assertEqual(out["boxes"], [{"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4},
                                        {"x0": 0.2, "y0": 0.0, "x1": 0.6, "y1": 0.5},
                                        {"x0": 0.0, "y0": 0.9, "x1": 1.0, "y1": 1.0}])
        self.assertEqual(out["note"], "N 도로에 눈")
        self.assertEqual((out["thinking"], seen), ("도로 위 알갱이.", ["도로 위 알갱이."]))
        self.assertIsInstance(out["secs"], float)
        body = json.loads(sent[0].data)
        self.assertEqual(sent[0].get_header("X-api-key"), "test-key")
        self.assertTrue(body["stream"])
        schema = body["output_config"]["format"]["schema"]
        self.assertEqual(schema["required"], ["boxes", "note"])
        image = body["messages"][0]["content"][0]["source"]["data"]
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(image))).size, (120, 90), "사진을 돌리지 않고 원본 방향으로 보낸다")

    def test_boxes_may_be_empty_and_are_capped(self):
        with mock.patch.object(claude_vision.urllib.request, "urlopen", lambda req, timeout: self.boxes_stream([], "눈 없음")):
            out = claude_vision.boxes(self.img)
        self.assertEqual((out["boxes"], out["note"]), ([], "눈 없음"))
        many = [{"x0": i / 100.0, "y0": 0.0, "x1": i / 100.0 + 0.01, "y1": 0.1} for i in range(40)]
        with mock.patch.object(claude_vision.urllib.request, "urlopen", lambda req, timeout: self.boxes_stream(many)):
            out = claude_vision.boxes(self.img)
        self.assertEqual(len(out["boxes"]), 30)

    def test_boxes_unfinished_answer_or_http_error_raises(self):
        with mock.patch.object(claude_vision.urllib.request, "urlopen", lambda req, timeout: self.boxes_stream([], stop="max_tokens")):
            with self.assertRaises(RuntimeError):
                claude_vision.boxes(self.img)
        def refuse(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 529, "Overloaded", {}, io.BytesIO(b'{"error": {"message": "overloaded"}}'))
        with mock.patch.object(claude_vision.urllib.request, "urlopen", refuse):
            with self.assertRaisesRegex(RuntimeError, "529 overloaded"):
                claude_vision.boxes(self.img)

    def test_enabled_only_with_a_key(self):
        self.assertTrue(claude_vision.enabled())
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertFalse(claude_vision.enabled())


if __name__ == "__main__":
    unittest.main()
