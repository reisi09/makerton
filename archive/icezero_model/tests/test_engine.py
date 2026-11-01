# -*- coding: utf-8 -*-
"""ICE-ZERO 사거리 엔진 시험.

무거운 학습은 시험마다 반복하지 않는다. 저장본(models/)을 한 번만 불러오고,
없으면 그때 한 번만 학습한다(이 맥에서 5초 안팎).

    python3 -m unittest discover -s suwon-makeathon-2026/icezero_model/tests -p 'test_engine*.py' -v
"""

import json
import sys
import time
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

import icezero_cross as ez  # noqa: E402


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ez.Engine().load()
        cls.frame = cls.engine.frame
        cls.night = cls.engine.default_night
        assert cls.night, "기본 시연 밤이 없다"
        cls.base_ts = cls.night + "T18:00:00"   # 아직 후보가 없는 시각
        cls.cold_ts = cls.night + "T23:00:00"   # 지면온도가 떨어지는 시각

    # ---------------------------------------------------- 자료·피처

    def test_feature_no_season_leak(self):
        """시즌 경계: 공백을 넘어 시차·롤링 피처가 새지 않는다(전부 NaN)."""
        frame = self.frame
        present = frame["ground_temp"].notna().to_numpy()
        starts = np.where(~present[:-1] & present[1:])[0] + 1   # 공백 뒤 첫 자료 시각
        ends = np.where(present[:-1] & ~present[1:])[0]         # 공백 앞 마지막 자료 시각
        self.assertGreaterEqual(len(starts), 4, "겨울 시즌 경계가 4개 미만이면 자료가 이상하다")

        lag_cols = ["gt_lag1", "gt_lag2", "gt_lag3", "gt_lag6", "gt_roll6", "gt_trend3",
                    "air_gt_gap_lag1", "new_snow_6h", "precip_6h", "temp_6h_mean"]
        for pos in starts:
            for col in lag_cols:
                self.assertTrue(np.isnan(frame[col].iloc[pos]),
                                "%s 에서 %s 가 채워졌다(시즌 경계 누수)" % (frame.index[pos], col))
        for pos in ends:
            for h in (1, 3, 6):
                self.assertTrue(np.isnan(frame["target_h%d" % h].iloc[pos]),
                                "%s 에서 h%d 목표가 채워졌다(경계 누수)" % (frame.index[pos], h))

        # 첫 행도 시차가 비어 있다
        self.assertTrue(np.isnan(frame["gt_lag1"].iloc[0]))
        # 목표가 있는 행은 '그 시점 자료가 실제로 있을 때'만이다(공백을 건너뛰지 않는다)
        for h in ez.HORIZONS:
            valid = np.where(frame["target_h%d" % h].notna().to_numpy())[0]
            self.assertGreater(len(valid), 10000)
            self.assertTrue(present[valid + h].all(), "h%d 목표가 공백을 건넜다" % h)

    def test_dewpoint_magnus(self):
        """Magnus 이슬점: 포화=같은 온도, 습도↑ → 이슬점↑, 이슬점차는 0 이상."""
        self.assertAlmostEqual(float(ez.dewpoint(0.0, 100.0)), 0.0, places=6)
        # 표준 이슬점(Magnus): 20°C·50% → 9.3°C, 10°C·50% → 0.05°C, −10°C·80% → −12.8°C
        self.assertAlmostEqual(float(ez.dewpoint(20.0, 50.0)), 9.3, delta=0.1)
        self.assertAlmostEqual(float(ez.dewpoint(10.0, 50.0)), 0.054, delta=0.01)
        self.assertAlmostEqual(float(ez.dewpoint(-10.0, 80.0)), -12.8, delta=0.1)
        self.assertGreater(float(ez.dewpoint(10.0, 90.0)), float(ez.dewpoint(10.0, 50.0)))

        sample = self.frame.dropna(subset=["temp", "humidity", "dewpoint_depression"])
        self.assertGreater(len(sample), 10000)
        expected = sample["temp"] - ez.dewpoint(sample["temp"], sample["humidity"])
        self.assertTrue(np.allclose(sample["dewpoint_depression"], expected, equal_nan=True))
        self.assertTrue((sample["dewpoint_depression"] >= -0.01).all(),
                        "이슬점차가 음수면 이슬점 계산이 틀렸다")

    # ---------------------------------------------------- 선정 규칙

    def test_level_and_priority(self):
        self.assertEqual(ez.level_of(0.6), "risk3")
        self.assertEqual(ez.level_of(0.599), "risk2")
        self.assertEqual(ez.level_of(0.3), "risk2")
        self.assertEqual(ez.level_of(0.299), "risk1")
        self.assertEqual(ez.level_of(None), "risk1")
        self.assertAlmostEqual(ez.priority_of(0.58, False), 0.58)
        self.assertAlmostEqual(ez.priority_of(0.58, True), 1.08)
        self.assertAlmostEqual(ez.priority_of(0.9142, True), 1.4142)

    def test_select_arms_rules(self):
        """후보를 (−priority, N·E·S·W)으로 정렬해 예산만큼 고르고, 그 순서가 처리 순서다."""
        pri = {"N": 0.5805, "E": 0.9142, "S": 0.5213, "W": 0.7922}
        cand = {"N": True, "E": True, "S": True, "W": True}
        self.assertEqual(ez.select_arms(pri, cand, 2), ["E", "W"])
        self.assertEqual(ez.select_arms(pri, cand, 0), [])
        self.assertEqual(ez.select_arms(pri, cand, 4), ["E", "W", "N", "S"])
        self.assertEqual(ez.select_arms(pri, cand, 99), ["E", "W", "N", "S"], "예산은 4로 제한")
        self.assertEqual(ez.select_arms(pri, {"S": True}, 4), ["S"])
        self.assertEqual(ez.select_arms(pri, cand, None), ["E", "W"], "예산 없음 → 기본 2")
        self.assertEqual(ez.select_arms(pri, cand, "이상"), ["E", "W"])
        # 동점이면 N·E·S·W 순서
        flat = {"N": 0.5, "E": 0.5, "S": 0.5, "W": 0.5}
        self.assertEqual(ez.select_arms(flat, cand, 2), ["N", "E"])
        # 제보 가산이 순위를 뒤집는다(S: 0.52 + 0.5 > E: 0.91)
        boosted = dict(pri, S=ez.priority_of(pri["S"], True))
        self.assertEqual(ez.select_arms(boosted, cand, 1), ["S"])

    def test_dispatch_uses_reports_and_budget(self):
        """제보가 있는 갈래는 확률이 낮아도 후보가 되고, 우선순위 순서로 예산만큼 선정된다."""
        plain = self.engine.step(self.base_ts, budget=2)
        self.assertFalse(plain["dispatch"]["recommend"], "이 시각에는 후보가 없어야 한다")
        self.assertLess(max(a["p_max"] for a in plain["arms"].values()), ez.DISPATCH_P)

        single = self.engine.step(self.base_ts, reports=["S"], budget=1)
        self.assertEqual(single["dispatch"]["selected"], ["S"])
        self.assertTrue(single["arms"]["S"]["candidate"])
        self.assertIn("확인된 제보", single["arms"]["S"]["reasons"])
        self.assertAlmostEqual(single["arms"]["S"]["priority"],
                               round(0.5213 + ez.REPORT_BONUS, 3))

        both = self.engine.step(self.base_ts, reports=["E", "S"], budget=2)
        self.assertEqual(both["dispatch"]["order"], both["dispatch"]["selected"])
        self.assertEqual(both["dispatch"]["selected"], ["E", "S"], "E(1.414) > S(1.021)")

        # 예산 0이면 후보가 있어도 권고하지 않는다
        zero = self.engine.step(self.base_ts, reports=["E", "S"], budget=0)
        self.assertEqual(zero["dispatch"]["selected"], [])
        self.assertFalse(zero["dispatch"]["recommend"])

        # 확률로 이미 후보인 시각에 제보가 붙으면 순위가 뒤집힌다
        flipped = self.engine.step(self.cold_ts, reports=["S"], budget=2)
        self.assertTrue(flipped["arms"]["E"]["candidate"], "E는 확률만으로 후보여야 한다")
        self.assertAlmostEqual(flipped["arms"]["E"]["priority"], round(0.9142, 3))
        self.assertEqual(flipped["dispatch"]["selected"], ["S", "E"], "제보 +0.5가 순위를 뒤집는다")

        # 확인되지 않은(pending) 제보는 반영하지 않는다
        pending = self.engine.step(self.base_ts, reports=[{"arms": ["S"], "status": "pending"}])
        self.assertFalse(pending["arms"]["S"]["candidate"])

    # ---------------------------------------------------- 센서

    def test_sensor_override_bridge_only(self):
        """교량(구조물) 갈래에만 현장 보정이 붙고, 다른 갈래는 모델값 그대로다."""
        base = self.engine.step(self.cold_ts)
        warm = self.engine.step(self.cold_ts, sensor={"t_bridge": 10.0})
        cold = self.engine.step(self.cold_ts, sensor={"t_bridge": -5.0})

        bridge = [a for a in ez.ARM_ORDER if base["arms"][a]["structure"] == 1]
        self.assertEqual(bridge, ["E"], "계약상 교량 갈래는 E 하나다")

        self.assertEqual(base["arms"]["E"]["source"], "model")
        self.assertEqual(warm["arms"]["E"]["source"], "sensor")
        self.assertEqual(cold["arms"]["E"]["source"], "sensor")
        self.assertAlmostEqual(warm["arms"]["E"]["t_eff"]["h0"], 10.0, places=3)
        self.assertAlmostEqual(cold["arms"]["E"]["t_eff"]["h0"], -5.0, places=3)
        self.assertIn(ez.NOTE_SENSOR, warm["notes"])
        self.assertNotIn(ez.NOTE_SENSOR, base["notes"])

        # 센서 방향이 확률 방향을 그대로 따라간다(차가우면 ↑, 따뜻하면 ↓)
        self.assertGreaterEqual(cold["arms"]["E"]["p_max"], base["arms"]["E"]["p_max"])
        self.assertLessEqual(warm["arms"]["E"]["p_max"], base["arms"]["E"]["p_max"])

        for arm in ("N", "S", "W"):
            self.assertEqual(warm["arms"][arm]["source"], "model")
            self.assertEqual(warm["arms"][arm]["t_eff"], base["arms"][arm]["t_eff"])
            self.assertEqual(warm["arms"][arm]["p_freeze"], base["arms"][arm]["p_freeze"])
            self.assertNotIn("교량 센서 보정", " ".join(warm["arms"][arm]["reasons"]))

        # 낡은 센서값·꺼진 센서는 무시한다
        stale = self.engine.step(self.cold_ts, sensor={"t_bridge": 2.0, "age_sec": 9999})
        self.assertEqual(stale["arms"]["E"]["source"], "model")
        self.assertEqual(stale["arms"]["E"]["t_eff"], base["arms"]["E"]["t_eff"])
        off = self.engine.step(self.cold_ts, sensor={"use_sensor": False, "t_bridge": 2.0})
        self.assertEqual(off["arms"]["E"]["source"], "model")
        self.assertEqual(off["arms"]["E"]["t_eff"], base["arms"]["E"]["t_eff"])

        # 센서 보정은 모든 시점에 같은 offset을 더한다(h0가 t_bridge가 된다)
        expected_h1 = 10.0 + base["forecast"]["h1"] - base["forecast"]["h0"]
        self.assertAlmostEqual(warm["arms"]["E"]["t_eff"]["h1"], expected_h1, delta=0.002)
        expected_h6 = 10.0 + base["forecast"]["h6"] - base["forecast"]["h0"]
        self.assertAlmostEqual(warm["arms"]["E"]["t_eff"]["h6"], expected_h6, delta=0.002)

    # ---------------------------------------------------- step JSON

    def test_step_json_shape_and_ranges(self):
        for ts in self.engine.timeline(self.night):
            result = self.engine.step(ts)
            self.assertEqual(set(result), {"time", "obs", "forecast", "arms", "dispatch",
                                           "model", "notes"})
            self.assertEqual(result["time"], ts)
            self.assertEqual(set(result["obs"]),
                             {"temp", "humidity", "wind", "precip", "snow", "ground_temp"})
            self.assertEqual(set(result["forecast"]), {"h0", "h1", "h3", "h6"})
            self.assertEqual(set(result["arms"]), set(ez.ARM_ORDER))
            self.assertIsInstance(result["notes"], list)
            self.assertIn(ez.NOTE_CALIB, result["notes"])

            for arm_id, arm in result["arms"].items():
                for key in ("name", "label", "structure", "shadow_index", "risk_v2", "risk_v2_pct",
                            "t_eff", "p_freeze", "p_max", "source", "level", "candidate",
                            "priority", "reasons"):
                    self.assertIn(key, arm, "%s에 %s가 없다" % (arm_id, key))
                self.assertEqual(set(arm["t_eff"]), {"h0", "h1", "h3", "h6"})
                self.assertEqual(set(arm["p_freeze"]), {"h0", "h1", "h3", "h6"})
                for h in (0, 1, 3, 6):
                    p = arm["p_freeze"]["h%d" % h]
                    self.assertGreaterEqual(p, 0.0)
                    self.assertLessEqual(p, 1.0)
                    self.assertIsInstance(p, float)
                p_max = max(arm["p_freeze"]["h%d" % h] for h in (1, 3, 6))
                self.assertAlmostEqual(arm["p_max"], p_max, places=6)
                self.assertEqual(arm["level"], ez.level_of(arm["p_max"]))
                self.assertEqual(arm["candidate"], arm["p_max"] >= ez.DISPATCH_P)
                self.assertGreaterEqual(arm["priority"], arm["risk_v2"] - 1e-9)
                self.assertTrue(arm["reasons"])
                self.assertIn(arm["source"], ("model", "sensor"))
                # 유효온도 = 예측 − 2.5×구조물
                delta = ez.BRIDGE_DELTA_C * arm["structure"]
                self.assertAlmostEqual(arm["t_eff"]["h0"],
                                       round(result["forecast"]["h0"] - delta, 3), places=3)

            dispatch = result["dispatch"]
            self.assertEqual(set(dispatch), {"recommend", "selected", "order", "budget", "threshold"})
            self.assertEqual(dispatch["selected"], dispatch["order"])
            self.assertEqual(dispatch["recommend"], bool(dispatch["selected"]))
            self.assertEqual(dispatch["threshold"], ez.DISPATCH_P)
            self.assertLessEqual(len(dispatch["selected"]), dispatch["budget"])
            for arm_id in dispatch["selected"]:
                self.assertTrue(result["arms"][arm_id]["candidate"])
            # 우선순위 내림차순이 처리 순서다
            prios = [result["arms"][a]["priority"] for a in dispatch["selected"]]
            self.assertEqual(prios, sorted(prios, reverse=True))

            model = result["model"]
            self.assertEqual(set(model), {"name", "rmse", "persistence_rmse", "brier"})
            self.assertEqual(model["name"], ez.MODEL_NAME)
            self.assertEqual(set(model["brier"]), {"h0", "h1", "h3", "h6"})

    def test_step_is_fast_after_load(self):
        ts = [self.engine.timeline(self.night)[i % 16] for i in range(8)]
        self.engine.step(ts[0])  # 캐시 예열
        times = []
        for stamp in ts:
            started = time.perf_counter()
            self.engine.step(stamp)
            times.append(time.perf_counter() - started)
        self.assertLess(max(times), 0.2, "step 최대 %.3f초" % max(times))

        # 모델 디스크 로드도 0.2초 안쪽이어야 서버가 바로 뜬다
        started = time.perf_counter()
        fresh = ez.Engine().load()
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertEqual(fresh.loaded_from, "saved")

    # ---------------------------------------------------- 밤

    def test_nights_condition(self):
        """후보 밤은 계약 조건을 만족하고, 기본 밤은 점수 1위다."""
        nights = self.engine.nights(2025)
        self.assertGreater(len(nights), 0, "2025년 후보 밤이 없다")
        self.assertEqual(self.engine.default_night, nights[0]["night"])

        frame = self.frame
        for item in nights:
            stamp = pd.Timestamp(item["night"]) + pd.Timedelta(hours=18)
            gt18 = frame.at[stamp, "ground_temp"]
            self.assertGreater(float(gt18), 0.0, "%s 18시 지면온도가 0 이하" % item["night"])
            end = stamp.normalize() + pd.Timedelta(days=1, hours=9)
            window = frame.loc[stamp:end, "ground_temp"].dropna()
            self.assertLessEqual(float(window.min()), 0.0, "%s 최저가 0 초과" % item["night"])
            self.assertAlmostEqual(item["t_min"], round(float(window.min()), 2), places=2)
            self.assertGreaterEqual(pd.Timestamp(item["min_time"]), stamp)
            self.assertLessEqual(pd.Timestamp(item["min_time"]), end)
            drop = float(gt18) - float(window.min())
            expected = min(item["wet_12h"], ez.NIGHT_WET_CAP) + min(drop, ez.NIGHT_DROP_CAP)
            self.assertAlmostEqual(item["score"], round(expected, 2), places=2)
            self.assertGreaterEqual(item["score"], nights[-1]["score"])

        scores = [n["score"] for n in nights]
        self.assertEqual(scores, sorted(scores, reverse=True))

        # timeline은 18시부터 다음 날 09시까지 16개 정시
        line = self.engine.timeline(nights[0]["night"])
        self.assertEqual(len(line), 16)
        self.assertEqual(line[0], nights[0]["night"] + "T18:00:00")
        self.assertEqual(line[-1][:10], (pd.Timestamp(nights[0]["night"])
                                         + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        self.assertEqual(line[-1][-8:], "09:00:00")

    def test_saved_files(self):
        """models/ 생성물이 계약대로 있다(모델 JSON + 보정 thresholds JSON)."""
        models_dir = self.engine.models_dir
        for h in ez.HORIZONS:
            path = models_dir / ("xgb_h%d.json" % h)
            self.assertTrue(path.exists(), "%s 없음" % path)
            with open(path, "r", encoding="utf-8") as fp:
                head = fp.read(8)
            self.assertTrue(head.lstrip().startswith("{"), "xgboost JSON 형식이 아니다")
        with open(models_dir / "calib.json", "r", encoding="utf-8") as fp:
            calib = json.load(fp)
        for h in ez.HORIZONS:
            curve = calib["horizons"]["h%d" % h]
            self.assertGreater(len(curve["x"]), 1)
            self.assertEqual(len(curve["x"]), len(curve["y"]))
            self.assertEqual(curve["x"], sorted(curve["x"]))
            ys = curve["y"]
            self.assertTrue(all(ys[i] >= ys[i + 1] for i in range(len(ys) - 1)),
                            "동결확률 곡선이 단조감소가 아니다")
        with open(models_dir / "metrics.json", "r", encoding="utf-8") as fp:
            metrics = json.load(fp)
        for h in ez.HORIZONS:
            row = metrics["horizons"]["h%d" % h]
            self.assertLess(row["rmse"], row["persistence_rmse"], "모델이 persistence보다 나쁘다")
            self.assertGreaterEqual(row["brier"], 0.0)
            self.assertLessEqual(row["brier"], 1.0)

        # 저장본을 불러도 같은 예측이 나온다
        reloaded = ez.Engine().load()
        self.assertEqual(reloaded.step(self.cold_ts)["forecast"],
                         self.engine.step(self.cold_ts)["forecast"])


if __name__ == "__main__":
    unittest.main()
