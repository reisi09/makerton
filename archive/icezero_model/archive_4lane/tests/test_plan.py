"""계획 계산(plan.py) 시험 — 계약 4절. 하드웨어·네트워크 없이 돈다."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "server")
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import plan  # noqa: E402


class ScoreTest(unittest.TestCase):
    def test_empty_reports_still_have_structure_and_shade(self):
        # 계약 4절: 교량은 구조물 1.5, 그늘은 1.0 이 제보와 무관하게 붙는다.
        rows = plan.plan_rows()
        self.assertEqual(set(rows), set(plan.LOOP))
        for cell in ("U1", "U4", "D1", "D4"):
            self.assertEqual(rows[cell]["score"], 0.0)
            self.assertEqual(rows[cell]["risk"], "risk1")
        self.assertEqual(rows["U2"]["score"], 1.5)
        self.assertEqual(rows["U3"]["score"], 1.0)
        self.assertEqual(rows["U2"]["reasons"], [plan.REASON_STRUCT])
        self.assertEqual(rows["U3"]["reasons"], [plan.REASON_SHADE])

    def test_report_adds_three(self):
        rows = plan.plan_rows(confirmed=["D1"])
        self.assertEqual(rows["D1"]["score"], 3.0)
        self.assertIn(plan.REASON_REPORT, rows["D1"]["reasons"])
        self.assertEqual(rows["D1"]["risk"], "risk3")
        self.assertEqual(rows["U1"]["score"], 0.0)

    def test_bridge_structure_and_watch(self):
        rows = plan.plan_rows(bridge_warn=True)
        # 교량 = 구조물 1.5 + 관측 주의 2.0 = 3.5
        self.assertEqual(rows["U2"]["score"], 3.5)
        self.assertEqual(rows["D2"]["score"], 3.5)
        self.assertIn(plan.REASON_STRUCT, rows["U2"]["reasons"])
        self.assertIn(plan.REASON_WATCH, rows["U2"]["reasons"])
        self.assertEqual(rows["U2"]["risk"], "risk3")
        # 그늘은 1.0
        self.assertEqual(rows["U3"]["score"], 1.0)
        self.assertEqual(rows["D3"]["risk"], "risk2")
        # 일반 칸은 0
        self.assertEqual(rows["U1"]["score"], 0.0)
        self.assertEqual(rows["U4"]["score"], 0.0)

    def test_bridge_without_watch(self):
        rows = plan.plan_rows(bridge_warn=False)
        self.assertEqual(rows["U2"]["score"], 1.5)
        self.assertEqual(rows["U2"]["risk"], "risk2")

    def test_manual_watch_overrides_board(self):
        on = plan.plan_rows(bridge_warn=False, manual_watch=True)
        self.assertEqual(on["U2"]["score"], 3.5)
        off = plan.plan_rows(bridge_warn=True, manual_watch=False)
        self.assertEqual(off["U2"]["score"], 1.5)
        follow = plan.plan_rows(bridge_warn=True, manual_watch=None)
        self.assertEqual(follow["U2"]["score"], 3.5)

    def test_report_plus_shade_and_bridge(self):
        rows = plan.plan_rows(confirmed=["U2", "D3"], bridge_warn=True)
        self.assertEqual(rows["U2"]["score"], 6.5)   # 3.0 + 1.5 + 2.0
        self.assertEqual(rows["D3"]["score"], 4.0)   # 3.0 + 1.0

    def test_duplicate_reports_do_not_stack(self):
        rows = plan.plan_rows(confirmed=["U1", "U1", "u1"])
        self.assertEqual(rows["U1"]["score"], 3.0)

    def test_risk_bucket_boundaries(self):
        self.assertEqual(plan.risk_bucket(0), "risk1")
        self.assertEqual(plan.risk_bucket(-1), "risk1")
        self.assertEqual(plan.risk_bucket(0.01), "risk2")
        self.assertEqual(plan.risk_bucket(2.49), "risk2")
        self.assertEqual(plan.risk_bucket(2.5), "risk3")
        self.assertEqual(plan.risk_bucket(6.5), "risk3")


class ProposalTest(unittest.TestCase):
    def test_zero_score_cells_excluded(self):
        rows = plan.plan_rows(confirmed=["U1"])
        proposal = plan.propose(rows, 8)
        self.assertEqual(proposal["cells"], ["U1", "U2", "U3", "D3", "D2"])
        for cell in ("U4", "D4", "D1"):
            self.assertNotIn(cell, proposal["cells"])

    def test_loop_order(self):
        rows = plan.plan_rows(confirmed=["D1", "U4", "U1"])
        proposal = plan.propose(rows, 3)
        # 점수는 모두 3.0 → 동점은 루프 순서, 실행 순서도 루프 순서
        self.assertEqual(proposal["cells"], ["U1", "U4", "D1"])
        self.assertEqual(proposal["order"], proposal["cells"])

    def test_budget_cut_takes_highest_score(self):
        rows = plan.plan_rows(confirmed=["U1", "D1"], bridge_warn=True)
        proposal = plan.propose(rows, 2)
        # 3.5(U2) 3.5(D2) 3.0(U1) 3.0(D1) 중 앞 두 개 → 다시 루프 순서로
        self.assertEqual(proposal["cells"], ["U2", "D2"])
        self.assertEqual(proposal["budget"], 2)

    def test_budget_zero(self):
        rows = plan.plan_rows(confirmed=["U1"])
        proposal = plan.propose(rows, 0)
        self.assertEqual(proposal["cells"], [])
        self.assertEqual(proposal["budget"], 0)

    def test_budget_clamped(self):
        self.assertEqual(plan.clamp_budget(-3), 0)
        self.assertEqual(plan.clamp_budget(99), 8)
        self.assertEqual(plan.clamp_budget(3), 3)
        self.assertEqual(plan.clamp_budget("4"), 4)
        self.assertEqual(plan.clamp_budget("많이"), plan.default_budget())

    def test_budget_env_default(self):
        old = os.environ.get("BUDGET_DEFAULT")
        try:
            os.environ["BUDGET_DEFAULT"] = "6"
            self.assertEqual(plan.default_budget(), 6)
            os.environ["BUDGET_DEFAULT"] = "이상한값"
            self.assertEqual(plan.default_budget(), plan.BUDGET_FALLBACK)
            os.environ["BUDGET_DEFAULT"] = "99"
            self.assertEqual(plan.default_budget(), 8)
        finally:
            if old is None:
                os.environ.pop("BUDGET_DEFAULT", None)
            else:
                os.environ["BUDGET_DEFAULT"] = old

    def test_scores_and_reasons_cover_eight_cells(self):
        rows = plan.plan_rows(confirmed=["U3", "D4"])
        proposal = plan.propose(rows, 4)
        self.assertEqual(len(proposal["scores"]), 8)
        self.assertEqual(len(proposal["reasons"]), 8)
        self.assertEqual(set(proposal["scores"]), set(plan.CELLS))
        self.assertEqual(proposal["reasons"]["U3"], [plan.REASON_REPORT, plan.REASON_SHADE])

    def test_make_plan(self):
        proposal = plan.make_plan(confirmed=["U3"], budget=2)
        # 4.0(U3) + 1.5(U2·D2) 중 상위 두 칸 → 다시 루프 순서
        self.assertEqual(proposal["cells"], ["U2", "U3"])
        self.assertEqual(proposal["budget"], 2)
        self.assertEqual(proposal["scores"]["U2"], 1.5)
        self.assertEqual(proposal["scores"]["U3"], 4.0)


class SaltedTest(unittest.TestCase):
    def test_salted_cell_gets_zero(self):
        rows = plan.plan_rows(confirmed=["U2"], bridge_warn=True, salted=["U2"])
        self.assertEqual(rows["U2"]["score"], 0.0)
        self.assertTrue(rows["U2"]["salted"])
        self.assertEqual(rows["U2"]["reasons"], [plan.REASON_SALTED])
        self.assertEqual(rows["U2"]["risk"], "risk1")

    def test_salted_cell_not_in_proposal(self):
        proposal = plan.make_plan(confirmed=["U2", "D3"], bridge_warn=True, salted=["U2"], budget=4)
        self.assertNotIn("U2", proposal["cells"])
        self.assertEqual(proposal["cells"], ["U3", "D3", "D2"])

    def test_salted_cells_helper_respects_newer_report(self):
        reports = [{"cells": ["U2"], "at": 100.0}]
        self.assertEqual(plan.salted_cells(reports, {"U2": 200.0}), {"U2"})
        reports.append({"cells": ["U2"], "at": 300.0})
        self.assertEqual(plan.salted_cells(reports, {"U2": 200.0}), set())
        # 다른 칸 제보로는 풀리지 않는다
        reports = [{"cells": ["U2"], "at": 100.0}, {"cells": ["D3"], "at": 300.0}]
        self.assertEqual(plan.salted_cells(reports, {"U2": 200.0}), {"U2"})

    def test_newer_report_restores_score(self):
        reports = [{"cells": ["U2"], "at": 100.0}, {"cells": ["U2"], "at": 300.0}]
        salted = plan.salted_cells(reports, {"U2": 200.0})
        rows = plan.plan_rows(confirmed=plan.confirmed_cells(reports), salted=salted)
        self.assertFalse(rows["U2"]["salted"])
        self.assertEqual(rows["U2"]["score"], 4.5)  # 제보 3.0 + 구조물 1.5


class SaltedReturnTest(unittest.TestCase):
    def test_re_report_after_salt_gets_full_score_again(self):
        reports = [{"cells": ["U2"], "at": 300.0}]
        salted = plan.salted_cells(reports, {"U2": 200.0})
        rows = plan.plan_rows(confirmed=plan.confirmed_cells(reports), bridge_warn=True, salted=salted)
        self.assertFalse(rows["U2"]["salted"])
        self.assertEqual(rows["U2"]["score"], 6.5)  # 3.0 + 1.5 + 2.0


if __name__ == "__main__":
    unittest.main()
