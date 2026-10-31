# ICE-ZERO 제설차(pico/car) 시험. 하드웨어 없이 CPython으로 돈다.
#   - car_core: 기구 환산, 기지 출발·귀환 경로, 살포 구간, 상태기계(seq·정지·일시정지·장애물), 프로토콜
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
    pose = pose or car_core.Pose()
    segs = car_core.plan_for_order(order, pose)
    mission = car_core.Mission(segs, pose)
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
        self.assertEqual(car_core.mm_to_steps(500), 10029)      # 중심까지
        self.assertEqual(car_core.mm_to_steps(515), 10330)      # 귀환 후진
        self.assertEqual(car_core.mm_to_steps(380), 7622)       # E
        self.assertEqual(car_core.mm_to_steps(400), 8023)       # W
        self.assertEqual(car_core.mm_to_steps(250), 5015)       # N
        self.assertEqual(car_core.mm_to_steps(-360), 7221)      # 거리는 절댓값

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

    def test_dock_is_south_of_center(self):
        self.assertEqual(car_core.DOCK_X, config.CENTER_X)
        self.assertEqual(car_core.DOCK_Y, config.CENTER_Y + config.BASE_DIST_MM)
        pose = car_core.Pose()
        self.assertEqual((pose.x, pose.y, pose.h), (car_core.DOCK_X, car_core.DOCK_Y, 0.0))
        self.assertAlmostEqual(pose.dist_to_center(), config.BASE_DIST_MM)

    def test_shortest_delta(self):
        self.assertAlmostEqual(car_core.shortest_delta(0, 350), 10.0)
        self.assertAlmostEqual(car_core.shortest_delta(270, 0), -90.0)
        self.assertAlmostEqual(car_core.shortest_delta(0, 90), -90.0)
        self.assertAlmostEqual(abs(car_core.shortest_delta(180, 0)), 180.0)

    def test_norm_and_bearing(self):
        self.assertAlmostEqual(car_core.norm_deg(-10), 350.0)
        self.assertAlmostEqual(car_core.bearing_to(0, -100), 0.0)      # 북(y 감소)
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
    def test_depart_arms_return(self):
        segs = car_core.plan_for_order(["E"], car_core.Pose())
        self.assertEqual([s["phase"] for s in segs],
                         ["depart", "turn", "out", "turn", "back", "home", "home"])
        self.assertEqual([s["steps"] for s in segs],
                         [10029, 1654, 7622, 3308, 7622, 1654, 10330])
        self.assertEqual([s["dir"] for s in segs], [1, 1, 1, 1, 1, 1, -1])  # 마지막만 후진
        # 귀환 회전은 서쪽(270도)에서 북쪽으로 도는 +90도다
        self.assertEqual([bool(s["spray"]) for s in segs],
                         [False, False, True, False, False, False, False])

    def test_depart_reaches_center(self):
        segs = car_core.plan_for_order(["E"], car_core.Pose())
        first = segs[0]
        self.assertEqual(first["phase"], "depart")
        self.assertEqual(first["steps"], car_core.mm_to_steps(config.BASE_DIST_MM))
        self.assertIsNone(first["arm"])

    def test_s_is_served_on_depart(self):
        segs = car_core.plan_for_order(["S", "W"], car_core.Pose())
        first = segs[0]
        self.assertEqual(first["phase"], "depart")
        self.assertEqual(first["arm"], "S")
        self.assertTrue(first["spray"])
        self.assertEqual(first["window"], config.SPRAY_WIN["S"])
        self.assertEqual(first["mode"], "remain")      # 중심까지 남은 거리 기준
        self.assertEqual([s for s in segs if s["arm"] == "S" and s["phase"] == "out"], [])
        # S를 뺀 W만 갈래 주행을 한다
        self.assertEqual(len([s for s in segs if s["phase"] == "out"]), 1)

    def test_arm_distances_and_windows(self):
        for arm in ("N", "E", "W"):
            segs = car_core.plan_for_order([arm], car_core.Pose())
            out = [s for s in segs if s["phase"] == "out"][0]
            self.assertEqual(out["steps"], car_core.mm_to_steps(config.ARM_OUT_MM[arm]))
            self.assertEqual(out["window"], config.SPRAY_WIN[arm])
            self.assertEqual(out["mode"], "dist")
            back = [s for s in segs if s["phase"] == "back"][0]
            self.assertEqual(back["steps"], out["steps"])      # 같은 거리를 돌아온다
            self.assertFalse(back["spray"])

    def test_return_reverses_into_base(self):
        segs = car_core.plan_for_order(["E"], car_core.Pose())
        last = segs[-1]
        self.assertEqual(last["phase"], "home")
        self.assertEqual(last["dir"], -1)                      # 후진
        self.assertEqual(last["steps"], car_core.mm_to_steps(
            config.BASE_DIST_MM + config.DOCK_OVERDRIVE_MM))
        self.assertFalse(last["spray"])

    def test_pose_resets_to_dock(self):
        for order in (["S"], ["E"], ["N", "E"], ["E", "W"], ["N", "E", "S", "W"]):
            steps, spray, events, pose = sim_mission(order)
            self.assertEqual(pose.x, car_core.DOCK_X)
            self.assertEqual(pose.y, car_core.DOCK_Y)
            self.assertEqual(pose.h, 0.0)
            self.assertEqual(events[-1][0], car_core.EV_PLAN_DONE)

    def test_spray_happens_only_outbound(self):
        cases = ((["E"], {"out"}), (["S"], {"depart"}), (["S", "W"], {"depart", "out"}))
        for order, want in cases:
            segs = car_core.plan_for_order(order, car_core.Pose())
            mission = car_core.Mission(segs, car_core.Pose())
            phases = set()
            while not mission.done:
                mission.step()
                if mission.spray:
                    phases.add(mission.phase)
            self.assertEqual(phases, want)

    def test_arm_spray_window_length(self):
        for arm in ("N", "E", "W"):
            segs = car_core.plan_for_order([arm], car_core.Pose())
            mission = car_core.Mission(segs, car_core.Pose())
            sprayed = 0
            while not mission.done:
                mission.step()
                if mission.spray:
                    sprayed += 1
            lo, hi = config.SPRAY_WIN[arm]
            self.assertAlmostEqual(sprayed * car_core.MM_PER_STEP, hi - lo, delta=2.0)

    def test_s_spray_window_uses_remaining_distance(self):
        segs = car_core.plan_for_order(["S"], car_core.Pose())
        mission = car_core.Mission(segs, car_core.Pose())
        sprayed = 0
        while not mission.done:
            mission.step()
            if mission.spray:
                sprayed += 1
        lo, hi = config.SPRAY_WIN["S"]
        # 출발 길이므로 '중심까지 남은 거리'가 hi에서 lo로 줄어드는 동안 열린다
        self.assertAlmostEqual(sprayed * car_core.MM_PER_STEP, hi - lo, delta=2.0)

    def test_s_arm_events(self):
        steps, spray, events, pose = sim_mission(["S", "W"])
        names = [e[0] for e in events]
        self.assertEqual(names, [
            car_core.EV_ARM_START, car_core.EV_SPRAY_ON, car_core.EV_SPRAY_OFF,
            car_core.EV_ARM_DONE,
            car_core.EV_ARM_START, car_core.EV_SPRAY_ON, car_core.EV_SPRAY_OFF,
            car_core.EV_ARM_DONE, car_core.EV_PLAN_DONE])
        arms = [e[1] for e in events if e[0] == car_core.EV_ARM_DONE]
        self.assertEqual(arms, ["S", "W"])

    def test_arm_start_follows_return_heading(self):
        # E를 돌고 나면 서쪽을 보고 돌아오므로 W로 가는 회전이 필요 없다
        segs = car_core.plan_for_order(["E", "W"], car_core.Pose())
        self.assertEqual([s["steps"] for s in segs],
                         [10029, 1654, 7622, 3308, 7622, 8023, 3308, 8023, 1654, 10330])
        self.assertEqual(segs[5]["arm"], "W")
        self.assertEqual(segs[5]["phase"], "out")

    def test_estimate_seconds(self):
        self.assertAlmostEqual(car_core.estimate_seconds(["S"]),
                               20359 * config.STEP_US / 1000000.0)
        self.assertAlmostEqual(car_core.estimate_seconds(["E", "W"]),
                               61573 * config.STEP_US / 1000000.0)
        self.assertAlmostEqual(car_core.estimate_seconds(["S", "W"]),
                               43021 * config.STEP_US / 1000000.0)
        self.assertAlmostEqual(car_core.estimate_seconds(["N", "E", "S", "W"]),
                               74911 * config.STEP_US / 1000000.0)

    def test_plan_home_from_mid_arm(self):
        pose = car_core.Pose(x=config.CENTER_X + config.ARM_OUT_MM["E"],
                             y=config.CENTER_Y, h=90.0)
        segs = car_core.plan_home(pose)
        self.assertEqual(segs[0]["phase"], "home")
        mission = car_core.Mission(segs, pose)
        while not mission.done:
            mission.step()
        self.assertEqual(pose.x, car_core.DOCK_X)
        self.assertEqual(pose.y, car_core.DOCK_Y)
        self.assertEqual(pose.h, 0.0)

    def test_plan_home_from_center_reverses_only(self):
        pose = car_core.Pose(x=config.CENTER_X, y=config.CENTER_Y, h=0.0)
        segs = car_core.plan_home(pose)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["phase"], "home")
        self.assertEqual(segs[0]["dir"], -1)

    def test_plan_home_from_dock(self):
        # 도킹 위치는 이미 북향이라 회전이 필요 없다: 중심으로 전진 → 후진 귀환
        segs = car_core.plan_home(car_core.Pose())
        self.assertEqual([s["phase"] for s in segs], ["home", "home"])
        self.assertEqual(segs[0]["dir"], 1)
        self.assertEqual(segs[0]["steps"], car_core.mm_to_steps(config.BASE_DIST_MM))
        self.assertEqual(segs[1]["dir"], -1)
        self.assertEqual(segs[1]["steps"], car_core.mm_to_steps(
            config.BASE_DIST_MM + config.DOCK_OVERDRIVE_MM))


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
        self.assertEqual(tel["x"], int(car_core.DOCK_X))
        self.assertEqual(tel["y"], int(car_core.DOCK_Y))
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
        self.assertTrue(car_core.valid_order(["N", "E", "S", "W"])[0])
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
        self.assertEqual(self.core.state, car_core.STATE_RUN)
        self.assertEqual(self.core.phase, car_core.PHASE_DEPART)

    def test_tel_shows_depart_phase(self):
        self.plan(1)
        self.drain()
        for _ in range(5):
            self.core.step()
        tel = self.core.tel(100)
        self.assertEqual(tel["phase"], "depart")
        self.assertEqual(tel["state"], car_core.STATE_RUN)
        self.assertEqual(tel["y"], int(car_core.DOCK_Y))      # 아직 몇 mm 안 움직였다
        self.assertLess(self.core.pose.y, car_core.DOCK_Y)     # 북쪽으로 갔다

    def test_s_arm_starts_on_depart(self):
        self.plan(1, order=("S", "W"))
        out = self.drain()
        self.assertEqual([m["t"] for m in out], ["ack", "evt", "evt"])
        self.assertEqual(out[2]["e"], car_core.EV_ARM_START)
        self.assertEqual(out[2]["arm"], "S")

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
        self.assertEqual(self.core.arm, None)                  # 출발 구간이라 arm이 없다
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

    def test_home_returns_to_dock(self):
        self.plan(1, order=("E",))
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
        self.assertEqual(self.core.pose.x, car_core.DOCK_X)
        self.assertEqual(self.core.pose.y, car_core.DOCK_Y)
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

    def test_obstacle_ignored_while_reversing(self):
        """귀환 후진 중에는 차고 벽을 장애물로 보지 않는다."""
        self.plan(1, order=("S",))
        self.drain()
        segs = self.core.mission.segs
        reverse_steps = segs[-1]["steps"]
        while self.core.can_step() and not self.core.mission.reversing():
            self.core.step()
        self.assertTrue(self.core.mission.reversing())
        self.core.sonar(3.0, self.t)                  # 뒤벽이 3cm 앞
        self.core.tick(self.t + 10)
        self.assertEqual(self.core.state, car_core.STATE_RUN)
        self.assertIsNone(self.core.blocked_since)
        self.assertEqual(self.core.tel(self.t)["obst_cm"], 3.0)   # 표시는 한다
        for _ in range(reverse_steps):
            self.core.step()
        self.assertEqual(self.core.state, car_core.STATE_IDLE)
        self.assertEqual(self.core.pose.y, car_core.DOCK_Y)

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


# ---------------------------------------------------------------- main.py (가짜 하드웨어)
class DeviceTest(unittest.TestCase):
    def test_plan_moves_coils_and_sprays(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            inject(world, {"t": "plan", "seq": 1, "order": ["S"]})
            run_ms(dev, world, 200)
            self.assertEqual(dev.core.state, core_mod.STATE_RUN)
            self.assertEqual(dev.core.phase, "depart")
            self.assertFalse(world.coils_off(cfg.PIN_LEFT))
            self.assertEqual(world.freqs[cfg.PIN_SERVO], cfg.SERVO_HZ)
            # 출발 길 110mm를 지나면 S 살포가 시작된다
            for i in range(2):
                inject(world, {"t": "ping", "seq": 100 + i})
                run_ms(dev, world, 2000)
            self.assertTrue(dev.core.spray)
            self.assertGreater(world.duty[cfg.PIN_SERVO], 0)
            self.assertLess(dev.core.pose.y, core_mod.DOCK_Y)     # 북쪽으로 갔다
            t = tel_last(world)
            self.assertIsNotNone(t)
            self.assertEqual(t["phase"], "depart")

    def test_stop_turns_coils_off_and_closes_servo(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            inject(world, {"t": "plan", "seq": 1, "order": ["S"]})
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
            inject(world, {"t": "plan", "seq": 1, "order": ["S"]})
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
            inject(world, {"t": "plan", "seq": 1, "order": ["S"]})
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

    def test_reverse_ignores_sonar(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            # 중심에 있다가 home을 받으면 곧바로 후진(귀환)만 한다
            dev.core.pose.x = cfg.CENTER_X
            dev.core.pose.y = cfg.CENTER_Y
            dev.core.pose.h = 0.0
            inject(world, {"t": "home", "seq": 9})
            dev.tick()
            self.assertEqual(dev.core.mission.phase, "home")
            self.assertTrue(dev.core.mission.reversing())
            world.sonar_cm(3.0)
            run_ms(dev, world, 1000)
            self.assertEqual(dev.core.state, core_mod.STATE_RUN)
            self.assertIsNone(dev.core.blocked_since)

    def test_link_timeout_pauses(self):
        with fake_pico() as (dev, world, core_mod, cfg):
            inject(world, {"t": "plan", "seq": 1, "order": ["S"]})
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
            inject(world, {"t": "plan", "seq": 5, "order": ["S"]})
            dev.tick()
            msgs = sent_of(world)
            acks = [m for m in msgs if m["t"] == "ack"]
            self.assertEqual(acks[0]["seq"], 5)
            self.assertTrue(acks[0]["ok"])
            evts = [m for m in msgs if m["t"] == "evt"]
            self.assertEqual(evts[0]["e"], core_mod.EV_PLAN_START)
            self.assertEqual(evts[1]["e"], core_mod.EV_ARM_START)
            self.assertEqual(evts[1]["arm"], "S")

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
            inject(world, {"t": "plan", "seq": 1, "order": ["S"]})
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
            inject(world, {"t": "plan", "seq": 1, "order": ["S"]})
            run_ms(dev, world, 300)
            self.assertEqual(world.sonar_reads, 0)
            self.assertEqual(dev.core.state, core_mod.STATE_RUN)


if __name__ == "__main__":
    unittest.main()
