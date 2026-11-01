# main.py 상태기계 시험: 가짜 machine·network·socket으로 한 바퀴를 시간과 함께 흘린다.
#   (b) 한 바퀴 이벤트 시퀀스(HOME→END→SEG×3→END→END→SEG×3→END→HOME) → 칸 U1..U4,(회차),D4..D1,DONE
#   (c) SEG 하나 누락 시 다음 END에서 재동기화
#   (d) 계획 칸만 1회씩 살포
#   (e) arming(막대 위에서 출발)
#   (f) plan → go → marker → salt → done UDP 메시지
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PICO_CAR = os.path.join(HERE, "..", "pico_car")
if HERE not in sys.path:
    sys.path.append(HERE)      # 뒤에 붙인다: 이 폴더의 이름이 다른 시험의 import를 가리지 않게

import fake_micropython  # noqa: E402

LINE_L, LINE_C, LINE_R = 18, 19, 20
BUTTON = 21
SERVO_PIN = 16
PWMA, PWMB = 12, 15

# 시험용 타임라인(ms). 묶음 사이는 GROUP_GAP_MS(700)보다 넉넉히 벌린다.
# (HOME에서 출발) → END → SEG×3 → END → (동쪽 회차) → END → SEG×3 → END → (서쪽 회차) → HOME
LAP = [
    ("end", 2000), ("end", 2100),
    ("seg", 3000), ("seg", 4000), ("seg", 5000),
    ("end", 6000), ("end", 6100),
    ("end", 8000), ("end", 8100),
    ("seg", 9100), ("seg", 10100), ("seg", 11100),
    ("end", 12100), ("end", 12200),
    ("home", 13200), ("home", 13300), ("home", 13400),
]
LAP_END = 15000
LAP_CELLS = ["U1", "U2", "U3", "U4", "D4", "D3", "D2", "D1"]

_MODS = {}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module          # main.py의 import car_core/config가 이 객체를 찾는다
    spec.loader.exec_module(module)
    return module


def setUpModule():
    world, fakes = fake_micropython.build()
    names = ("config", "car_core", "main", "machine", "network", "socket")
    saved = dict((k, sys.modules.get(k)) for k in names)
    for name in ("config", "car_core", "main"):
        sys.modules.pop(name, None)
    sys.modules.update(fakes)
    try:
        config = _load("config", os.path.join(PICO_CAR, "config.py"))
        car_core = _load("car_core", os.path.join(PICO_CAR, "car_core.py"))
        main = _load("main", os.path.join(PICO_CAR, "main.py"))
    finally:
        for name in names:
            if saved[name] is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved[name]
    _MODS.update({"config": config, "car_core": car_core, "main": main, "world": world})


def tearDownModule():
    fake_micropython.WORLD = None
    _MODS.clear()


def make_cfg(**over):
    """pico_car/config.py 값을 그대로 복사하고 시험용으로 일부만 바꾼다."""
    src = _MODS["config"]
    cfg = types.SimpleNamespace()
    for key in dir(src):
        if key.isupper():
            setattr(cfg, key, getattr(src, key))
    for key, value in over.items():
        setattr(cfg, key, value)
    return cfg


class Sim(unittest.TestCase):
    """가짜 세계 + 차 한 대. step(t)가 world.now와 loop_once를 같은 시각으로 맞춘다."""

    def setUp(self):
        self.world = fake_micropython.World()
        fake_micropython.WORLD = self.world
        self.tmp = tempfile.mkdtemp(prefix="icezero_car_")
        self.cfg = make_cfg(PLAN_PATH=os.path.join(self.tmp, "plan.json"))
        self.pipe_r, self.pipe_w = os.pipe()
        self.stdin = fake_micropython.PipeStdin(self.pipe_r)   # 장치의 USB CDC처럼 버퍼링 없이
        self.car = None
        self.now = 0
        self.boot_log = ""

    def tearDown(self):
        self.stdin.close()
        os.close(self.pipe_w)

    # ── 준비 ──
    def make_car(self, boot=False, **cfg_over):
        for key, value in cfg_over.items():
            setattr(self.cfg, key, value)
        out = io.StringIO()
        car = _MODS["main"].Car(self.cfg, stdin=self.stdin)
        if boot:
            with contextlib.redirect_stdout(out):
                car.boot()
        self.car = car
        self.boot_log = out.getvalue()
        return car

    def send(self, msg):
        self.world.inbox.append(json.dumps(msg).encode())

    def build_lap(self, skip=None, extra=()):
        """한 바퀴 표식 타임라인. skip 시각의 막대는 놓친 것으로, extra는 더 놓는다."""
        w = self.world
        w.bar(0, 500)                       # 출발할 때 차고지 막대 위에 서 있다
        for _, t in LAP:
            if t != skip:
                w.bar(t)
        for t in extra:
            w.bar(t)

    # ── 실행 ──
    def step(self, t):
        self.world.now = t
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.car.loop_once(t)
        self.now = t
        return out.getvalue()

    def run_until(self, end, step_ms=5):
        t = self.now
        while t < end:
            t += step_ms
            self.step(t)

    def start(self, plan=("U2", "D3"), go_at=300, boot=False, **cfg_over):
        self.make_car(boot=boot, **cfg_over)
        self.send({"t": "plan", "seq": 1, "plan_id": "P1", "cells": list(plan)})
        self.step(0)
        self.send({"t": "go", "seq": 2, "plan_id": "P1"})
        self.step(go_at)
        return self.car

    def run_lap(self, plan=("U2", "D3"), skip=None, extra=(), **cfg_over):
        self.build_lap(skip=skip, extra=extra)
        self.start(plan=plan, **cfg_over)
        self.run_until(LAP_END)

    # ── 조회 ──
    def sent_messages(self):
        """차가 보낸 메시지 + 보낸 시각(_t)."""
        out = []
        for entry in self.world.sent:
            try:
                msg = json.loads(entry["data"].decode())
            except ValueError:
                continue
            msg["_t"] = entry["t"]
            out.append(msg)
        return out

    def events(self, name=None):
        return [m for m in self.world.events() if name is None or m.get("e") == name]

    def hellos(self):
        return [m for m in self.sent_messages() if m.get("t") == "hello"]


class TestBoot(Sim):
    def test_boot_summary_has_line_sensor_guide(self):
        self.make_car(boot=True)
        self.assertIn("라인센서 값 확인", self.boot_log)
        self.assertIn(self.cfg.CAR_ID, self.boot_log)
        self.assertNotIn(self.cfg.WIFI_PASSWORD, self.boot_log)   # 비밀번호는 찍지 않는다
        self.assertEqual(self.world.servo_angle(SERVO_PIN), self.cfg.SERVO_CLOSED_DEG)

    def test_servo_duty_formula(self):
        self.make_car()
        self.car.set_servo(90)
        self.assertEqual(self.world.duties[SERVO_PIN],
                         1638 + (8192 - 1638) * 90 // 180)

    def test_tb6612_direction_pins(self):
        self.make_car()
        self.car.motors.set(0.5, -0.25)
        self.assertEqual(self.world.outputs[10], 1)       # AIN1 앞으로
        self.assertEqual(self.world.outputs[11], 0)
        self.assertGreater(self.world.duties[PWMA], 0)
        self.assertEqual(self.world.outputs[13], 0)       # BIN1 뒤로
        self.assertEqual(self.world.outputs[14], 1)
        self.assertGreater(self.world.duties[PWMB], 0)
        self.car.motors.stop()
        self.assertEqual(self.world.duties[PWMA], 0)
        self.assertEqual(self.world.duties[PWMB], 0)

    def test_pwm2_driver_writes_both_pins(self):
        self.make_car(DRIVER="pwm2")
        self.car.motors.set(0.5, -0.25)
        self.assertGreater(self.world.duties[10], 0)      # 왼쪽 IN1
        self.assertEqual(self.world.duties[11], 0)
        self.assertEqual(self.world.duties[13], 0)
        self.assertGreater(self.world.duties[14], 0)      # 오른쪽 IN2
        self.car.motors.stop()
        self.assertEqual(self.world.duties[10], 0)
        self.assertEqual(self.world.duties[14], 0)

    def test_invert_swaps_direction(self):
        self.make_car(LEFT_INVERT=True)
        self.car.motors.set(0.5, 0.5)
        self.assertEqual(self.world.outputs[10], 0)       # 왼쪽: 뒤로
        self.assertEqual(self.world.outputs[11], 1)
        self.assertEqual(self.world.outputs[13], 1)       # 오른쪽: 앞으로


class TestFullLap(Sim):
    """(b) (d) (e) (f): 한 바퀴를 흘려 칸 순서·살포·UDP 메시지를 본다."""

    def test_cell_sequence_and_done(self):
        self.run_lap()
        self.assertEqual(self.world.cells_marked(), LAP_CELLS)
        self.assertEqual(self.car.state, "DONE")
        self.assertTrue(self.car.pos.done)

    def test_only_planned_cells_sprayed_once(self):
        self.run_lap(plan=("U2", "D3"))
        self.assertEqual([m.get("cell") for m in self.events("salt")], ["U2", "D3"])
        self.assertEqual(self.car.salter.salted, ["U2", "D3"])

    def test_other_plan_sprays_that_cell(self):
        self.run_lap(plan=("D1",))
        self.assertEqual([m.get("cell") for m in self.events("salt")], ["D1"])

    def test_servo_opens_then_closes(self):
        self.run_lap(plan=("U2",))
        open_duty = _MODS["main"].servo_duty(self.cfg.SERVO_OPEN_DEG)
        closed_duty = _MODS["main"].servo_duty(self.cfg.SERVO_CLOSED_DEG)
        writes = [entry for entry in self.world.duty_log if entry[1] == SERVO_PIN]
        opened = [entry for entry in writes if entry[2] == open_duty]
        self.assertEqual(len(opened), 1)                  # 칸당 1회
        later = [entry for entry in writes if entry[0] >= opened[0][0] + self.cfg.SALT_MS]
        self.assertEqual(later[0][2], closed_duty)        # SALT_MS 뒤에 닫힌다
        self.assertEqual(self.world.servo_angle(SERVO_PIN), self.cfg.SERVO_CLOSED_DEG)

    def test_udp_messages(self):
        self.run_lap(plan=("U2", "D3"))
        messages = self.sent_messages()
        acks = [m.get("seq") for m in messages if m.get("t") == "ack"]
        self.assertEqual(acks[:2], [1, 2])
        names = self.world.event_names()
        self.assertIn("start", names)
        self.assertIn("marker", names)
        self.assertIn("salt", names)
        self.assertIn("done", names)
        self.assertEqual(names[0], "start")                # go 뒤 첫 이벤트
        running = [m for m in self.hellos() if m.get("st") == "RUN"]
        self.assertTrue(running)
        sample = running[0]
        self.assertEqual(sample.get("id"), self.cfg.CAR_ID)
        self.assertEqual(sample.get("plan"), "P1")
        self.assertEqual(sample.get("cells"), ["U2", "D3"])
        self.assertIn("pos", sample)
        self.assertIn("dist", sample)
        self.assertTrue([m for m in self.hellos() if m.get("st") == "DONE"])
        self.assertTrue([m for m in self.hellos() if m.get("salted")])
        self.assertEqual(self.world.sent[0]["addr"][1], self.cfg.SERVER_PORT)

    def test_hello_period_one_second(self):
        self.run_lap(plan=("U2",))
        times = [m["_t"] for m in self.hellos()]
        self.assertGreaterEqual(len(times), 10)
        gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
        self.assertTrue(all(gap == 1000 for gap in gaps), gaps)

    def test_start_bar_ignored_while_unarmed(self):
        """(e) 막대 위에서 출발: 첫 검정은 세지 않고, 흰색을 본 뒤부터 센다."""
        self.build_lap()
        self.start(plan=("U2",))
        self.assertEqual(self.car.state, "RUN")
        self.assertFalse(self.car.pos.armed)              # 아직 출발 막대 위
        self.run_until(500)
        self.assertEqual(self.world.cells_marked(), [])   # 출발 막대는 묶음이 되지 않는다
        self.assertTrue(self.car.pos.armed)               # 흰색(유도선)을 봤다
        self.assertEqual(self.car.state, "RUN")
        self.run_until(2900)
        self.assertEqual(self.world.cells_marked(), ["U1"])

    def test_lost_line_stops_after_lost_ms(self):
        self.build_lap()
        self.start(plan=("U2",))
        self.world.line_off(700)                          # 유도선을 완전히 놓쳤다
        self.run_until(1350)
        self.assertEqual(self.car.state, "RUN")           # 아직 LOST_MS 전
        self.run_until(1500)
        self.assertEqual(self.car.state, "LOST")
        self.assertIn("lost", self.world.event_names())
        self.assertEqual(self.world.duties[PWMA], 0)
        self.assertEqual(self.world.duties[PWMB], 0)


class TestMissingSeg(Sim):
    """(c) SEG 하나를 놓쳐도 다음 END에서 다시 맞춘다."""

    def test_resync_at_next_end(self):
        self.run_lap(plan=("U2",), skip=5000)
        self.assertEqual(self.world.cells_marked(), ["U1", "U2", "U3"] + LAP_CELLS[4:])
        self.assertEqual(self.car.state, "DONE")

    def test_extra_seg_clamps_and_warns(self):
        # 상행에 SEG를 하나 더 놓는다(U1→U2→U3→U4→넘침). 칸은 U4에 고정되고 경고가 나간다.
        w = self.world
        w.bar(0, 500)                              # 출발(차고지 막대)
        w.bar(2000), w.bar(2100)                   # END 1 → U1
        for t in (3000, 4000, 5000, 6000):
            w.bar(t)                               # SEG 4개 → 네 번째가 넘침
        w.bar(8000), w.bar(8100)                   # END 2 → 회차
        w.bar(10000), w.bar(10100)                 # END 3 → D4
        for t in (11100, 12100, 13100):
            w.bar(t)                               # D3, D2, D1
        w.bar(14300), w.bar(14400)                 # END 4
        w.bar(15400), w.bar(15500), w.bar(15600)   # HOME
        self.start(plan=("U2",))
        self.run_until(6800)
        self.assertIn("warn", self.world.event_names())
        self.assertEqual(self.car.pos.cell, "U4")
        # 네 번째 SEG는 칸을 바꾸지 않는다(마지막 칸 고정 + 경고)
        self.assertEqual(self.world.cells_marked()[:4], ["U1", "U2", "U3", "U4"])
        self.run_until(17000)
        self.assertEqual(self.car.state, "DONE")


class TestCommands(Sim):
    def test_plan_rejected_while_running(self):
        self.build_lap()
        self.start()
        self.send({"t": "plan", "seq": 3, "plan_id": "P2", "cells": ["D1"]})
        self.step(400)
        self.assertEqual(self.car.plan_id, "P1")
        self.assertEqual(self.car.cells, ["U2", "D3"])
        self.assertIn("warn", self.world.event_names())

    def test_duplicate_seq_runs_once(self):
        self.build_lap()
        self.make_car()
        packet = {"t": "plan", "seq": 1, "plan_id": "P1", "cells": ["U2"]}
        self.send(packet)
        self.step(0)
        self.send(packet)                                  # 재전송
        self.step(10)
        acks = [m["seq"] for m in self.sent_messages() if m.get("t") == "ack"]
        self.assertEqual(acks, [1, 1])                     # ack는 매번 보낸다
        self.send({"t": "go", "seq": 2, "plan_id": "P1"})
        self.step(20)
        self.send({"t": "go", "seq": 2, "plan_id": "P1"})   # 재전송
        self.step(30)
        self.assertEqual(self.world.event_names().count("start"), 1)

    def test_go_with_wrong_plan_id_rejected(self):
        self.build_lap()
        self.make_car()
        self.send({"t": "plan", "seq": 1, "plan_id": "P1", "cells": ["U2"]})
        self.step(0)
        self.send({"t": "go", "seq": 2, "plan_id": "P9"})
        self.step(10)
        self.assertEqual(self.car.state, "IDLE")
        self.assertIn("warn", self.world.event_names())

    def test_stop_resume_abort(self):
        self.build_lap()
        self.start()
        self.assertEqual(self.car.state, "RUN")
        self.send({"t": "stop", "seq": 3})
        self.step(400)
        self.assertEqual(self.car.state, "HOLD_CMD")
        self.assertEqual(self.world.duties[PWMA], 0)
        self.assertIn("estop", self.world.event_names())
        self.send({"t": "resume", "seq": 4})
        self.step(410)
        self.assertEqual(self.car.state, "RUN")
        self.assertIn("resume", self.world.event_names())
        self.send({"t": "abort", "seq": 5})
        self.step(420)
        self.assertEqual(self.car.state, "IDLE")
        self.assertEqual(self.car.pos.leg, 0)

    def test_stop_holds_even_in_idle(self):
        self.build_lap()
        self.make_car()
        self.send({"t": "plan", "seq": 1, "plan_id": "P1", "cells": ["U2"]})
        self.step(0)
        self.send({"t": "stop", "seq": 2})          # 계약 8절: stop은 언제나 HOLD_CMD
        self.step(10)
        self.assertEqual(self.car.state, "HOLD_CMD")
        self.send({"t": "go", "seq": 3, "plan_id": "P1"})
        self.step(20)
        self.assertEqual(self.car.state, "HOLD_CMD")   # 풀기 전에는 출발하지 않는다
        self.send({"t": "resume", "seq": 4})
        self.step(30)
        self.assertEqual(self.car.state, "RUN")

    def test_resume_ignored_outside_hold(self):
        self.build_lap()
        self.start()
        self.send({"t": "resume", "seq": 3})
        self.step(400)
        self.assertEqual(self.car.state, "RUN")             # RUN에서는 resume 무시
        self.assertNotIn("resume", self.world.event_names())

    def test_token_required_when_configured(self):
        self.cfg.TOKEN = "team-secret"
        self.build_lap()
        self.make_car()
        self.send({"t": "plan", "seq": 1, "plan_id": "P1", "cells": ["U2"]})
        self.step(0)
        self.assertIsNone(self.car.plan_id)                 # 토큰 없음 → 거절
        self.send({"t": "plan", "seq": 2, "plan_id": "P1", "cells": ["U2"],
                   "tok": "team-secret"})
        self.step(10)
        self.assertEqual(self.car.plan_id, "P1")
        self.assertEqual(self.hellos()[0].get("tok"), "team-secret")   # 나가는 메시지에도

    def test_offline_boot_and_button_start(self):
        path = os.path.join(self.tmp, "plan.json")
        with open(path, "w") as f:
            json.dump({"plan_id": "P7", "cells": ["U3"]}, f)
        self.build_lap()
        self.make_car(boot=True)                            # Wi-Fi 없이 plan.json만 읽는다
        self.assertEqual(self.car.plan_id, "P7")
        self.assertEqual(self.car.cells, ["U3"])
        self.world.wifi_connected = False
        self.world.at(100, BUTTON, 0)                       # 100ms에 누름
        self.world.at(200, BUTTON, 1)
        self.run_until(120)
        self.assertEqual(self.car.state, "IDLE")            # 디바운스 중
        self.run_until(200)
        self.assertEqual(self.car.state, "RUN")
        self.world.at(400, BUTTON, 0)
        self.world.at(500, BUTTON, 1)
        self.run_until(520)
        self.assertEqual(self.car.state, "HOLD_CMD")        # 버튼 비상 정지
        self.world.at(700, BUTTON, 0)
        self.world.at(800, BUTTON, 1)
        self.run_until(820)
        self.assertEqual(self.car.state, "RUN")             # 버튼 재개

    def test_button_without_plan_runs_test_lap(self):
        """계획이 없으면 버튼은 시험 주행(살포 없이 한 바퀴)이다."""
        self.build_lap()
        self.make_car()
        self.world.at(100, BUTTON, 0)
        self.world.at(200, BUTTON, 1)
        self.run_until(300)
        self.assertEqual(self.car.state, "RUN")
        self.assertTrue(self.car.test_run)
        self.assertIsNone(self.car.plan_id)
        self.run_until(LAP_END)
        self.assertEqual(self.car.state, "DONE")
        self.assertEqual(self.world.cells_marked(), LAP_CELLS)
        self.assertEqual(self.events("salt"), [])              # 살포 없음
        start = self.events("start")[0]
        self.assertIsNone(start.get("plan"))
        self.assertIsNone(self.hellos()[-1].get("plan"))

    def test_wifi_retry_does_not_block(self):
        self.build_lap()
        self.make_car()
        self.world.at(100, BUTTON, 0)     # Wi-Fi가 없어도 버튼 처리는 계속 돈다
        self.world.at(200, BUTTON, 1)
        self.run_until(100)
        self.assertEqual(self.world.connects, 1)            # 처음 한 번 시도
        self.run_until(5000)
        self.assertEqual(self.world.connects, 1)            # 10초 전에는 다시 시도하지 않는다
        self.run_until(10500)
        self.assertEqual(self.world.connects, 2)

    def test_usb_plan(self):
        self.build_lap()
        self.make_car()
        os.write(self.pipe_w, b'@@PLAN {"plan_id": "P5", "cells": ["U2", "D3"]}\n')
        self.step(0)
        self.assertEqual(self.car.plan_id, "P5")
        self.assertEqual(self.car.cells, ["U2", "D3"])
        with open(self.cfg.PLAN_PATH) as f:
            self.assertEqual(json.load(f), {"plan_id": "P5", "cells": ["U2", "D3"]})
        other = _MODS["main"].Car(self.cfg, stdin=self.stdin)
        with contextlib.redirect_stdout(io.StringIO()):
            other.load_plan()
        self.assertEqual(other.plan_id, "P5")

    def test_usb_plan_rejected_while_running(self):
        self.build_lap()
        self.start()
        os.write(self.pipe_w, b'@@PLAN {"plan_id": "P6", "cells": ["D1"]}\n')
        self.step(400)
        self.assertEqual(self.car.plan_id, "P1")

    def test_unknown_cells_dropped(self):
        self.build_lap()
        self.make_car()
        os.write(self.pipe_w, b'@@PLAN {"plan_id": "P5", "cells": ["X1", "U2", "U2"]}\n')
        self.step(0)
        self.assertEqual(self.car.cells, ["U2"])


class TestManualPush(Sim):
    """MANUAL_PUSH=True: 손으로 미는 모드. 모터를 쓰지 않고 표식·살포·정지 판단만 한다."""

    MOTOR_PINS = (10, 11, 12, 13, 14, 15)

    def test_boot_summary_mentions_manual(self):
        self.make_car(boot=True, MANUAL_PUSH=True)
        self.assertIn("손으로 미는 모드", self.boot_log)

    def test_full_lap_without_motors(self):
        self.run_lap(plan=("U2", "D3"), MANUAL_PUSH=True)
        self.assertTrue(self.car.manual)
        # 모터 duty는 처음 0에서 한 번도 움직이지 않는다(서보 duty는 따로 센다)
        motor_writes = [e for e in self.world.duty_log
                        if e[1] in (PWMA, PWMB) and e[2] != 0]
        self.assertEqual(motor_writes, [])
        self.assertEqual(self.world.duties[PWMA], 0)
        self.assertEqual(self.world.duties[PWMB], 0)
        for pin in (10, 11, 13, 14):
            self.assertNotIn(pin, self.world.outputs)          # 방향 핀도 건드리지 않는다
        # 표식·칸·살포·정지는 정상
        self.assertEqual(self.world.cells_marked(), LAP_CELLS)
        self.assertEqual([m.get("cell") for m in self.events("salt")], ["U2", "D3"])
        self.assertEqual(self.car.state, "DONE")
        self.assertTrue(self.hellos()[-1]["st"] == "DONE")

    def test_white_line_does_not_go_lost(self):
        self.build_lap()
        self.start(plan=("U2",), MANUAL_PUSH=True)
        self.world.line_off(700)                              # 3초 넘게 흰색만 본다
        self.run_until(4000)
        self.assertEqual(self.car.state, "RUN")
        self.assertNotIn("lost", self.world.event_names())

    def test_obstacle_does_not_hold(self):
        self.build_lap()
        self.start(plan=("U2",), MANUAL_PUSH=True)
        self.world.at_pulse(320, 300)                         # 5cm — 밀고 있으니 상관없다
        self.run_until(1500)
        self.assertEqual(self.car.state, "RUN")
        self.assertNotIn("obstacle", self.world.event_names())
        self.assertTrue(any(m.get("dist") is not None for m in self.hellos()))  # 거리는 보고

    def test_button_and_stop_still_work(self):
        self.build_lap()
        self.make_car(MANUAL_PUSH=True)
        self.send({"t": "plan", "seq": 1, "plan_id": "P1", "cells": ["U2"]})
        self.step(0)
        self.world.at(100, BUTTON, 0)
        self.world.at(200, BUTTON, 1)
        self.run_until(300)
        self.assertEqual(self.car.state, "RUN")
        self.world.at(400, BUTTON, 0)
        self.world.at(500, BUTTON, 1)
        self.run_until(520)
        self.assertEqual(self.car.state, "HOLD_CMD")
        self.send({"t": "resume", "seq": 2})
        self.step(600)
        self.assertEqual(self.car.state, "RUN")
        self.assertEqual(self.world.duties[PWMA], 0)


class TestCalibration(Sim):
    """현장 보정용(DIAG, LOG_MARKERS)."""

    def test_diag_mode_does_not_drive(self):
        self.build_lap()
        self.make_car(DIAG=True)
        text = "".join(self.step(t) for t in range(0, 1000, 5))
        self.assertIn("진단 L=", text)
        self.assertEqual(text.count("진단 L="), 5)              # 200ms마다
        self.assertEqual(self.car.state, "IDLE")
        self.assertEqual(self.world.duties[PWMA], 0)
        self.assertEqual(self.world.duties[PWMB], 0)

    def test_marker_logs(self):
        self.build_lap()
        self.start(plan=("U2",))
        text = "".join(self.step(t) for t in range(300, 5000, 5))
        self.assertIn("막대 감지", text)
        self.assertIn("이전 막대에서", text)                    # 막대 간격(ms)
        self.assertIn("묶음 확정", text)
        self.assertIn("칸 U2", text)                            # 현재 칸

    def test_marker_logs_can_be_off(self):
        self.build_lap()
        self.make_car(LOG_MARKERS=False)
        self.send({"t": "plan", "seq": 1, "plan_id": "P1", "cells": ["U2"]})
        self.step(0)
        self.send({"t": "go", "seq": 2, "plan_id": "P1"})
        self.step(300)
        text = "".join(self.step(t) for t in range(305, 5000, 5))
        self.assertNotIn("막대 감지", text)
        self.assertNotIn("묶음 확정", text)


class TestObstacle(Sim):
    def test_hold_and_clear(self):
        self.build_lap()
        self.start()
        self.assertEqual(self.car.state, "RUN")
        self.assertGreater(self.world.duties[PWMA], 0)      # 달리는 중
        self.world.at_pulse(400, 500)                       # 8.6cm 앞에 장애물
        self.run_until(500)
        self.assertEqual(self.car.state, "HOLD_OBS")
        self.assertEqual(self.world.duties[PWMA], 0)
        self.assertIn("obstacle", self.world.event_names())
        self.world.at_pulse(600, -1)                        # 시간 초과 = 멀리 있음
        self.run_until(1090)
        self.assertEqual(self.car.state, "HOLD_OBS")        # RESUME_MS(500)는 기다린다
        self.run_until(1200)
        self.assertEqual(self.car.state, "RUN")
        self.assertIn("clear", self.world.event_names())


if __name__ == "__main__":
    unittest.main()
