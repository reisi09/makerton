# car_core 순수 로직 시험(하드웨어 없음).
#   (a) 조향 표 전 경우
#   막대 감지·묶음 확정·위치 계산·살포 판단의 단위 동작
#   (e) 출발 arming(막대 위에서 출발)
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PICO_CAR = os.path.join(HERE, "..", "pico_car")


def _load_core():
    """sys.path를 건드리지 않고 파일에서 바로 읽는다(다른 시험의 main·config를 가리지 않게)."""
    spec = importlib.util.spec_from_file_location("car_core", os.path.join(PICO_CAR, "car_core.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


car_core = _load_core()

BASE = car_core.BASE_SPEED
SOFT = car_core.SOFT_TURN
HARD = car_core.HARD_TURN


class TestSteer(unittest.TestCase):
    """계약 10절 조향 표."""

    def check(self, sensors, last, want_left, want_right, want_side):
        left, right, side = car_core.steer(sensors[0], sensors[1], sensors[2], last)
        self.assertAlmostEqual(left, want_left, msg="센서 %r 좌" % (sensors,))
        self.assertAlmostEqual(right, want_right, msg="센서 %r 우" % (sensors,))
        self.assertEqual(side, want_side, msg="센서 %r 방향" % (sensors,))

    def test_straight_center(self):
        self.check((0, 1, 0), 0, BASE, BASE, 0)
        # 직진은 마지막 방향을 지우지 않는다
        self.check((0, 1, 0), -1, BASE, BASE, -1)
        self.check((0, 1, 0), 1, BASE, BASE, 1)

    def test_soft_left_and_right(self):
        self.check((1, 1, 0), 0, BASE - SOFT, BASE + SOFT, -1)
        self.check((0, 1, 1), 0, BASE + SOFT, BASE - SOFT, 1)

    def test_hard_left_and_right(self):
        self.check((1, 0, 0), 0, BASE - HARD, BASE + HARD, -1)
        self.check((0, 0, 1), 0, BASE + HARD, BASE - HARD, 1)

    def test_bar_crossing_is_straight(self):
        self.check((1, 1, 1), 0, BASE, BASE, 0)
        self.check((1, 1, 1), -1, BASE, BASE, -1)
        self.check((1, 0, 1), 0, BASE, BASE, 0)
        self.check((1, 0, 1), 1, BASE, BASE, 1)

    def test_lost_line_turns_to_last_side(self):
        self.check((0, 0, 0), -1, BASE - HARD, BASE + HARD, -1)
        self.check((0, 0, 0), 1, BASE + HARD, BASE - HARD, 1)
        self.check((0, 0, 0), 0, BASE, BASE, 0)

    def test_all_eight_combinations_in_range(self):
        for mask in range(8):
            sensors = ((mask >> 2) & 1, (mask >> 1) & 1, mask & 1)
            for last in (-1, 0, 1):
                left, right, side = car_core.steer(sensors[0], sensors[1], sensors[2], last)
                self.assertGreaterEqual(left, -1.0, msg="%r %r" % (sensors, last))
                self.assertLessEqual(left, 1.0, msg="%r %r" % (sensors, last))
                self.assertGreaterEqual(right, -1.0, msg="%r %r" % (sensors, last))
                self.assertLessEqual(right, 1.0, msg="%r %r" % (sensors, last))
                self.assertIn(side, (-1, 0, 1))

    def test_left_turn_slows_left_wheel(self):
        left, right, _ = car_core.steer(1, 0, 0, 0)
        self.assertLess(left, right)
        left, right, _ = car_core.steer(0, 0, 1, 0)
        self.assertGreater(left, right)


class TestSteeringLost(unittest.TestCase):
    def test_lost_after_lost_ms(self):
        steering = car_core.Steering(lost_ms=700)
        left, right, lost = steering.update(1, 1, 0, 1000)
        self.assertFalse(lost)
        self.assertLess(left, right)
        # 선을 놓치면 마지막 방향(좌)으로 꺾다가 700ms 뒤에 선다
        left, right, lost = steering.update(0, 0, 0, 1100)
        self.assertFalse(lost)
        self.assertLess(left, right)
        left, right, lost = steering.update(0, 0, 0, 1699)
        self.assertFalse(lost)
        left, right, lost = steering.update(0, 0, 0, 1800)
        self.assertTrue(lost)
        self.assertEqual((left, right), (0.0, 0.0))

    def test_black_resets_lost_timer(self):
        steering = car_core.Steering(lost_ms=700)
        steering.update(0, 0, 0, 0)
        steering.update(0, 0, 0, 600)
        left, right, lost = steering.update(0, 1, 0, 650)     # 선을 다시 찾았다
        self.assertFalse(lost)
        left, right, lost = steering.update(0, 0, 0, 700)     # 타이머는 700부터 다시 센다
        self.assertFalse(lost)
        left, right, lost = steering.update(0, 0, 0, 1399)
        self.assertFalse(lost)
        left, right, lost = steering.update(0, 0, 0, 1400)
        self.assertTrue(lost)

    def test_reset_clears(self):
        steering = car_core.Steering(lost_ms=100)
        steering.update(0, 0, 0, 0)
        _, _, lost = steering.update(0, 0, 0, 200)
        self.assertTrue(lost)
        steering.reset()
        _, _, lost = steering.update(0, 0, 0, 300)
        self.assertFalse(lost)


class TestBarDetector(unittest.TestCase):
    def test_needs_two_samples(self):
        bars = car_core.BarDetector(confirm=2)
        self.assertFalse(bars.update(1, 1, 1))
        self.assertTrue(bars.update(1, 1, 1))

    def test_one_bar_while_black(self):
        bars = car_core.BarDetector(confirm=2)
        found = [bars.update(1, 1, 1) for _ in range(10)]
        self.assertEqual(found.count(True), 1)

    def test_white_ends_bar(self):
        bars = car_core.BarDetector(confirm=2)
        bars.update(1, 1, 1)
        bars.update(1, 1, 1)
        self.assertFalse(bars.update(1, 0, 1))       # 하나라도 흰색이면 끝
        self.assertFalse(bars.update(1, 1, 1))       # 카운터가 다시 1부터
        self.assertTrue(bars.update(1, 1, 1))

    def test_single_black_sample_is_noise(self):
        bars = car_core.BarDetector(confirm=2)
        self.assertFalse(bars.update(1, 1, 1))
        self.assertFalse(bars.update(1, 1, 0))
        self.assertFalse(bars.update(1, 1, 1))
        self.assertTrue(bars.update(1, 1, 1))


class TestGroupClassifier(unittest.TestCase):
    def test_three_bars_one_group(self):
        groups = car_core.GroupClassifier(gap_ms=700)
        for t in (0, 100, 200):
            groups.bar(t)
        self.assertEqual(groups.pending(), 3)
        self.assertIsNone(groups.tick(899))
        self.assertEqual(groups.tick(900), 3)        # 마지막 막대 + 700
        self.assertIsNone(groups.tick(1000))         # 확정은 한 번만

    def test_two_bars(self):
        groups = car_core.GroupClassifier(gap_ms=700)
        groups.bar(0)
        groups.bar(100)
        self.assertEqual(groups.tick(800), 2)

    def test_single_bar(self):
        groups = car_core.GroupClassifier(gap_ms=700)
        groups.bar(0)
        self.assertEqual(groups.tick(700), 1)

    def test_gap_splits_group(self):
        groups = car_core.GroupClassifier(gap_ms=700)
        groups.bar(0)
        self.assertEqual(groups.tick(700), 1)
        groups.bar(1000)
        self.assertEqual(groups.tick(1700), 1)

    def test_kind_of(self):
        self.assertEqual(car_core.kind_of(1), car_core.KIND_SEG)
        self.assertEqual(car_core.kind_of(2), car_core.KIND_END)
        self.assertEqual(car_core.kind_of(3), car_core.KIND_HOME)
        self.assertEqual(car_core.kind_of(5), car_core.KIND_HOME)


class TestPosition(unittest.TestCase):
    def setUp(self):
        self.pos = car_core.Position()
        self.pos.start()          # 출발: 무장 전

    def armed(self):
        self.pos.observe(0, 1, 0)

    def test_start_is_unarmed_until_white(self):
        self.assertFalse(self.pos.bar())
        self.pos.observe(1, 1, 1)
        self.assertFalse(self.pos.bar())
        self.armed()
        self.assertTrue(self.pos.bar())

    def test_up_leg_cells(self):
        self.armed()
        kind, cell, warn = self.pos.group(2)          # END 1
        self.assertEqual((kind, cell, warn), (car_core.KIND_END, "U1", False))
        self.assertEqual(self.pos.leg, 1)
        for want in ("U2", "U3", "U4"):
            kind, cell, warn = self.pos.group(1)
            self.assertEqual((kind, cell, warn), (car_core.KIND_SEG, want, False))

    def test_up_leg_clamps_with_warning(self):
        self.armed()
        self.pos.group(2)
        for _ in range(4):
            self.pos.group(1)
        kind, cell, warn = self.pos.group(1)
        self.assertEqual(cell, "U4")
        self.assertTrue(warn)                         # 4를 넘으면 고정 + 경고

    def test_east_turn_no_cell(self):
        self.armed()
        self.pos.group(2)
        kind, cell, warn = self.pos.group(2)          # END 2: 회차
        self.assertEqual(cell, None)
        self.assertEqual(self.pos.leg, 2)
        self.assertEqual(self.pos.seg, 0)

    def test_down_leg_cells(self):
        self.armed()
        self.pos.group(2)
        self.pos.group(2)
        kind, cell, warn = self.pos.group(2)          # END 3
        self.assertEqual(cell, "D4")
        self.assertEqual(self.pos.leg, 3)
        for want in ("D3", "D2", "D1"):
            kind, cell, warn = self.pos.group(1)
            self.assertEqual(cell, want)

    def test_down_leg_clamps_with_warning(self):
        self.armed()
        for _ in range(3):
            self.pos.group(2)
        for _ in range(4):
            self.pos.group(1)
        kind, cell, warn = self.pos.group(1)
        self.assertEqual(cell, "D1")
        self.assertTrue(warn)

    def test_end_resets_seg_count(self):
        self.armed()
        self.pos.group(2)
        self.pos.group(1)
        self.pos.group(1)
        self.assertEqual(self.pos.seg, 2)
        self.pos.group(2)                             # END가 오면 다시 맞춘다
        self.assertEqual(self.pos.seg, 0)

    def test_seg_without_end_does_not_crash(self):
        self.armed()
        kind, cell, warn = self.pos.group(1)          # END를 놓친 상태
        self.assertEqual(kind, car_core.KIND_SEG)
        self.assertIsNone(cell)

    def test_home_finishes(self):
        self.armed()
        self.pos.group(2)
        self.pos.group(1)
        kind, cell, warn = self.pos.group(3)
        self.assertEqual(kind, car_core.KIND_HOME)
        self.assertTrue(self.pos.done)
        self.assertIsNone(self.pos.cell)
        self.assertEqual(self.pos.leg, 0)

    def test_unarmed_group_ignored(self):
        kind, cell, warn = self.pos.group(2)
        self.assertEqual(kind, None)
        self.assertEqual(self.pos.leg, 0)             # 출발 막대는 세지 않는다

    def test_state_dict(self):
        self.armed()
        self.pos.group(2)
        self.assertEqual(self.pos.state(), {"leg": 1, "seg": 0, "cell": "U1"})


class TestSalter(unittest.TestCase):
    def test_only_planned_cell(self):
        salter = car_core.Salter(salt_ms=600)
        salter.set_plan("P1", ["U2", "D3"])
        self.assertFalse(salter.enter("U1", 1000))
        self.assertTrue(salter.enter("U2", 1000))
        self.assertFalse(salter.enter("U3", 1000))

    def test_once_per_cell(self):
        salter = car_core.Salter(salt_ms=600)
        salter.set_plan("P1", ["U2"])
        self.assertTrue(salter.enter("U2", 0))
        self.assertTrue(salter.tick(600))
        self.assertFalse(salter.enter("U2", 5000))
        self.assertEqual(salter.salted, ["U2"])

    def test_close_time(self):
        salter = car_core.Salter(salt_ms=600)
        salter.set_plan("P1", ["U2"])
        salter.enter("U2", 1000)
        self.assertTrue(salter.is_open())
        self.assertFalse(salter.tick(1599))
        self.assertTrue(salter.tick(1600))
        self.assertFalse(salter.is_open())
        self.assertFalse(salter.tick(1700))           # 닫기는 한 번만

    def test_new_plan_resets_history(self):
        salter = car_core.Salter()
        salter.set_plan("P1", ["U2"])
        salter.enter("U2", 0)
        salter.set_plan("P1", ["U2"])                 # 같은 계획 재전송: 이력 유지
        self.assertEqual(salter.salted, ["U2"])
        salter.set_plan("P2", ["U2"])                 # 새 계획: 새 주행
        self.assertEqual(salter.salted, [])

    def test_none_cell(self):
        salter = car_core.Salter()
        salter.set_plan("P1", ["U2"])
        self.assertFalse(salter.enter(None, 0))


class TestLoopOrder(unittest.TestCase):
    def test_contract_order(self):
        self.assertEqual(car_core.LOOP,
                         ("U1", "U2", "U3", "U4", "D4", "D3", "D2", "D1"))
        self.assertEqual(car_core.loop_index("U4"), 3)
        self.assertEqual(car_core.loop_index("D4"), 4)
        self.assertIsNone(car_core.loop_index("X1"))

    def test_ticks_diff_wraps(self):
        start = 0x3FFFFFF0
        self.assertEqual(car_core.ticks_diff(start + 20, start), 20)
        self.assertEqual(car_core.ticks_diff(start, start + 20), -20)


if __name__ == "__main__":
    unittest.main()
