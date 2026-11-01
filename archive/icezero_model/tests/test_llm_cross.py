"""제보 해석(llm.py 4갈래판) 시험 — 네트워크 없이 돈다. 계약 4절."""

import json
import os
import sys
import unittest
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
        self.assertEqual(llm.extract_json('{"arms":["E"]}'), {"arms": ["E"]})

    def test_surrounded_by_chatter_and_code_fence(self):
        text = '설명입니다.\n```json\n{"arms":["W"],"budget":2}\n```\n끝.'
        self.assertEqual(llm.extract_json(text)["arms"], ["W"])

    def test_missing_json_raises(self):
        with self.assertRaises(ValueError):
            llm.extract_json("JSON 없이 문장만")

    def test_array_is_rejected(self):
        with self.assertRaises(ValueError):
            llm.extract_json('[1,2,3]')


class NormalizeTest(unittest.TestCase):
    def test_drops_unknown_arms_and_sorts_contract_order(self):
        out = llm.normalize({"arms": ["w", "X", "E"], "condition": "slippery"})
        self.assertEqual(out["arms"], ["E", "W"])
        self.assertEqual(out["condition"], "slippery")
        self.assertFalse(out["ambiguous"])

    def test_road_names_become_arms(self):
        out = llm.normalize({"arms": ["올림픽로", "테헤란로115길"]})
        self.assertEqual(out["arms"], ["N", "E"])

    def test_budget_clamped_to_0_4(self):
        self.assertEqual(llm.normalize({"budget": 9})["budget"], 4)
        self.assertEqual(llm.normalize({"budget": -3})["budget"], 0)
        self.assertEqual(llm.normalize({"budget": "2회분"})["budget"], 2)
        self.assertIsNone(llm.normalize({"budget": None})["budget"])
        self.assertIsNone(llm.normalize({"budget": "모름"})["budget"])

    def test_unknown_condition_falls_back(self):
        self.assertEqual(llm.normalize({"condition": "폭설"})["condition"], "other")

    def test_ambiguous_without_question_gets_default(self):
        out = llm.normalize({"ambiguous": True})
        self.assertTrue(out["ambiguous"])
        self.assertTrue(out["question"])
        self.assertIn("갈래", out["question"])

    def test_not_ambiguous_clears_question(self):
        out = llm.normalize({"ambiguous": False, "question": "어디인가요?"})
        self.assertEqual(out["question"], "")

    def test_summary_default(self):
        out = llm.normalize({"arms": ["E"], "condition": "snow"})
        self.assertIn("E", out["summary"])
        empty = llm.normalize({})
        self.assertIn("확인", empty["summary"])

    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            llm.normalize(["E"])


class RuleParseTest(unittest.TestCase):
    def check(self, text, arms, condition=None, budget=None, ambiguous=False):
        out = llm.rule_parse(text)
        self.assertEqual(out["arms"], arms, text)
        if condition is not None:
            self.assertEqual(out["condition"], condition, text)
        if budget is not None:
            self.assertEqual(out["budget"], budget, text)
        self.assertEqual(out["ambiguous"], ambiguous, text)
        return out

    def test_bridge_arm(self):
        self.check("올림픽로 교량 위가 미끄럽습니다", ["E"], "slippery")

    def test_shade_arm(self):
        self.check("테헤란로 그늘 쪽에 살얼음이 보여요", ["W"], "ice_suspected")

    def test_north_road(self):
        self.check("테헤란로115길 북쪽 끝이 얼었습니다", ["N"], "ice_suspected")

    def test_short_north_name(self):
        self.check("북쪽 115길이 하얗게 얼었습니다", ["N"], "ice_suspected")

    def test_south_road(self):
        self.check("역삼로107길 남쪽에 사고가 났어요", ["S"], "accident")

    def test_direction_words(self):
        self.check("동쪽 다리 위가 얼음이에요", ["E"], "ice_suspected")
        self.check("서쪽 테헤란로가 젖어 있어요", ["W"], "slippery")

    def test_two_arms(self):
        self.check("교량이랑 그늘 쪽 둘 다 미끄러워요", ["E", "W"], "slippery")

    def test_budget_from_report(self):
        self.check("올림픽로 교량 미끄럼, 남은 제설제 2회분", ["E"], "slippery", budget=2)
        self.check("예산 3 남았습니다. 역삼로107길이 얼었어요", ["S"], budget=3)

    def test_teheran_alone_is_ambiguous(self):
        out = self.check("테헤란로가 미끄럽습니다", [], "slippery", ambiguous=True)
        self.assertIn("115길", out["question"])

    def test_no_place_is_ambiguous(self):
        out = self.check("어딘가 얼음 같아 보여요", [], "ice_suspected", ambiguous=True)
        self.assertTrue(out["question"])
        self.assertIn("올림픽로", out["question"])

    def test_empty_text(self):
        out = self.check("", [], "other", ambiguous=True)
        self.assertTrue(out["question"])

    def test_explicit_letter(self):
        self.check("E 갈래 얼음", ["E"], "ice_suspected")

    def test_all_arms_phrase(self):
        self.check("사거리 전체가 얼음 같아요", ["N", "E", "S", "W"], "ice_suspected")
        self.check("네 갈래 모두 미끄럽습니다", ["N", "E", "S", "W"], "slippery")

    def test_clear_condition(self):
        self.check("올림픽로는 이상 없습니다", ["E"], "clear")


class ApiHeaderTest(unittest.TestCase):
    def test_headers_and_body(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = dict((k.lower(), v) for k, v in req.header_items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"choices": [{"message": {"content": '{"arms":["E"]}'}}]})

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            text = llm.chat_text("시스템", "제보", key="k", api_base="https://example.test/v1")

        self.assertEqual(text, '{"arms":["E"]}')
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["headers"]["user-agent"], "icezero-model/1.0")
        self.assertEqual(captured["headers"]["authorization"], "Bearer k")
        self.assertEqual(captured["body"]["max_tokens"], 2000)
        self.assertEqual(captured["body"]["messages"][0]["role"], "system")
        self.assertEqual(captured["body"]["messages"][1]["content"], "제보")

    def test_empty_body_raises(self):
        with mock.patch("urllib.request.urlopen",
                        lambda req, timeout=None: FakeResponse(
                            {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]})):
            with self.assertRaises(ValueError):
                llm.chat_text("s", "u", key="k")


class InterpretTest(unittest.TestCase):
    def test_rule_only_never_calls_network(self):
        with mock.patch("llm.chat_text", side_effect=AssertionError("네트워크를 부르면 안 된다")):
            out = llm.interpret("올림픽로 교량이 미끄럽습니다", use_llm=False)
        self.assertEqual(out["engine"], "rule")
        self.assertIsNone(out["error"])
        self.assertEqual(out["result"]["arms"], ["E"])
        self.assertEqual(out["rule"]["arms"], ["E"])

    def test_llm_success(self):
        with mock.patch("llm.chat_text", return_value='{"arms":["E","W"],"condition":"snow"}'):
            out = llm.interpret("어딘가 눈", use_llm=True, key="k")
        self.assertEqual(out["engine"], "llm")
        self.assertEqual(out["result"]["arms"], ["E", "W"])
        self.assertIsNone(out["error"])
        self.assertGreaterEqual(out["latency_ms"], 0.0)

    def test_llm_failure_falls_back_to_rule(self):
        with mock.patch("llm.chat_text", side_effect=RuntimeError("boom")):
            out = llm.interpret("테헤란로115길이 얼었습니다", use_llm=True, key="k")
        self.assertEqual(out["engine"], "rule")
        self.assertEqual(out["result"]["arms"], ["N"])
        self.assertIn("LLM 실패", out["error"])
        self.assertEqual(out["result"], out["rule"])

    def test_system_prompt_has_arms_and_ambiguity_rule(self):
        self.assertIn("테헤란로115길", llm.SYSTEM)
        self.assertIn("올림픽로", llm.SYSTEM)
        self.assertIn("역삼로107길", llm.SYSTEM)
        self.assertIn("그늘", llm.SYSTEM)
        self.assertIn("모호", llm.SYSTEM)
        self.assertIn('"arms"', llm.SYSTEM)


if __name__ == "__main__":
    unittest.main()
