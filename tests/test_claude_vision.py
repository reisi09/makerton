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

    def test_enabled_only_with_a_key(self):
        self.assertTrue(claude_vision.enabled())
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertFalse(claude_vision.enabled())


if __name__ == "__main__":
    unittest.main()
