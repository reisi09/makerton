# -*- coding: utf-8 -*-
"""모델 시험 (계약 3절).

    python3 -m unittest tests.test_model      (저장소 루트에서)

무거운 학습은 시험마다 반복하지 않는다. 작은 XGB(40그루)로 임시 폴더에 한 번만
학습해 산출물·엔진을 만들고, 저장본(model/models/<stn>)에는 기대지 않는다.

확인하는 것
- 자료 읽기: cp949·utf-8-sig 원본, 중복 시각 제거, 매시 reindex
- 누수 방지: 겨울 시즌 경계를 넘어 시차·목표가 새지 않는다
- 방법 선택: Brier 최소, 동점은 reg
- local_dt: 음수가 유효온도를 낮추고 동결확률을 올린다, [−6, +3] 자름
- treated: 효과가 남아 있으면 level done·후보 제외, 지난 시각이면 원래대로
- step: 계약 키·3자리 반올림·우선순위 순서·예산, 1회 0.2초 이내
"""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from model.icezero import engine as engine_mod
from model.icezero import features, kma, train

SMALL_REG = dict(train.XGB_PARAMS, n_estimators=40)
SMALL_CLF = dict(train.CLF_PARAMS, n_estimators=40)

# 시험용 고정 갈래(roads.py 산출물 모양 그대로). E는 교량, W는 그늘.
ARMS = {
    "source": {"note": "시험용 고정값"},
    "arms": {
        "N": {"name": "북쪽 일반", "label": "general", "structure": 0, "shadow_index": 0.10,
              "risk": 0.30, "risk_pct": 0.25, "bearing_deg": 0, "length_m": 30,
              "osm_ids": [], "near_water": False},
        "E": {"name": "동쪽 교량", "label": "bridge", "structure": 1, "shadow_index": 0.45,
              "risk": 0.90, "risk_pct": 0.95, "bearing_deg": 90, "length_m": 40,
              "osm_ids": [], "near_water": True},
        "S": {"name": "남쪽 일반", "label": "general", "structure": 0, "shadow_index": 0.05,
              "risk": 0.20, "risk_pct": 0.15, "bearing_deg": 180, "length_m": 30,
              "osm_ids": [], "near_water": False},
        "W": {"name": "서쪽 그늘", "label": "general", "structure": 0, "shadow_index": 0.60,
              "risk": 0.50, "risk_pct": 0.60, "bearing_deg": 270, "length_m": 35,
              "osm_ids": [], "near_water": False},
    },
}

ARM_KEYS = {
    "name", "label", "structure", "shadow_index", "risk", "risk_pct", "local_dt", "wet",
    "t_eff", "p_freeze", "p_max", "source", "level", "candidate", "treated", "priority",
    "reasons",
}


class ModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="icezero_model_test_"))
        cls.models_dir = cls.tmp / "models" / "108"
        cls.arms_path = cls.tmp / "cross_arms.json"
        cls.arms_path.write_text(json.dumps(ARMS, ensure_ascii=False), encoding="utf-8")

        patches = [
            mock.patch.object(train, "XGB_PARAMS", SMALL_REG),
            mock.patch.object(train, "CLF_PARAMS", SMALL_CLF),
        ]
        for patch in patches:
            patch.start()
        try:
            train.train("108", models_dir=cls.models_dir, quiet=True)
        finally:
            for patch in patches:
                patch.stop()

        cls.engine = engine_mod.Engine(
            stn="108", models_dir=cls.models_dir, arms_path=cls.arms_path
        ).load()
        cls.frame = features.build_features(kma.load_station("108"))
        cls.night = cls.engine.default_night

        # 경보가 실제로 나오는 시각을 하나 찾아 둔다(없으면 None).
        cls.dispatch_ts = None
        for item in cls.engine.nights()[:10]:
            for ts in cls.engine.timeline(item["night"]):
                if cls.engine.step(ts)["dispatch"]["selected"]:
                    cls.dispatch_ts = ts
                    break
            if cls.dispatch_ts:
                break
        cls.sample_ts = cls.dispatch_ts or (cls.night + "T23:00:00")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ------------------------------------------------------------ 자료

    def test_station_reads_cp949_and_utf8sig(self):
        """포털 원본(cp949)과 BOM 있는 같은 자료(utf-8-sig)를 모두 읽고 중복을 지운다."""
        root = Path(tempfile.mkdtemp(prefix="icezero_kma_"))
        try:
            folder = root / "data" / "raw" / "T"
            folder.mkdir(parents=True)
            header = ("지점,일시,기온(°C),강수량(mm),풍속(m/s),습도(%),일조(hr),"
                      "일사(MJ/m2),적설(cm),지면온도(°C)")
            rows = [
                "108,2025-01-01 00:00,-3.0,0.0,1.0,70,0.0,0.0,0.0,-1.5",
                "108,2025-01-01 01:00,-3.2,0.0,1.1,72,0.0,0.0,0.0,-1.7",
            ]
            text = header + "\n" + "\n".join(rows) + "\n"
            (folder / "OBS_ASOS_TIM_a.csv").write_bytes(text.encode("cp949"))
            (folder / "OBS_ASOS_TIM_b.csv").write_text(text, encoding="utf-8-sig")

            frame = kma.load_station("T", data_dir=root / "data")
            self.assertEqual(list(frame.columns), list(kma.STANDARD_COLUMNS))
            self.assertEqual(len(frame), 2)             # 중복 시각은 하나로
            self.assertEqual(frame.index.freqstr, "h")  # 매시 격자
            self.assertAlmostEqual(float(frame["ground_temp"].iloc[0]), -1.5)
            self.assertAlmostEqual(float(frame["humidity"].iloc[1]), 72.0)
            self.assertIn("sunshine", frame.columns)
            self.assertIn("solar", frame.columns)

            empty = root / "data" / "raw" / "NONE"
            empty.mkdir(parents=True)
            with self.assertRaises(kma.StationDataMissing):
                kma.load_station("NONE", data_dir=root / "data")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_feature_no_season_leak(self):
        """겨울 시즌 경계: 시차·롤링 피처와 목표가 공백을 건너 채워지지 않는다."""
        frame = self.frame
        present = frame["ground_temp"].notna().to_numpy()
        starts = np.where(~present[:-1] & present[1:])[0] + 1   # 공백 뒤 첫 관측
        ends = np.where(present[:-1] & ~present[1:])[0]         # 공백 앞 마지막 관측
        self.assertGreaterEqual(len(starts), 4, "겨울 시즌 경계가 4개 미만이다")

        lag_cols = [
            "gt_lag1", "gt_lag2", "gt_lag3", "gt_lag6", "gt_roll6", "gt_trend3",
            "air_gt_gap_lag1", "gt_min24", "new_snow_6h", "precip_6h", "temp_6h_mean",
            "humidity_trend3",
        ]
        for pos in starts:
            for col in lag_cols:
                self.assertTrue(
                    np.isnan(frame[col].iloc[pos]),
                    "%s 에서 %s 가 채워졌다(시즌 경계 누수)" % (frame.index[pos], col),
                )
        for pos in ends:
            for h in (1, 3, 6):
                self.assertTrue(
                    np.isnan(frame[features.target_column(h)].iloc[pos]),
                    "%s 에서 h%d 목표가 채워졌다(경계 누수)" % (frame.index[pos], h),
                )
        self.assertTrue(np.isnan(frame["gt_lag1"].iloc[0]))

        for h in (1, 3, 6):
            valid = np.where(frame[features.target_column(h)].notna().to_numpy())[0]
            self.assertGreater(len(valid), 5000)
            self.assertTrue(present[valid + h].all(), "h%d 목표가 공백을 건넜다" % h)

    def test_target_is_ground_temp_after_h(self):
        """목표 열은 정확히 h시간 뒤 관측 지면온도다."""
        frame = self.frame
        index = frame.index
        for h in (1, 3, 6):
            target = features.target_column(h)
            rows = frame.iloc[:-h][[target]]
            expected = frame["ground_temp"].shift(-h).iloc[:-h]
            self.assertTrue(np.allclose(rows[target], expected, equal_nan=True))
        self.assertTrue(np.allclose(frame["target_h0"], frame["ground_temp"], equal_nan=True))
        self.assertEqual(index[1] - index[0], pd.Timedelta(hours=1))

    # ------------------------------------------------------------ 선택·상수

    def test_pick_method(self):
        """Brier 최소를 고르고, 동점은 reg → clf → blend 순서."""
        self.assertEqual(train.pick_method({"reg": 0.20, "clf": 0.10, "blend": 0.15}), "clf")
        self.assertEqual(train.pick_method({"reg": 0.12, "clf": 0.20, "blend": 0.15}), "reg")
        self.assertEqual(train.pick_method({"reg": 0.10, "clf": 0.10, "blend": 0.10}), "reg")
        self.assertEqual(train.pick_method({"reg": 0.30, "clf": 0.10, "blend": 0.10}), "clf")
        self.assertEqual(
            train.pick_method({"reg": float("nan"), "clf": 0.05, "blend": float("nan")}), "clf"
        )
        self.assertEqual(train.pick_method({}), "reg")

    def test_clamp_helpers(self):
        self.assertEqual(engine_mod.clamp_budget(None), 2)
        self.assertEqual(engine_mod.clamp_budget(9), 4)
        self.assertEqual(engine_mod.clamp_budget(-3), 0)
        self.assertEqual(engine_mod.clamp_budget("x"), 2)
        self.assertEqual(engine_mod.clamp_local_dt(-12.0), -6.0)
        self.assertEqual(engine_mod.clamp_local_dt(9.0), 3.0)
        self.assertEqual(engine_mod.clamp_local_dt(None), 0.0)
        self.assertEqual(engine_mod.level_of(0.61), "risk3")
        self.assertEqual(engine_mod.level_of(0.31), "risk2")
        self.assertEqual(engine_mod.level_of(0.10), "risk1")
        self.assertAlmostEqual(engine_mod.priority_of(0.5, True), 0.8)

    def test_metrics_have_selection_and_events(self):
        """산출물 metrics.json에 방법 선택·rolling·사건 지표가 실제 값으로 있다."""
        with open(self.models_dir / "metrics.json", "r", encoding="utf-8") as fp:
            metrics = json.load(fp)
        self.assertEqual(set(metrics["methods"]), {"h0", "h1", "h3", "h6"})
        self.assertEqual(metrics["methods"]["h0"], "reg")
        for h in (1, 3, 6):
            self.assertIn(metrics["methods"]["h%d" % h], ("reg", "clf", "blend"))
            self.assertIsNotNone(metrics["method_selection"]["h%d" % h]["brier"]["blend"])
        for year in ("2022", "2023", "2024", "2025"):
            self.assertIsNotNone(metrics["rolling"][year]["h6"]["rmse"])
            self.assertIsNotNone(metrics["rolling"][year]["h6"]["persistence_rmse"])
            self.assertIsNotNone(metrics["rolling"][year]["h6"]["air_rmse"])
        events = metrics["events"]
        self.assertGreater(events["nights_total"], 0)
        self.assertIsNotNone(events["hit_rate"])
        self.assertIsNotNone(events["false_alarm_rate"])
        self.assertIn("alarm", events["definition"])
        self.assertEqual(events["p_threshold"], engine_mod.DISPATCH_P)

    # ------------------------------------------------------------ 엔진

    def test_available_and_errors(self):
        self.assertTrue(self.engine.available())
        empty = self.tmp / "empty_models"
        empty.mkdir(exist_ok=True)
        blank = engine_mod.Engine(stn="108", models_dir=empty, arms_path=self.arms_path)
        self.assertFalse(blank.available())
        with self.assertRaises(FileNotFoundError):
            blank.load()

        with self.assertRaises(FileNotFoundError) as caught:
            engine_mod.Engine(stn="108", models_dir=self.models_dir,
                              arms_path=self.tmp / "no_arms.json")
        self.assertIn("갈래 파일이 없다", str(caught.exception))

    def test_timeline(self):
        stamps = self.engine.timeline(self.night)
        self.assertEqual(len(stamps), 16)
        self.assertTrue(stamps[0].endswith("T18:00:00"))
        self.assertTrue(stamps[-1].endswith("T09:00:00"))
        later = self.engine.timeline("2025-12-07")
        self.assertEqual(later[0], "2025-12-07T18:00:00")

    def test_step_keys_and_rounding(self):
        out = self.engine.step(self.sample_ts)
        self.assertEqual(
            set(out),
            {"time", "station", "obs", "forecast", "arms", "dispatch", "model", "notes"},
        )
        self.assertEqual(out["station"], "108")
        self.assertEqual(set(out["arms"]), set(engine_mod.ARM_ORDER))
        arm = out["arms"]["E"]
        self.assertEqual(set(arm), ARM_KEYS)
        self.assertEqual(set(out["dispatch"]),
                         {"recommend", "selected", "order", "budget", "threshold"})
        self.assertEqual(set(out["model"]),
                         {"name", "station", "method", "rmse", "persistence_rmse", "brier"})
        self.assertEqual(set(out["forecast"]), {"h0", "h1", "h3", "h6"})
        for key in ("h0", "h1", "h3", "h6"):
            for value in list(arm["t_eff"].values()) + list(arm["p_freeze"].values()):
                self.assertEqual(round(value, 3), value, "3자리 반올림이 아니다")
            self.assertEqual(round(out["forecast"][key], 3), out["forecast"][key])
        self.assertGreaterEqual(arm["p_max"], 0.0)
        self.assertLessEqual(arm["p_max"], 1.0)
        self.assertIn(arm["level"], {"risk1", "risk2", "risk3", "done"})
        self.assertIn(arm["source"], {"model", "model+local"})
        self.assertEqual(out["dispatch"]["threshold"], 0.5)

    def test_local_dt_direction(self):
        """현장 기온이 낮으면(local_dt < 0) 유효온도가 내려가고 동결확률이 오른다."""
        ts = self.sample_ts
        base = self.engine.step(ts)
        cold = self.engine.step(ts, local={"E": {"dt": -4.0}})

        self.assertAlmostEqual(
            cold["arms"]["E"]["t_eff"]["h6"], base["arms"]["E"]["t_eff"]["h6"] - 4.0, delta=0.002
        )
        self.assertGreaterEqual(
            cold["arms"]["E"]["p_freeze"]["h6"], base["arms"]["E"]["p_freeze"]["h6"] - 1e-9
        )
        self.assertEqual(cold["arms"]["E"]["source"], "model+local")
        self.assertTrue(any("현장" in why for why in cold["arms"]["E"]["reasons"]))
        self.assertAlmostEqual(
            cold["arms"]["E"]["priority"], base["arms"]["E"]["priority"], places=3
        )

        # 자름: 아래 −6, 위 +3
        self.assertEqual(self.engine.step(ts, local={"N": {"dt": -12.0}})["arms"]["N"]["local_dt"], -6.0)
        self.assertEqual(self.engine.step(ts, local={"S": {"dt": 9.0}})["arms"]["S"]["local_dt"], 3.0)
        # 빠진 갈래는 0과 False
        self.assertEqual(cold["arms"]["S"]["local_dt"], 0.0)
        self.assertFalse(cold["arms"]["S"]["wet"])
        self.assertEqual(cold["arms"]["S"]["source"], "model")

    def test_wet_priority(self):
        """젖은 갈래는 우선순위 +0.3, source는 model+local."""
        ts = self.sample_ts
        base = self.engine.step(ts)
        wet = self.engine.step(ts, local={"W": {"dt": 0.0, "wet": True}})
        self.assertTrue(wet["arms"]["W"]["wet"])
        self.assertAlmostEqual(
            wet["arms"]["W"]["priority"], base["arms"]["W"]["priority"] + 0.3, places=3
        )
        self.assertEqual(wet["arms"]["W"]["source"], "model+local")
        self.assertTrue(any("젖음" in why for why in wet["arms"]["W"]["reasons"]))

    def test_treated_excluded(self):
        """효과가 남은 갈래는 level done·후보 아님·선정 제외. 지난 시각이면 원래대로."""
        if not self.dispatch_ts:
            self.skipTest("경보가 나오는 시각이 없어 treated 시험을 건너뛴다")
        ts = self.dispatch_ts
        picked = self.engine.step(ts)["dispatch"]["selected"]
        self.assertTrue(picked)

        end = (pd.Timestamp(ts) + pd.Timedelta(hours=3)).isoformat()
        after = self.engine.step(ts, treated={arm: end for arm in picked})
        for arm in picked:
            self.assertTrue(after["arms"][arm]["treated"])
            self.assertEqual(after["arms"][arm]["level"], "done")
            self.assertFalse(after["arms"][arm]["candidate"])
            self.assertNotIn(arm, after["dispatch"]["selected"])
            self.assertNotIn(arm, after["dispatch"]["order"])

        past = (pd.Timestamp(ts) - pd.Timedelta(hours=1)).isoformat()
        restored = self.engine.step(ts, treated={arm: past for arm in picked})
        for arm in picked:
            self.assertFalse(restored["arms"][arm]["treated"])
            self.assertNotEqual(restored["arms"][arm]["level"], "done")
        self.assertEqual(restored["dispatch"]["selected"], picked)

    def test_candidate_rule_and_budget(self):
        """후보는 p_max ≥ 0.5 이고 처리되지 않은 갈래. 예산만큼 우선순위 순서로 고른다."""
        ts = self.sample_ts
        out = self.engine.step(ts, budget=4)
        for arm, item in out["arms"].items():
            self.assertEqual(
                item["candidate"], bool(item["p_max"] >= 0.5 and not item["treated"])
            )
        order = out["dispatch"]["order"]
        self.assertEqual(order, out["dispatch"]["selected"])
        self.assertLessEqual(len(order), 4)
        priorities = [out["arms"][arm]["priority"] for arm in order]
        self.assertEqual(priorities, sorted(priorities, reverse=True))
        # 동점이면 N·E·S·W 순서
        for before, after in zip(order, order[1:]):
            if out["arms"][before]["priority"] == out["arms"][after]["priority"]:
                self.assertLess(
                    engine_mod.ARM_ORDER.index(before), engine_mod.ARM_ORDER.index(after)
                )
        self.assertEqual(out["dispatch"]["budget"], 4)
        self.assertEqual(out["dispatch"]["recommend"], bool(order))

        none = self.engine.step(ts, budget=0)
        self.assertEqual(none["dispatch"]["selected"], [])
        self.assertFalse(none["dispatch"]["recommend"])
        self.assertEqual(self.engine.step(ts, budget=9)["dispatch"]["budget"], 4)

    def test_step_speed(self):
        """step 1회는 0.2초 이내."""
        stamps = []
        for item in self.engine.nights()[:3]:
            stamps.extend(self.engine.timeline(item["night"])[:5])
        self.assertTrue(stamps)
        worst = 0.0
        for ts in stamps:
            started = time.perf_counter()
            self.engine.step(ts, local={"E": {"dt": -1.0, "wet": True}})
            worst = max(worst, time.perf_counter() - started)
        self.assertLess(worst, 0.2, "step 1회가 0.2초를 넘었다: %.3f초" % worst)

    def test_dispatch_selected_are_candidates(self):
        """선정된 갈래는 반드시 후보이고, 0.5 문턱을 넘는다."""
        if not self.dispatch_ts:
            self.skipTest("경보가 나오는 시각이 없다")
        out = self.engine.step(self.dispatch_ts)
        for arm in out["dispatch"]["selected"]:
            self.assertTrue(out["arms"][arm]["candidate"])
            self.assertGreaterEqual(out["arms"][arm]["p_max"], 0.5)


if __name__ == "__main__":
    unittest.main()
