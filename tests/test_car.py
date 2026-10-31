# ICE-ZERO 제설차(pico/car) 시험. 하드웨어 없이 CPython으로 돈다.
#   - car_core: 기구 환산, 경로 계획·살포 구간, 상태기계(seq·정지·일시정지·장애물), 프로토콜
#   - main: 가짜 machine/network/socket/time으로 비차단 루프 한 바퀴 — 코일·서보·텔레메트리
import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICO = os.path.join(ROOT, "pico", "car")
TESTS = os.path.dirname(os.path.abspath(__file__))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

import fake_mpy_car  # noqa: E402  (sys.path를 먼저 넣는다)


def load_module(name, filename):
    """파일 경로로 직접 모듈을 읽는다(sys.path를 오염시키지 않는다)."""
    path = os.path.join(PICO, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_core():
    """car_core는 config를 import하므로 잠깐 sys.modules에 넣고 읽는다."""
    saved = sys.modules.get("config")
    sys.modules["config"] = load_module("config", "config.py")
    try:
        return load_module("car_core", "car_core.py")
    finally:
        if saved is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = saved


car_core = load_core()
config = car_core.config          # car_core가 실제로 쓴 설정 모듈


# ---------------------------------------------------------------- 가짜 하드웨어 붙이기
@contextlib.contextmanager
def fake_pico():
    """가짜 모듈을 끼우고 main을 새로 읽어 CarDevice까지 만든다."""
    world, mods = fake_mpy_car.build()
    names = ("main", "config", "car_core", "machine", "network", "socket", "time")
    saved = {}
    for k in names:
        saved[k] = sys.modules.get(k)
    for k in names:
        sys.modules.pop(k, None)
    sys.modules.update(mods)
    sys.modules["config"] = load_module("config", "config.py")
    core_mod = load_module("car_core", "car_core.py")
    sys.modules["car_core"] = core_mod
    try:
        main = load_module("main", "main.py")
        sys.modules["main"] = main
        cfg = sys.modules["config"]
        cfg.LOG_EVENTS = False          # 시험 출력을 조용하게
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dev = main.CarDevice(cfg)
        dev.boot_log = out.getvalue()
        yield dev, world, core_mod, cfg
    finally:
        for k in names:
            sys.modules.pop(k, None)
        for k in names:
            if saved[k] is not None:
                sys.modules[k] = saved[k]


def run_ms(dev, world, ms, tick_us=1200):
    """가짜 시계를 tick_us씩 밀면서 tick을 돈다(기본은 스텝 하나 간격)."""
    left = int(ms * 1000)
    while left > 0:
        world.advance_us(tick_us)
        left -= tick_us
        dev.tick()


def inject(world, obj, addr=("127.0.0.1", 9200)):
    world.inbox.append((car_core.encode(obj), addr))


def sent_of(world):
    return [json.loads(data.decode()) for data, _ in world.sent]


def tel_last(world):
    for msg in reversed(sent_of(world)):
        if msg.get("t") == "tel":
            return msg
    return None


def sim_mission(order, pose=None):
    """계획을 끝까지 밀어 보고 (스텝 수, 살포 스텝 수, 이벤트, 최종 자세)를 돌려준다."""
    segs = car_core.plan_for_order(order, pose or car_core.Pose())
    mission = car_core.Mission(segs, pose or car_core.Pose())
    events = list(mission.begin())
    steps = 0
    spray = 0
    while not mission.done:
        left, right, sp, ev = mission.step()
        steps += 1
        if sp:
            spray += 1
        events.extend(ev)
    return steps, spray, events, mission.pose


# ---------------------------------------------------------------- 기구 환산
class GeometryTest(unittest.TestCase):
    def test_mm_to_steps(self):
        self.assertEqual(car_core.mm_to_steps(0), 0)
        self.assertEqual(car_core.mm_to_steps(360), 7221)
        self.assertEqual(car_core.mm_to_steps(-360), 7221)      # 거리는 절댓값
        self.assertEqual(car_core.mm_to_steps(110), 2206)

    def test_deg_to_steps(self):
        self.assertEqual(car_core.deg_to_steps(0), 0)
        self.assertEqual(car_core.deg_to_steps(45), 827)
        self.assertEqual(car_core.deg_to_steps(90), 1654)
        self.assertEqual(car_core.deg_to_steps(180), 3308)
        self.assertEqual(car_core.deg_to_steps(270), 4962)
        self.assertEqual(car_core.deg_to_steps(-90), 1654)

    def test_one_step_units(self):
        self.assertAlmostEqual(car_core.MM_PER_STEP, 0.04985, places=4)
        self.assertAlmostEqual(car_core.DEG_PER_STEP, 0.05441, places=4)

    def test_shortest_delta(self):
        self.assertAlmostEqual(car_core.shortest_delta(0, 350), 10.0)
        self.assertAlmostEqual(car_core.shortest_delta(270, 0), -90.0)
        self.assertAlmostEqual(car_core.shortest_delta(0, 90), -90.0)
        self.assertAlmostEqual(abs(car_core.shortest_delta(180, 0)), 180.0)

    def test_norm_and_bearing(self):
        self.assertAlmostEqual(car_core.norm_deg(-10), 350.0)
        self.assertAlmostEqual(car_core.bearing_to(0, -100), 0.0)      # 북
        self.assertAlmostEqual(car_core.bearing_to(100, 0), 90.0)      # 동
        self.assertAlmostEqual(car_core.bearing_to(0, 100), 180.0)     # 남
        self.assertAlmostEqual(car_core.bearing_to(-100, 0), 270.0)    # 서

    def test_half_step_sequence(self):
        self.assertEqual(len(car_core.HALF_STEP), 8)
        for pattern in car_core.HALF_STEP:
            self.assertEqual(len(pattern), 4)
            for v in pattern:
                self.assertIn(v, (0, 1))
        for i in range(8):
            a = car_core.HALF_STEP[i]
            b = car_core.HALF_STEP[(i + 1) % 8]
            diff = 0
            for k in range(4):
                if a[k] != b[k]:
                    diff += 1
            self.assertEqual(diff, 1)          # 이웃한 단계는 코일 하나만 바뀐다


# ---------------------------------------------------------------- 경로 계획
class PlanTest(unittest.TestCase):
    def test_single_arm_phases(self):
        segs = car_core.plan_for_order(["E"], car_core.Pose())
        self.assertEqual([s["phase"] for s in segs],
                         ["turn", "out", "turn", "back", "home"])
        self.assertEqual([s["steps"] for s in segs],
                         [1654, 7221, 3308, 7221, 1654])
        self.assertEqual([s["dir"] for s in segs], [1, 1, 1, 1, 1])
        # 살포는 'out' 구간에만
        self.assertEqual([bool(s["spray"]) for s in segs],
                         [False, True, False, False, False])

    def test_out_and_back_length(self):
        segs = car_core.plan_for_order(["E"], car_core.Pose())
        drive = [s for s in segs if s["kind"] == "drive"]
        self.assertEqual(len(drive), 2)
        self.assertEqual(car_core.mm_to_steps(config.OUT_MM), drive[0]["steps"])
        self.assertEqual(drive[0]["steps"], drive[1]["steps"])   # 같은 거리를 돌아온다

    def test_turn_to_bearing(self):
        segs = car_core.plan_for_order(["S"], car_core.Pose())
        self.assertEqual(segs[0]["phase"], "turn")
        self.assertEqual(segs[0]["steps"], car_core.deg_to_steps(180))
        # W는 북에서 반시계 90도가 짧다
        segs = car_core.plan_for_order(["W"], car_core.Pose())
        self.assertEqual(segs[0]["dir"], -1)

    def test_plan_ends_north(self):
        for order in (["E"], ["W"], ["N"], ["S"], ["E", "W"]):
            steps, spray, events, pose = sim_mission(order)
            # 스텝 반올림 때문에 1스텝(0.054도) 남짓 오차가 남는다
            self.assertAlmostEqual(car_core.shortest_delta(0.0, pose.h), 0.0, delta=0.5)
            self.assertAlmostEqual(pose.x, config.HOME_X, delta=1.0)
            self.assertAlmostEqual(pose.y, config.HOME_Y, delta=1.0)

    def test_spray_window_covers_contract_range(self):
        steps, spray, events, pose = sim_mission(["E"])
        travelled = spray * car_core.MM_PER_STEP
        # 살포 구간은 110~340mm이고, 경계 판정에 ±0.5mm 여유를 둔다
        self.assertGreaterEqual(travelled, config.SPRAY_TO_MM - config.SPRAY_FROM_MM)
        self.assertLessEqual(travelled, config.SPRAY_TO_MM - config.SPRAY_FROM_MM + 2.0)
        names = [e[0] for e in events]
        self.assertEqual(names.index(car_core.EV_SPRAY_ON) + 1,
                         names.index(car_core.EV_SPRAY_OFF))

    def test_spray_stays_inside_out_phase(self):
        segs = car_core.plan_for_order(["E"], car_core.Pose())
        mission = car_core.Mission(segs, car_core.Pose())
        sprayed_phases = set()
        while not mission.done:
            mission.step()
            if mission.spray:
                sprayed_phases.add(mission.phase)
        self.assertEqual(sprayed_phases, {"out"})

    def test_events_order_two_arms(self):
        steps, spray, events, pose = sim_mission(["E", "W"])
        names = [e[0] for e in events]
        self.assertEqual(names, [
            car_core.EV_ARM_START, car_core.EV_SPRAY_ON, car_core.EV_SPRAY_OFF,
            car_core.EV_ARM_DONE,
            car_core.EV_ARM_START, car_core.EV_SPRAY_ON, car_core.EV_SPRAY_OFF,
            car_core.EV_ARM_DONE, car_core.EV_PLAN_DONE])
        arms = [e[1] for e in events if e[0] == car_core.EV_ARM_DONE]
        self.assertEqual(arms, ["E", "W"])

    def test_two_arm_time(self):
        one = car_core.estimate_seconds(["E"])
        two = car_core.estimate_seconds(["E", "W"])
        self.assertAlmostEqual(one, 21058 * config.STEP_US / 1000000.0)
        self.assertAlmostEqual(two, 38808 * config.STEP_US / 1000000.0)
        # 한 갈래 = 방위 회전 + 360mm + 180도 + 360mm
        self.assertEqual([s["steps"] for s in car_core.plan_for_order(["E"], car_core.Pose())],
                         [1654, 7221, 3308, 7221, 1654])
        # E를 돌고 나면 서쪽을 보고 돌아오므로 W로 가는 회전이 필요 없다
        segs = car_core.plan_for_order(["E", "W"], car_core.Pose())
        self.assertEqual([s["steps"] for s in segs],
                         [1654, 7221, 3308, 7221, 7221, 3308, 7221, 1654])
        self.assertEqual(sum(s["steps"] for s in segs), 38808)

    def test_plan_home_from_offset(self):
        pose = car_core.Pose(x=config.HOME_X + 200.0, y=config.HOME_Y - 100.0, h=45.0)
        segs = car_core.plan_home(pose)
        self.assertEqual(segs[-1]["phase"], "home")
        mission = car_core.Mission(segs, pose)
        while not mission.done:
            mission.step()
        self.assertAlmostEqual(pose.x, config.HOME_X, delta=1.0)
        self.assertAlmostEqual(pose.y, config.HOME_Y, delta=1.0)
        self.assertAlmostEqual(car_core.shortest_delta(0.0, pose.h), 0.0, delta=0.5)

    def test_plan_home_when_already_home(self):
        segs = car_core.plan_home(car_core.Pose())
        self.assertEqual(segs, [])


# ---------------------------------------------------------------- 프로토콜
class ProtocolTest(unittest.TestCase):
    def test_telemetry_format(self):
        core = car_core.CarCore(config)
        core.start(1000)
        tel = core.tel(2500)
        for key in ("t", "id", "state", "seq", "arm", "phase", "x", "y", "h",
                    "spray", "obst_cm", "up"):
            self.assertIn(key, tel)
        self.assertEqual(tel["t"], "tel")
        self.assertEqual(tel["id"], config.CAR_ID)
        self.assertEqual(tel["state"], car_core.STATE_IDLE)
        self.assertEqual(tel["phase"], car_core.PHASE_IDLE)
        self.assertEqual(tel["up"], 1500)
        self.assertIsNone(tel["obst_cm"])
        self.assertEqual(tel["x"], int(config.HOME_X))
        self.assertEqual(tel["h"], 0)

    def test_event_format(self):
        evt = car_core.make_evt(car_core.EV_SPRAY_ON, 7, "E")
        self.assertEqual(evt, {"t": "evt", "e": "spray_on", "seq": 7, "arm": "E"})
        evt = car_core.make_evt(car_core.EV_PLAN_DONE, 7)
        self.assertEqual(evt, {"t": "evt", "e": "plan_done", "seq": 7, "arm": None})

    def test_ack_and_hello(self):
        self.assertEqual(car_core.make_ack(3, False, "실행 중"),
                         {"t": "ack", "seq": 3, "ok": False, "reason": "실행 중"})
        self.assertEqual(car_core.make_hello(config),
                         {"t": "hello", "id": config.CAR_ID})

    def test_encode_parse_roundtrip(self):
        obj = {"t": "plan", "seq": 1, "order": ["E", "W"]}
        data = car_core.encode(obj)
        self.assertIsInstance(data, bytes)
        self.assertEqual(car_core.parse(data), obj)
        self.assertEqual(car_core.parse(data.decode()), obj)

    def test_parse_rejects_junk(self):
        self.assertIsNone(car_core.parse(b"\xff\xfe"))
        self.assertIsNone(car_core.parse("not json"))
        self.assertIsNone(car_core.parse("[1,2]"))

    def test_valid_order(self):
        self.assertTrue(car_core.valid_order(["E"])[0])
        self.assertTrue(car_core.valid_order(("E", "W"))[0])
        self.assertFalse(car_core.valid_order([])[0])
        self.assertFalse(car_core.valid_order("E")[0])
        self.assertFalse(car_core.valid_order(["X"])[0])
        self.assertFalse(car_core.valid_order(["E", "E"])[0])
        self.assertFalse(car_core.valid_order(["E", "W", "N", "S", "E"])[0])

    def test_secrets_are_empty_in_repo(self):
        self.assertEqual(config.WIFI_SSID, "")
        self.assertEqual(config.WIFI_PASS, "")


# ---------------------------------------------------------------- 상태기계
class CoreStateTest(unittest.TestCase):
    def setUp(self):
        self.core = car_core.CarCore(config)
        self.core.start(0)
        self.t = 10

    def plan(self, seq, order=("E",), now=None):
        self.core.handle_packet({"t": "plan", "seq": seq, "order": list(order)},
                                self.t if now is None else now)

    def drain(self):
        return self.core.drain()

    def test_plan_starts_and_acks(self):
        self.plan(1)
        out = self.drain()
        self.assertEqual(out[0], {"t": "ack", "seq": 1, "ok": True, "reason": ""})
        self.assertEqual(out[1]["e"], car_core.EV_PLAN_START)
        self.assertEqual(out[2]["e"], car_core.EV_ARM_START)
        self.assertEqual(out[2]["arm"], "E")
        self.assertEqual(self.core.state, car_core.STATE_RUN)
        self.assertEqual(self.core.phase, car_core.PHASE_TURN)

    def test_duplicate_seq_runs_once(self):
        self.plan(1)
        self.drain()
        self.core.step()
        steps_before = self.core.mission.steps_done
        self.plan(1)
        out = self.drain()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["t"], "ack")
        self.assertFalse(out[0]["ok"])
        self.assertEqual(self.core.mission.steps_done, steps_before)  # 다시 시작하지 않는다
        self.assertEqual(self.core.state, car_core.STATE_RUN)

    def test_plan_rejected_while_running(self):
        self.plan(1)
        self.drain()
        self.plan(2, order=("W",))
        out = self.drain()
        self.assertEqual(out[0]["t"], "ack")
        self.assertFalse(out[0]["ok"])
        self.assertTrue(out[0]["reason"])
        self.assertEqual(self.core.arm, "E")                  # 원래 계획이 살아 있다
        self.assertFalse(self.core.mission.done)

    def test_bad_order_rejected(self):
        self.plan(3, order=("Q",))
        out = self.drain()
        self.assertFalse(out[0]["ok"])
        self.assertEqual(self.core.state, car_core.STATE_IDLE)

    def test_stop(self):
        self.plan(1)
        self.drain()
        for _ in range(20):
            self.core.step()
        self.core.handle_packet({"t": "stop"}, self.t)
        out = self.drain()
        self.assertEqual(out[0]["e"], car_core.EV_STOPPED)
        self.assertEqual(self.core.state, car_core.STATE_STOPPED)
        self.assertFalse(self.core.spray)
        self.assertFalse(self.core.can_step())
        self.assertFalse(self.core.step()["step"])            # 스텝을 밀지 않는다

    def test_home_after_stop(self):
        self.plan(1)
        self.drain()
        for _ in range(3000):
            self.core.step()
        self.core.handle_packet({"t": "stop"}, self.t)
        self.drain()
        self.core.handle_packet({"t": "home", "seq": 9}, self.t)
        out = self.drain()
        self.assertEqual(out[0]["t"], "ack")
        self.assertTrue(out[0]["ok"])
        self.assertEqual(self.core.state, car_core.STATE_RUN)
        self.assertEqual(self.core.mission.phase, car_core.PHASE_HOME)
        self.drain()
        while self.core.can_step():
            self.core.step()
        self.assertAlmostEqual(self.core.pose.x, config.HOME_X, delta=1.0)
        self.assertAlmostEqual(self.core.pose.y, config.HOME_Y, delta=1.0)
        self.assertEqual(self.core.state, car_core.STATE_IDLE)

    def test_link_timeout_pauses_and_resumes(self):
        self.plan(1)
        self.drain()
        self.core.tick(self.t + config.LINK_TIMEOUT_MS - 1)
        self.assertEqual(self.core.state, car_core.STATE_RUN)
        self.core.tick(self.t + config.LINK_TIMEOUT_MS + 1)
        self.assertEqual(self.core.state, car_core.STATE_PAUSE)
        self.assertFalse(self.core.can_step())
        self.drain()
        self.core.handle_packet({"t": "ping"}, self.t + config.LINK_TIMEOUT_MS + 10)
        self.core.tick(self.t + config.LINK_TIMEOUT_MS + 11)
        self.assertEqual(self.core.state, car_core.STATE_RUN)
        names = [m.get("e") for m in self.drain() if m.get("t") == "evt"]
        self.assertIn(car_core.EV_RESUMED, names)

    def test_obstacle_pause_resume(self):
        self.plan(1)
        self.drain()
        self.core.sonar(4.0, self.t)
        out = self.drain()
        self.assertEqual([m["e"] for m in out if m.get("t") == "evt"],
                         [car_core.EV_OBSTACLE])
        self.assertEqual(self.core.state, car_core.STATE_PAUSE)
        # 1초 동안 비어야 재개한다
        self.core.sonar(30.0, self.t + 10)
        self.core.tick(self.t + 500)
        self.assertEqual(self.core.state, car_core.STATE_PAUSE)
        self.core.sonar(30.0, self.t + 800)
        self.core.tick(self.t + 10 + config.OBST_CLEAR_MS)
        self.assertEqual(self.core.state, car_core.STATE_RUN)

    def test_obstacle_aborts_after_ten_seconds(self):
        self.plan(1)
        self.drain()
        self.core.sonar(5.0, self.t)
        self.drain()
        self.core.tick(self.t + config.OBST_ABORT_MS - 100)
        self.assertEqual(self.core.state, car_core.STATE_PAUSE)
        self.core.tick(self.t + config.OBST_ABORT_MS + 1)
        out = self.drain()
        names = [m["e"] for m in out if m.get("t") == "evt"]
        self.assertIn(car_core.EV_ABORTED, names)
        self.assertEqual(self.core.state, car_core.STATE_ERROR)
        self.assertFalse(self.core.can_step())
        self.assertIsNone(self.core.mission)

    def test_plan_accepted_after_abort(self):
        self.plan(1)
        self.drain()
        self.core.sonar(5.0, self.t)
        self.core.tick(self.t + config.OBST_ABORT_MS + 1)
        self.drain()
        self.core.sonar(None, self.t + config.OBST_ABORT_MS + 2)
        self.plan(2, order=("W",))
        out = self.drain()
        self.assertTrue(out[0]["ok"])
        self.assertEqual(self.core.state, car_core.STATE_RUN)

    def test_tel_reports_pose_and_obstacle(self):
        self.plan(1)
        self.drain()
        for _ in range(10):
            self.core.step()
        self.core.sonar(12.34, self.t)
        tel = self.core.tel(100)
        self.assertEqual(tel["state"], car_core.STATE_RUN)
        self.assertEqual(tel["seq"], 1)
        self.assertEqual(tel["phase"], car_core.PHASE_TURN)
        self.assertEqual(tel["obst_cm"], 12.3)
        self.assertIn(tel["h"], (0, 1))                   # 10스텝 = 0.54도라 반올림하면 1


# ---------------------------------------------------------------- main.py (가짜 하드웨어)
class DeviceTest(unittest.TestCase):
    def test_plan_moves_coils_and_sprays(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            inject(world, {"t": "plan", "seq": 1, "order": ["E"]})
            run_ms(dev, world, 200)
            self.assertEqual(dev.core.state, core_mod.STATE_RUN)
            self.assertFalse(world.coils_off(cfg.PIN_LEFT))
            self.assertEqual(world.freqs[cfg.PIN_SERVO], cfg.SERVO_HZ)
            # 90도 회전 + 110mm ≈ 4.6초. 링크 타임아웃(5초)에 걸리지 않게 ping을 섞는다
            for i in range(3):
                inject(world, {"t": "ping", "seq": 100 + i})
                run_ms(dev, world, 2000)
            self.assertTrue(dev.core.spray)
            self.assertGreater(world.duty[cfg.PIN_SERVO], 0)
            t = tel_last(world)
            self.assertIsNotNone(t)
            self.assertGreater(t["x"], int(cfg.HOME_X))

    def test_stop_turns_coils_off_and_closes_servo(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            inject(world, {"t": "plan", "seq": 1, "order": ["E"]})
            run_ms(dev, world, 300)
            self.assertFalse(world.coils_off(cfg.PIN_LEFT))
            inject(world, {"t": "stop"})
            dev.tick()
            self.assertEqual(dev.core.state, core_mod.STATE_STOPPED)
            self.assertTrue(world.coils_off(cfg.PIN_LEFT))
            self.assertTrue(world.coils_off(cfg.PIN_RIGHT))
            self.assertEqual(world.duty[cfg.PIN_SERVO],
                             int(cfg.SERVO_MIN_US * 65535.0 / 20000.0))
            run_ms(dev, world, cfg.TEL_MS + 100, tick_us=1000)
            t = tel_last(world)
            self.assertEqual(t["state"], core_mod.STATE_STOPPED)

    def test_button_stops_and_resumes(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            inject(world, {"t": "plan", "seq": 1, "order": ["E"]})
            run_ms(dev, world, 100)
            world.button_down = True
            run_ms(dev, world, 100)
            self.assertEqual(dev.core.state, core_mod.STATE_STOPPED)
            world.button_down = False
            run_ms(dev, world, 100)
            world.button_down = True
            run_ms(dev, world, 100)
            self.assertEqual(dev.core.state, core_mod.STATE_RUN)

    def test_obstacle_stops_and_aborts(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            inject(world, {"t": "plan", "seq": 1, "order": ["E"]})
            run_ms(dev, world, 200)
            world.sonar_cm(4.0)
            run_ms(dev, world, 300)
            self.assertEqual(dev.core.state, core_mod.STATE_PAUSE)
            self.assertTrue(world.coils_off(cfg.PIN_LEFT))
            world.sonar_cm(None)
            run_ms(dev, world, 1500)
            self.assertEqual(dev.core.state, core_mod.STATE_RUN)
            world.sonar_cm(3.0)
            run_ms(dev, world, 300)
            run_ms(dev, world, cfg.OBST_ABORT_MS + 500)
            self.assertEqual(dev.core.state, core_mod.STATE_ERROR)
            self.assertTrue(world.coils_off(cfg.PIN_LEFT))

    def test_link_timeout_pauses(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            inject(world, {"t": "plan", "seq": 1, "order": ["E"]})
            run_ms(dev, world, 200)
            self.assertEqual(dev.core.state, core_mod.STATE_RUN)
            run_ms(dev, world, cfg.LINK_TIMEOUT_MS + 500)
            self.assertEqual(dev.core.state, core_mod.STATE_PAUSE)
            self.assertTrue(world.coils_off(cfg.PIN_LEFT))
            inject(world, {"t": "ping", "seq": 77})
            dev.tick()
            self.assertEqual(dev.core.state, core_mod.STATE_RUN)

    def test_hello_broadcast_and_tel_period(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            dev.tick()
            first = sent_of(world)
            self.assertEqual(first[0]["t"], "hello")
            self.assertEqual(first[0]["id"], cfg.CAR_ID)
            self.assertEqual(world.sent[0][1][0], "255.255.255.255")   # SERVER_IP가 비었다
            self.assertEqual(world.sent[0][1][1], cfg.SERVER_PORT)
            run_ms(dev, world, cfg.TEL_MS * 2 + 100, tick_us=1000)
            tels = [m for m in sent_of(world) if m["t"] == "tel"]
            self.assertGreaterEqual(len(tels), 2)

    def test_ack_and_events_reach_server(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            inject(world, {"t": "plan", "seq": 5, "order": ["E"]})
            dev.tick()
            msgs = sent_of(world)
            acks = [m for m in msgs if m["t"] == "ack"]
            self.assertEqual(acks[0]["seq"], 5)
            self.assertTrue(acks[0]["ok"])
            evts = [m for m in msgs if m["t"] == "evt"]
            self.assertEqual(evts[0]["e"], core_mod.EV_PLAN_START)
            self.assertEqual(evts[1]["e"], core_mod.EV_ARM_START)

    def test_wifi_retry_and_led_before_connected(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            cfg.WIFI_SSID = "hotspot"
            cfg.WIFI_PASS = "secret"
            world.wifi_connected = False
            dev.tick()
            self.assertEqual(world.wifi_attempts, [("hotspot", "secret")])
            self.assertEqual(world.outputs[cfg.PIN_LED_B], 1)     # 연결 전: 파랑
            self.assertEqual(world.outputs[cfg.PIN_LED_G], 0)
            # 재시도는 WIFI_RETRY_MS 간격으로만 한다
            run_ms(dev, world, cfg.WIFI_RETRY_MS - 200, tick_us=1000)
            self.assertEqual(len(world.wifi_attempts), 1)
            run_ms(dev, world, 400, tick_us=1000)
            self.assertEqual(len(world.wifi_attempts), 2)
            world.wifi_connected = True
            dev.tick()
            self.assertEqual(world.outputs[cfg.PIN_LED_G], 1)     # 붙으면 초록

    def test_no_step_burst_after_idle(self):
        """놀고 있다가 계획을 받아도 밀린 시간만큼 몰아서 돌지 않는다."""
        with fake_pico() as (dev, world, core_mod, cfg):
            run_ms(dev, world, 3000)                 # 계획 없이 3초(2500스텝 분량)
            inject(world, {"t": "plan", "seq": 1, "order": ["E"]})
            dev.tick()
            self.assertEqual(dev.core.state, core_mod.STATE_RUN)
            self.assertEqual(dev.core.mission.steps_done, 1)      # 딱 한 스텝
            run_ms(dev, world, 100, tick_us=1200)
            self.assertLess(dev.core.mission.steps_done, 120)     # 100ms면 83스텝 남짓

    def test_no_sonar_configuration(self):
        """SONAR_ENABLED=False면 초음파를 아예 재지 않고 장애물 정지도 없다."""
        with fake_pico() as (dev, world, core_mod, cfg):
            cfg.SONAR_ENABLED = False
            dev.sonar = dev.sonar.__class__(cfg)      # 초음파 핀 없이 다시 만든다
            inject(world, {"t": "plan", "seq": 1, "order": ["E"]})
            run_ms(dev, world, 300)
            self.assertEqual(world.sonar_reads, 0)
            self.assertEqual(dev.core.state, core_mod.STATE_RUN)


if __name__ == "__main__":
    unittest.main()
