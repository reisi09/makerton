# -*- coding: utf-8 -*-
"""web/lib/routeTable.json이 server/route.py plan()과 같아야 조작 화면이 그리는 최적 경로가 실제 출동 경로와 같다."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import make_route_table  # noqa: E402


class RouteTableTest(unittest.TestCase):
    def test_table_matches_the_planner(self):
        with open(make_route_table.OUT, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved, make_route_table.table(), "경로·기구 상수가 바뀌었다: python3 tools/make_route_table.py 로 다시 만든다")
        self.assertEqual(len(saved), 16)                     # N·E·S·W 조합 15가지 + 교차로만
        self.assertEqual(sorted(saved["NESW"]["order"]), ["E", "N", "S", "W"])


if __name__ == "__main__":
    unittest.main()
