# -*- coding: utf-8 -*-
"""server/route.py 시험: 갈래별 눈 → 기지에서 출발해 눈 있는 갈래를 도는 가장 빠른 순서."""
import itertools
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server import route  # noqa: E402


def arms(**snow):
    return {a: {"area_mm2": snow.get(a, 0), "far_mm": 0} for a in "CNESW"}


class RouteTest(unittest.TestCase):
    def test_visits_exactly_the_snowy_arms(self):
        p = route.plan(arms(N=720, W=387, S=101, E=60))
        self.assertEqual(sorted(p["order"]), ["N", "S", "W"])          # E 60은 기준(100) 아래

    def test_chosen_order_is_the_fastest_of_all_orders(self):
        snow = arms(N=720, E=163, S=101, W=387)
        p = route.plan(snow)
        every = [route.steps(o) for o in itertools.permutations("NESW")]
        self.assertEqual(route.steps(p["order"]), min(every))
        self.assertEqual(p["tried"], 24)
        self.assertGreater(p["worst_seconds"], p["seconds"])

    def test_ties_go_to_the_arm_with_more_snow_first(self):
        # E·W 두 갈래는 어느 순서든 회전량이 같다(90 + 180 + 90)
        self.assertEqual(route.steps(["E", "W"]), route.steps(["W", "E"]))
        self.assertEqual(route.plan(arms(E=500, W=200))["order"], ["E", "W"])
        self.assertEqual(route.plan(arms(E=200, W=500))["order"], ["W", "E"])

    def test_snow_only_in_the_crossroad_is_pushed_out_the_shortest_arm(self):
        self.assertEqual(route.plan(arms(C=300))["order"], ["E"])

    def test_no_snow_no_route(self):
        self.assertIsNone(route.plan(arms(C=30, N=20)))
        self.assertFalse(route.decide(arms())["go"])

    def test_path_leaves_and_returns_to_the_garage(self):
        p = route.plan(arms(S=400))
        self.assertEqual(p["path"][0], [775, 250, 270])
        self.assertEqual(p["path"][-1], [775, 250, 270])
        self.assertGreater(max(y for _, y, _ in p["path"]), 480 + 300)   # S 갈래 끝까지 내려갔다

    def test_vague_amount_or_unsure_photo_sweeps_every_arm(self):
        everything = sorted(route.plan(route.ALL)["order"])
        for d in (route.decide(arms(N=720, E=60)),                  # E 60은 눈인지 반사인지 애매하다
                  route.decide(arms(C=45)),
                  route.decide(arms(), sure=False)):                 # 비스듬한 사진은 0이라도 믿지 않는다
            self.assertTrue(d["go"])
            self.assertEqual(sorted(d["plan"]["order"]), everything)
            self.assertIn("전체 청소", d["text"])
        self.assertFalse(route.decide(arms(N=14, S=7))["go"])        # 위에서 찍은 눈 없는 사진 수준

    def test_decide_text_names_the_order(self):
        d = route.decide(arms(N=720, W=387))
        self.assertTrue(d["go"])
        self.assertIn("→".join(d["plan"]["order"]), d["text"])


if __name__ == "__main__":
    unittest.main()
