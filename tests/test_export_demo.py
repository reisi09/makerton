# -*- coding: utf-8 -*-
"""tools/export_demo.py: 실제 119 모델로 밤 하나를 내보내 데모 자료의 형식과 방향을 본다."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import export_demo  # noqa: E402
from model.icezero.engine import Engine  # noqa: E402


@unittest.skipUnless((ROOT / "model" / "models" / "119" / "metrics.json").exists(), "119 모델 없음")
class ExportDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Engine(stn="119")
        cls.engine.load()
        cls.night = export_demo.export_night(cls.engine, cls.engine.nights()[0]["night"])

    def test_night_has_hourly_steps_with_probability_grid(self):
        steps = self.night["steps"]
        self.assertEqual(len(steps), export_demo.NIGHT_HOURS)
        self.assertTrue(steps[0]["t"].endswith("T18:00:00"))
        for s in steps:
            for h in export_demo.P_HORIZONS:
                self.assertEqual(len(s["p"][h]), len(export_demo.DT_GRID))
                self.assertTrue(all(0.0 <= p <= 1.0 for p in s["p"][h]))

    def test_colder_local_reading_never_lowers_probability(self):
        # 얼음팩(현장 −6°C) 쪽이 따뜻한 쪽(+3°C)보다 동결확률이 낮으면 슬라이더가 거꾸로 동작한다
        for s in self.night["steps"]:
            for h in export_demo.P_HORIZONS:
                self.assertGreaterEqual(s["p"][h][0], s["p"][h][-1])

    def test_truth_is_observed_ground_temp_later(self):
        frame = self.engine.frame
        s = self.night["steps"][0]
        import pandas as pd
        later = pd.Timestamp(s["t"]) + pd.Timedelta(hours=1)
        self.assertAlmostEqual(s["truth"]["h1"], round(float(frame["ground_temp"][later]), 1))


if __name__ == "__main__":
    unittest.main()
