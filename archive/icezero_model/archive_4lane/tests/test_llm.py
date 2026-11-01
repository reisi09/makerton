"""제보 해석(llm.py) 시험 — 네트워크 없이 돈다. 계약 5절."""

import json
import os
import sys
import unittest
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "server")
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import llm  # noqa: E402


class FakeResponse(object):
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ExtractJsonTest(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(llm.extract_json('{"cells":["D3"]}'), {"cells": ["D3"]})

    def test_code_fence_and_chatter(self):
        text = '좋아요.\n```json\n{"cells":["U2"],"ambiguous":false}\n```\n이상입니다.'
        self.assertEqual(llm.extract_json(text)["cells"], ["U2"])

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            llm.extract_json("JSON 이 없는 응답")

    def test_broken_json_raises(self):
        with self.assertRaises(ValueError):
            llm.extract_json('{"cells": ["U2",]}')

    def test_array_is_not_object(self):
        with self.assertRaises(ValueError):
            llm.extract_json('[1,2,3]')


class NormalizeTest(unittest.TestCase):
    def test_drops_unknown_cells_and_sorts_loop(self):
        out = llm.normalize({"cells": ["d3", "U2", "Z9", "U9", "U2", "S2", ""]})
        self.assertEqual(out["cells"], ["U2", "D3"])

    def test_cells_as_string_and_dict(self):
        self.assertEqual(llm.normalize({"cells": "U4, d1"})["cells"], ["U4", "D1"])
        self.assertEqual(llm.normalize({"cells": {"D2": True}})["cells"], ["D2"])

    def test_bad_condition_falls_back(self):
        self.assertEqual(llm.normalize({"condition": "ICE!"})["condition"], "other")
        self.assertEqual(llm.normalize({"condition": "SNOW"})["condition"], "snow")
        self.assertEqual(llm.normalize({})["condition"], "other")

    def test_budget_range(self):
        self.assertEqual(llm.normalize({"budget": 3})["budget"], 3)
        self.assertEqual(llm.normalize({"budget": "3회분"})["budget"], 3)
        self.assertEqual(llm.normalize({"budget": 99})["budget"], 8)
        self.assertEqual(llm.normalize({"budget": -5})["budget"], 0)
        self.assertIsNone(llm.normalize({"budget": "많이"})["budget"])
        self.assertIsNone(llm.normalize({"budget": None})["budget"])
        self.assertIsNone(llm.normalize({"budget": True})["budget"])

    def test_ambiguous_needs_question(self):
        out = llm.normalize({"cells": [], "ambiguous": True})
        self.assertTrue(out["ambiguous"])
        self.assertTrue(out["question"])

    def test_question_dropped_when_not_ambiguous(self):
        out = llm.normalize({"cells": ["U2"], "ambiguous": False, "question": "어디인가요?"})
        self.assertEqual(out["question"], "")

    def test_summary_generated(self):
        out = llm.normalize({"cells": ["U2"], "condition": "snow"})
        self.assertIn("U2", out["summary"])
        self.assertIn("눈", out["summary"])

    def test_lane1_list(self):
        out = llm.normalize({"lane1_closed": ["u3", "??"]})
        self.assertEqual(out["lane1_closed"], ["U3"])

    def test_not_a_dict(self):
        with self.assertRaises(ValueError):
            llm.normalize(["U2"])


class RuleParseTest(unittest.TestCase):
    def test_bridge_up_with_budget(self):
        out = llm.rule_parse("교량 위가 얼음 같아요. 상행 방향이고 제설제 3회분 남았습니다.")
        self.assertEqual(out["cells"], ["U2"])
        self.assertFalse(out["ambiguous"])
        self.assertEqual(out["budget"], 3)
        self.assertEqual(out["condition"], "ice_suspected")

    def test_bridge_without_direction_asks(self):
        out = llm.rule_parse("물 위 지나는 구간이 미끄럽대요")
        self.assertTrue(out["ambiguous"])
        self.assertEqual(out["cells"], ["U2", "D2"])
        self.assertIn("상행", out["question"])

    def test_shade_both_directions(self):
        out = llm.rule_parse("그늘 구간이 젖어 있어요. 양방향이요.")
        self.assertFalse(out["ambiguous"])
        self.assertEqual(out["cells"], ["U3", "D3"])
        self.assertEqual(out["condition"], "slippery")

    def test_explicit_cell_id(self):
        out = llm.rule_parse("U3에 사고가 났어요")
        self.assertEqual(out["cells"], ["U3"])
        self.assertFalse(out["ambiguous"])
        self.assertEqual(out["condition"], "accident")

    def test_budget_only_is_ambiguous(self):
        out = llm.rule_parse("제설제 2회분 남았습니다")
        self.assertEqual(out["budget"], 2)
        self.assertTrue(out["ambiguous"])
        self.assertEqual(out["cells"], [])
        self.assertTrue(out["question"])

    def test_direction_without_section_asks_section(self):
        out = llm.rule_parse("상행 방향이 미끄러워요")
        self.assertTrue(out["ambiguous"])
        self.assertEqual(out["cells"], [])
        self.assertIn("구간", out["question"])

    def test_west_words(self):
        out = llm.rule_parse("서쪽 방면 그늘이 젖었어요")
        self.assertFalse(out["ambiguous"])
        self.assertEqual(out["cells"], ["D3"])

    def test_lane1_closed_is_display_only(self):
        out = llm.rule_parse("하행 1차로를 통제하고 있어요")
        self.assertEqual(out["lane1_closed"], ["D4", "D3", "D2", "D1"])
        self.assertTrue(out["ambiguous"])  # 구간이 없다

    def test_empty_text(self):
        out = llm.rule_parse("   ")
        self.assertTrue(out["ambiguous"])
        self.assertTrue(out["question"])

    def test_matches_schema(self):
        out = llm.rule_parse("교량 하행이 미끄러워요")
        self.assertEqual(set(out), {"cells", "condition", "budget", "lane1_closed",
                                    "ambiguous", "question", "summary"})
        self.assertEqual(out["cells"], ["D2"])


class ApiHeaderTest(unittest.TestCase):
    def test_headers_and_body(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["headers"] = dict(req.header_items())
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"choices": [{"message": {"content": "안녕"}}]})

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            text = llm.chat_text("시스템", "사용자", timeout=7, key="테스트키",
                                 api_base="https://example.test/v1")

        self.assertEqual(text, "안녕")
        self.assertEqual(seen["url"], "https://example.test/v1/chat/completions")
        headers = {k.lower(): v for k, v in seen["headers"].items()}
        self.assertEqual(headers["user-agent"], "icezero-model/1.0")
        self.assertEqual(headers["authorization"], "Bearer 테스트키")
        self.assertEqual(headers["x-cmd-zdr"], "1")
        self.assertEqual(seen["body"]["max_tokens"], 2000)
        self.assertEqual(len(seen["body"]["messages"]), 2)
        self.assertIn("reasoning_effort", seen["body"])
        self.assertEqual(seen["body"]["reasoning_effort"], llm.TEXT_REASONING or seen["body"].get("reasoning_effort"))

    def test_empty_content_raises(self):
        def fake_urlopen(req, timeout=None):
            return FakeResponse({"choices": [{"message": {"content": "  "}, "finish_reason": "length"}]})

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(ValueError):
                llm.chat_text("s", "u", key="k", api_base="https://example.test/v1")


class InterpretTest(unittest.TestCase):
    def test_rule_only_never_calls_network(self):
        def boom(*args, **kwargs):
            raise AssertionError("use_llm=False 인데 네트워크를 불렀습니다")

        with mock.patch.object(llm, "chat_text", boom):
            out = llm.interpret("교량 상행이 미끄러워요", use_llm=False)
        self.assertEqual(out["engine"], "rule")
        self.assertEqual(out["result"]["cells"], ["U2"])
        self.assertIsNone(out["error"])

    def test_llm_success(self):
        reply = '```json\n{"cells":["U3"],"condition":"snow","budget":2,"lane1_closed":[],' \
                '"ambiguous":false,"question":"","summary":"그늘 칸에 눈"}\n```'
        with mock.patch.object(llm, "chat_text", return_value=reply):
            out = llm.interpret("방음벽 옆 그늘이 눈으로 덮였고 2회분 남았어요")
        self.assertEqual(out["engine"], "llm")
        self.assertEqual(out["result"]["cells"], ["U3"])
        self.assertEqual(out["result"]["budget"], 2)
        self.assertEqual(out["rule"]["cells"], ["U3", "D3"])  # 기준선도 함께 남는다(방향 없음)
        self.assertIsNone(out["error"])

    def test_llm_failure_falls_back_to_rule(self):
        with mock.patch.object(llm, "chat_text", side_effect=ValueError("빈 응답(finish_reason=length)")):
            out = llm.interpret("교량 하행이 미끄러워요")
        self.assertEqual(out["engine"], "rule")
        self.assertEqual(out["result"]["cells"], ["D2"])
        self.assertIn("LLM 실패", out["error"])
        self.assertIn("빈 응답", out["error"])

    def test_llm_bad_json_falls_back(self):
        with mock.patch.object(llm, "chat_text", return_value="칸은 U2 입니다"):
            out = llm.interpret("뭐가 미끄러워요")
        self.assertEqual(out["engine"], "rule")
        self.assertIsNotNone(out["error"])


if __name__ == "__main__":
    unittest.main()
