"""server/gosaek_server.py 시험 — 하드웨어 없이 돈다.

가짜 엔진(tests/fake_engine.py) · 가짜 센서(텔레메트리 직접 주입) · 가짜 차(FakeCar)를 쓴다.
서버는 프로세스 안에서 Model + ThreadingHTTPServer 로 띄운다.
"""

import datetime
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

HERE =os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import server.gosaek_server as srv          # noqa: E402
from tests.fake_engine import FakeEngine    # noqa: E402

NIGHT = "2025-01-09"
ARMS = ("N", "E", "S", "W")


def wait_for(predicate, timeout=6.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def telemetry(t_map, rh_map=None, ok=True, wet=False, dock=True, refills=3, refilling=False):
    rh_map = rh_map or {a: 80 for a in ARMS}
    return {"t": dict(t_map), "rh": dict(rh_map), "ok": {a: bool(ok) for a in ARMS},
            "wet_raw": 900 if wet else 2400, "wet": bool(wet), "light_raw": 1200,
            "warn": bool(wet), "dock": bool(dock), "refills": refills,
            "refilling": bool(refilling), "up": 7}


class StubSensor(object):
    """시리얼 대신 쓰는 기록용 센서 링크."""

    mode = "serial"

    def __init__(self):
        self.lines = []

    def write_line(self, line):
        self.lines.append(line)

    def stop(self):
        pass


class ServerBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make_model(self, engine=None, **kw):
        kw.setdefault("events_path", os.path.join(self.tmp.name, "events.jsonl"))
        kw.setdefault("mock_arm_s", 0.03)
        kw.setdefault("baseline_s", 999.0)     # 시험에서는 /baseline 으로 직접 잡는다
        kw.setdefault("sensor_fresh_s", 0.6)
        kw.setdefault("tick_s", 0.02)
        kw.setdefault("auto_cooldown_s", 0.01)
        kw.setdefault("auto", False)
        model = srv.Model(engine=engine if engine is not None else FakeEngine(), **kw)
        self.addCleanup(model.stop)
        return model

    def attach_fake_car(self, model, arm_s=0.01):
        car = srv.FakeCar(model, arm_s=arm_s)
        model.car_link = car
        self.addCleanup(car.stop)
        return car

    def enable_base(self, model, dock=True, refills=3, wet=False):
        """기지 Pico(#1) 텔레메트리가 살아 있는 상태로 만든다."""
        with model.lock:
            model.sensor_state["mode"] = "fake"
        model.sensor_telemetry(telemetry({"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0},
                                         dock=dock, refills=refills, wet=wet))
        return model

    def last_show(self, stub):
        shows = [line for line in stub.lines if line.startswith("@@SHOW")]
        return json.loads(shows[-1][len("@@SHOW "):])

    def start_http(self, model):
        httpd = srv.serve(model, "127.0.0.1", 0)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2.0)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return port


class StateTest(ServerBase):
    def test_state_has_contract_step_json(self):
        model = self.make_model(night=NIGHT)
        state = model.snapshot()
        step = state["step"]
        self.assertIsNotNone(step)
        for key in ("time", "station", "obs", "forecast", "arms", "dispatch", "model"):
            self.assertIn(key, step)
        self.assertEqual(set(step["arms"]), set(ARMS))
        arm = step["arms"]["E"]
        for key in ("name", "label", "structure", "shadow_index", "risk", "risk_pct",
                    "local_dt", "wet", "t_eff", "p_freeze", "p_max", "source", "level",
                    "candidate", "treated", "priority", "reasons"):
            self.assertIn(key, arm)
        self.assertEqual(set(arm["t_eff"]), {"h0", "h1", "h3", "h6"})
        self.assertEqual(state["station"]["label"], "수원 119")
        self.assertFalse(state["station"]["replaced"])
        self.assertIn("/monitor", state["monitor_url"])
        self.assertEqual(state["replay"]["night"], NIGHT)
        self.assertEqual(state["replay"]["total"], 16)

    def test_replay_move_and_night(self):
        model = self.make_model(night=NIGHT)
        first = model.current_ts()
        result = model.move(3)
        self.assertEqual(result["index"], 3)
        self.assertNotEqual(model.current_ts(), first)
        self.assertEqual(model.snapshot()["replay"]["index"], 3)
        model.set_night("2025-01-10")
        self.assertEqual(model.night, "2025-01-10")
        self.assertEqual(model.snapshot()["replay"]["ts"], "2025-01-10T18:00:00")

    def test_budget_clamped(self):
        model = self.make_model()
        self.assertEqual(model.set_budget(9)["budget"], 4)
        self.assertEqual(model.set_budget(0)["budget"], 0)
        self.assertEqual(model.snapshot()["budget"], 0)
        with self.assertRaises(srv.HttpError):
            model.set_budget("많이")


class AutoDispatchTest(ServerBase):
    def test_weather_model_alone_never_dispatches(self):
        """날씨 모델이 출동을 권해도 차는 나가지 않는다. 출동은 눈을 봤을 때만(사진·조도센서)."""
        model = self.make_model(night=NIGHT, budget=1, auto=True)
        self.attach_fake_car(model)
        self.assertTrue(model.snapshot()["step"]["dispatch"]["recommend"])
        time.sleep(0.4)
        self.assertIsNone(model.execution["plan_id"], "날씨 모델만으로 출동했습니다")

    def test_snow_sensor_sweeps_all_arms_in_the_best_order(self):
        model = self.make_model(night=NIGHT, auto=True)
        self.attach_fake_car(model)
        self.enable_base(model, dock=True, wet=True)
        self.assertIsNotNone(wait_for(lambda: model.execution["plan_id"]), "눈 감지 출동이 없습니다")
        self.assertEqual(sorted(model.execution["order"]), ["E", "N", "S", "W"])
        self.assertEqual(model.execution["order"],
                         srv.route.plan({a: {"area_mm2": 1000} for a in "CNESW"})["order"])

    def test_estop_turns_auto_off(self):
        model = self.make_model(night=NIGHT, auto=True)
        self.attach_fake_car(model)
        self.enable_base(model, dock=True, wet=True)
        self.assertIsNotNone(wait_for(lambda: model.execution["state"] == "running"))
        result = model.estop()
        self.assertFalse(result["auto"])
        self.assertFalse(model.auto)
        self.assertFalse(model.snapshot()["auto"])
        self.assertEqual(model.execution["state"], "stopped")
        self.assertIn("비상 정지", model.execution["message"])
        # 자동 출동이 꺼졌으니 새 계획이 생기지 않는다
        plan_id = model.execution["plan_id"]
        time.sleep(0.4)
        self.assertEqual(model.execution["plan_id"], plan_id)

    def test_mock_dispatch_when_no_car(self):
        model = self.make_model(night=NIGHT, budget=2, auto=False)
        self.assertIsNone(model.car_link)
        result = model.dispatch()
        self.assertEqual(result["mode"], "mock")
        self.assertEqual(result["order"], ["E", "W"])
        self.assertIsNotNone(wait_for(lambda: model.execution["state"] == "done"))
        self.assertEqual(model.execution["mode"], "mock")
        self.assertEqual(model.execution["done"], ["E", "W"])
        self.assertEqual(sorted(model.treated), ["E", "W"])
        self.assertEqual(model.treated["E"], "2025-01-09T21:00:00")


class SensorTest(ServerBase):
    def test_sensor_baseline_dt_and_quiet_clear(self):
        model = self.make_model(night=NIGHT)
        model.sensor_telemetry(telemetry({"N": 1.0, "E": -0.5, "S": 2.0, "W": 0.0}))
        model.sensor_baseline()
        state = model.snapshot()
        self.assertTrue(state["sensor"]["baseline_ready"])
        self.assertEqual(state["sensor"]["baseline"]["E"], -0.5)

        model.sensor_telemetry(telemetry({"N": 1.0, "E": -3.0, "S": 2.0, "W": 0.0}, wet=True))
        local = model.snapshot()["sensor"]["local"]
        self.assertEqual(local["E"]["dt"], -2.5)
        self.assertFalse(local["E"]["wet"])
        self.assertTrue(local["W"]["wet"])    # 젖음 센서는 WET_ARM(기본 W) 갈래
        self.assertNotIn("N", local)          # dt 0 이고 젖지 않은 갈래는 넣지 않는다

        model.refresh_step()
        arm = model.snapshot()["step"]["arms"]["E"]
        self.assertEqual(arm["local_dt"], -2.5)
        self.assertFalse(arm["wet"])
        self.assertTrue(model.snapshot()["step"]["arms"]["W"]["wet"])
        self.assertAlmostEqual(arm["t_eff"]["h3"], round(model.step["forecast"]["h3"] - 2.5 - 2.5, 3), places=3)

        # 센서가 조용해지면 local 을 비운다(계약 5절: 10초)
        model.sensor_state["seen"] = time.time() - (model.sensor_fresh_s + 0.5)
        self.assertEqual(model.snapshot()["sensor"]["local"], {})
        model.refresh_step()
        self.assertEqual(model.snapshot()["step"]["arms"]["E"]["local_dt"], 0.0)

    def test_show_after_step_has_arm_states(self):
        model = self.make_model(night=NIGHT)
        stub = StubSensor()
        model.sensor_link = stub
        model.push_show(force=True)
        shows = [line for line in stub.lines if line.startswith("@@SHOW")]
        self.assertTrue(shows)
        payload = json.loads(shows[-1][len("@@SHOW "):])
        self.assertEqual(set(payload["arms"]), set(ARMS))
        self.assertIn(payload["arms"]["E"], ("risk1", "risk2", "risk3", "plan", "done", "off"))
        self.assertLessEqual(len(payload["msg"]), 16)
        self.assertEqual(payload["msg"], payload["msg"].encode("ascii", "ignore").decode("ascii"))
        self.assertEqual(payload["arms"]["E"], model.step["arms"]["E"]["level"])


class BaseTest(ServerBase):
    def test_board_json_loaded(self):
        model = self.make_model()
        board = model.snapshot()["board"]
        self.assertEqual(board["CENTER_X"], 582)
        self.assertEqual(board["CENTER_Y"], 480)
        self.assertEqual(board["BASE_XY"], [775, 250])           # 북동쪽 기지 차고, 출입구는 서쪽
        self.assertEqual(board["BASE_H"], 270)
        self.assertEqual(board["ROAD_MM"], 135)            # 2026-10-31 사진 실측
        self.assertEqual(board["BOARD_MM"], [925, 910])
        self.assertEqual(board["PLAZA_MM"], [297, 420])
        self.assertEqual(board["ARM_END_MM"]["N"], 480)
        self.assertEqual(board["ARM_END_MM"]["E"], 343)
        self.assertEqual(board["ARM_END_MM"]["W"], 582)
        self.assertEqual(board["ARM_END_MM"]["S"], 430)
        self.assertEqual(board["WET_ARM"], "W")
        self.assertIn("가정", board["note"])           # 차체 길이는 아직 가정값이다

    def test_wet_arm_default_and_option(self):
        model = self.make_model()
        self.assertEqual(model.wet_arm, "W")
        model.sensor_telemetry(telemetry({"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0}))
        model.sensor_baseline()
        model.sensor_telemetry(telemetry({"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0}, wet=True))
        state = model.snapshot()
        self.assertTrue(state["sensor"]["local"]["W"]["wet"])
        self.assertFalse(state["sensor"]["local"].get("E", {}).get("wet", False))
        self.assertTrue(state["sensor"]["rows"]["W"]["wet"])
        self.assertFalse(state["sensor"]["rows"]["E"]["wet"])

        other = self.make_model(wet_arm="E")
        other.sensor_telemetry(telemetry({"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0}))
        other.sensor_baseline()
        other.sensor_telemetry(telemetry({"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0}, wet=True))
        self.assertEqual(other.wet_arm, "E")
        self.assertTrue(other.snapshot()["sensor"]["local"]["E"]["wet"])

    def test_base_state_parsed(self):
        model = self.make_model()
        self.enable_base(model, dock=False, refills=5)
        model.sensor_telemetry(telemetry({"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0},
                                         dock=True, refills=6, refilling=True))
        base = model.snapshot()["base"]
        self.assertTrue(base["ok"])
        self.assertEqual(base["dock"], True)
        self.assertEqual(base["refills"], 6)
        self.assertTrue(base["refilling"])
        self.assertFalse(base["beacon"])
        self.assertEqual(base["wet_arm"], "W")

    def test_dock_false_blocks_auto_dispatch(self):
        model = self.make_model(night=NIGHT, auto=True)
        self.attach_fake_car(model)
        self.enable_base(model, dock=False, wet=True)
        time.sleep(0.4)
        self.assertIsNone(model.execution["plan_id"], "도킹 전인데 출동했습니다")

        # 도킹되면 곧바로 자동 출동한다
        self.enable_base(model, dock=True, wet=True)
        self.assertIsNotNone(wait_for(lambda: model.execution["plan_id"]))
        self.assertEqual(sorted(model.execution["order"]), ["E", "N", "S", "W"])

    def test_beacon_only_while_running(self):
        model = self.make_model(night=NIGHT, auto=False)
        stub = StubSensor()
        model.sensor_link = stub
        model.push_show(force=True)
        self.assertFalse(self.last_show(stub)["beacon"])

        car = self.attach_fake_car(model, arm_s=0.2)
        model.dispatch(order=["E"])
        self.assertIsNotNone(wait_for(lambda: model.execution["state"] == "running"))
        model.push_show(force=True)
        self.assertTrue(self.last_show(stub)["beacon"])
        self.assertTrue(model.snapshot()["base"]["beacon"])

        self.assertIsNotNone(wait_for(lambda: model.execution["state"] == "done"))
        model.push_show(force=True)
        self.assertFalse(self.last_show(stub)["beacon"])
        self.assertFalse(model.snapshot()["base"]["beacon"])
        car.stop()


class FakeBaseTest(ServerBase):
    def test_fake_car_departs_and_docks(self):
        model = self.make_model(night=NIGHT, auto=False)
        car = self.attach_fake_car(model, arm_s=0.08)
        board = model.board
        dock_x, dock_y = board["BASE_XY"]
        seen = {"depart": False, "home": False, "ys": set(), "xs": set()}
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                tel = dict(model.car_state)
                if tel.get("phase") == "depart":
                    seen["depart"] = True
                if tel.get("phase") == "home":
                    seen["home"] = True
                if tel.get("y") is not None:
                    seen["ys"].add(tel["y"])
                if tel.get("x") is not None:
                    seen["xs"].add(tel["x"])
                time.sleep(0.005)

        self.addCleanup(stop.set)
        threading.Thread(target=watch, daemon=True).start()
        model.dispatch(order=["E", "S"])
        self.assertIsNotNone(wait_for(lambda: model.execution["state"] == "done"))
        self.assertIsNotNone(wait_for(lambda: model.car_state["state"] == "idle"))
        stop.set()
        car.stop()
        self.assertTrue(seen["depart"], "기지 출발 단계가 없습니다")
        self.assertTrue(seen["home"], "기지 귀환 단계가 없습니다")
        self.assertGreater(len(seen["ys"]), 2, "차가 y 축으로 움직이지 않았습니다")
        self.assertGreater(len(seen["xs"]), 1, "차가 x 축으로 움직이지 않았습니다")
        self.assertEqual(model.car_state["x"], dock_x)
        self.assertEqual(model.car_state["y"], dock_y)

    def test_fake_base_follows_car_and_refills(self):
        model = self.make_model(night=NIGHT, auto=False)
        fake = srv.FakeSensorSerial(model=model, period=5.0, beats=0)
        self.addCleanup(fake.close)
        self.assertTrue(fake.payload()["dock"])
        self.assertEqual(fake.refills, 3)

        model.car_state["state"] = "run"
        self.assertFalse(fake.payload()["dock"])
        model.car_state["state"] = "idle"
        body = fake.payload()
        self.assertTrue(body["dock"])
        self.assertTrue(body["refills"] >= 4, "귀환했는데 보충 횟수가 늘지 않았습니다")


class StationTest(ServerBase):
    def test_default_station_is_suwon_119(self):
        old = os.environ.get("GOSAEK_ENGINE")
        os.environ["GOSAEK_ENGINE"] = "tests.fake_engine"
        try:
            engine, station, error = srv.load_engine("119")
        finally:
            if old is None:
                os.environ.pop("GOSAEK_ENGINE", None)
            else:
                os.environ["GOSAEK_ENGINE"] = old
        self.assertIsNotNone(engine)
        self.assertTrue(engine.available())
        self.assertEqual(engine.stn, "119")
        self.assertEqual(station["id"], "119")
        self.assertEqual(station["label"], "수원 119")
        self.assertFalse(station["replaced"])
        self.assertIsNone(error)

    def test_missing_119_falls_back_to_108(self):
        old = os.environ.get("GOSAEK_ENGINE")
        os.environ["GOSAEK_ENGINE"] = "tests.fake_engine:Only108Engine"
        try:
            engine, station, error = srv.load_engine("119")
        finally:
            if old is None:
                os.environ.pop("GOSAEK_ENGINE", None)
            else:
                os.environ["GOSAEK_ENGINE"] = old
        self.assertIsNotNone(engine)
        self.assertTrue(engine.available())
        self.assertEqual(engine.stn, "108")
        self.assertEqual(station["id"], "108")
        self.assertTrue(station["replaced"])
        self.assertIn("108", station["label"])
        self.assertIn("119", station["note"])
        self.assertTrue(error)

        model = self.make_model(engine=engine, station=station, engine_error=error)
        state = model.snapshot()
        self.assertTrue(state["station"]["replaced"])
        self.assertIn("108", state["station"]["label"])


class HttpTest(ServerBase):
    def request(self, port, path, body=None):
        url = "http://127.0.0.1:%d%s" % (port, path)
        if body is None:
            req = urllib.request.Request(url)
        else:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def post(self, port, path, body):
        status, raw = self.request(port, path, body)
        return status, json.loads(raw.decode("utf-8"))

    def test_vision_photo_plans_the_route_and_dispatches(self):
        from tests.test_vision import N_SNOW, board, floor, photo
        model = self.make_model(night=NIGHT)
        self.attach_fake_car(model)
        port = self.start_http(model)
        clean = srv.vision.to_data_url(photo(board(glare=True)))
        snowy = srv.vision.to_data_url(photo(board(snow=N_SNOW)))

        status, body = self.post(port, "/api/vision/detect", {"image": srv.vision.to_data_url(floor())})
        self.assertEqual(status, 422, "도로가 없는 사진을 판정했습니다")

        status, body = self.post(port, "/api/vision/detect", {"image": clean})
        self.assertEqual(status, 200, body)
        self.assertFalse(body["decision"]["go"])
        self.assertIsNone(body["route"])
        self.assertIsNone(body["dispatch"])

        status, body = self.post(port, "/api/vision/detect", {"image": snowy})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["decision"]["go"])
        self.assertEqual(body["route"]["order"], ["N"])               # 눈은 N 갈래에만 있다
        self.assertEqual(body["route"]["path"][0][:2], [775, 250])   # 경로는 기지 차고에서 시작해
        self.assertEqual(body["route"]["path"][-1][:2], [775, 250])  # 기지로 돌아온다
        self.assertTrue(body["view"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(body["dispatch"]["source"], "vision")
        self.assertEqual(model.execution["order"], ["N"])
        self.assertIsNone(body["eye"], "키가 없으면 Claude에게 묻지 않는다")

    def test_claude_thinking_shows_live_and_disagreement_sweeps_every_arm(self):
        from tests.test_vision import N_SNOW, board, photo
        model = self.make_model(night=NIGHT, claude=True)
        port = self.start_http(model)
        live = []
        def judge(img, turns, on_thinking):
            on_thinking("N 도로와 E 도로에 흰 알갱이가 보인다.")
            live.append(model.snapshot()["vision_live"])
            return {"usable": True, "arms": {"C": False, "N": True, "E": True, "S": False, "W": False},
                    "note": "N·E 도로에 눈", "thinking": "N 도로와 E 도로에 흰 알갱이가 보인다.", "secs": 6.0}
        snowy = srv.vision.to_data_url(photo(board(snow=N_SNOW)))
        with mock.patch.object(srv.claude_vision, "judge", judge):
            status, body = self.post(port, "/api/vision/detect", {"image": snowy, "go": False})
        self.assertEqual(status, 200, body)
        self.assertEqual(live, [{"thinking": "N 도로와 E 도로에 흰 알갱이가 보인다."}])
        self.assertIsNone(model.snapshot()["vision_live"], "판정이 끝나면 실시간 사고 요약을 지운다")
        self.assertIn("엇갈림", body["decision"]["text"])
        self.assertEqual(sorted(body["route"]["order"]), ["E", "N", "S", "W"])
        self.assertEqual(body["eye"]["note"], "N·E 도로에 눈")

        def fail(img, turns, on_thinking):
            raise RuntimeError("HTTP 529 overloaded")
        with mock.patch.object(srv.claude_vision, "judge", fail):
            status, body = self.post(port, "/api/vision/detect", {"image": snowy, "go": False})
        self.assertEqual(body["route"]["order"], ["N"], "Claude가 실패하면 규칙만으로 판단한다")
        self.assertIn("Claude 판정 실패", body["decision"]["text"])
        self.assertEqual(model.snapshot()["vision"]["route"]["order"], ["N"])

    def test_sweep_all_dispatches_every_arm_in_the_best_order(self):
        model = self.make_model(night=NIGHT)
        self.attach_fake_car(model, arm_s=0.3)
        port = self.start_http(model)
        status, body = self.post(port, "/api/sweep", {})
        self.assertEqual(status, 200, body)
        self.assertEqual(sorted(body["route"]["order"]), ["E", "N", "S", "W"])
        self.assertEqual(model.execution["order"], body["route"]["order"])     # 고른 순서 그대로 보낸다
        self.assertEqual(body["dispatch"]["source"], "sweep")
        status, body = self.post(port, "/api/sweep", {})
        self.assertEqual(status, 409, "출동 중에 또 보냈습니다")

    def test_state_api_and_pages(self):
        model = self.make_model(night=NIGHT)
        port = self.start_http(model)

        status, raw = self.request(port, "/api/state")
        self.assertEqual(status, 200)
        state = json.loads(raw.decode("utf-8"))
        self.assertIn("step", state)
        self.assertIn("monitor_url", state)
        self.assertEqual(state["station"]["id"], "119")

        status, raw = self.request(port, "/")
        self.assertEqual(status, 200)
        html = raw.decode("utf-8")
        self.assertIn("자동 출동", html)

        status, raw = self.request(port, "/monitor")
        self.assertEqual(status, 200)
        monitor = raw.decode("utf-8")
        for page in (html, monitor):      # 모든 화면이 web/app/globals.css 와 같은 흑백 색상표를 쓴다
            self.assertIn("--carbon-black:#212529", page)
            self.assertIn("--bright-snow:#f8f9fa", page)
            self.assertNotIn("blue", page)
        self.assertIn("1920", monitor)
        self.assertIn("setInterval(refresh, 1000)", monitor)
        self.assertNotIn("cdn.", monitor.lower())
        self.assertNotIn("<button", monitor.lower())

        status, _raw = self.request(port, "/%EC%97%86%EB%8A%94%EA%B2%BD%EB%A1%9C")
        self.assertEqual(status, 404)

    def test_font_route_and_pretendard(self):
        model = self.make_model(night=NIGHT)
        port = self.start_http(model)

        url = "http://127.0.0.1:%d/static/fonts/PretendardVariable.woff2" % port
        with urllib.request.urlopen(url, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("Content-Type"), "font/woff2")
            self.assertGreater(len(response.read()), 1000)

        # 이 경로 밖으로는 나가지 못한다
        status, _raw = self.request(port, "/static/fonts/..%2F..%2Fboard.json")
        self.assertEqual(status, 404)

        for path in ("/", "/monitor"):
            status, raw = self.request(port, path)
            self.assertEqual(status, 200)
            html = raw.decode("utf-8")
            self.assertIn("@font-face", html)
            self.assertIn("Pretendard Variable", html)
            self.assertIn("/static/fonts/PretendardVariable.woff2", html)
            self.assertNotIn("cdn.", html.lower())

        status, raw = self.request(port, "/monitor")
        monitor = raw.decode("utf-8")
        self.assertIn("제설 기지", monitor)
        self.assertIn("BASE_XY", monitor)                 # 기지·차고 위치는 board.json에서 읽는다
        self.assertIn("beacon", monitor)
        self.assertIn("depart", monitor)

    def test_api_auto_budget_and_stop(self):
        model = self.make_model(night=NIGHT, auto=True)
        self.attach_fake_car(model)
        port = self.start_http(model)

        status, body = self.post(port, "/api/auto", {"on": False})
        self.assertEqual(status, 200)
        self.assertFalse(body["auto"])
        self.assertFalse(body["state"]["auto"])

        status, body = self.post(port, "/api/budget", {"budget": 3})
        self.assertEqual(status, 200)
        self.assertEqual(body["budget"], 3)
        self.assertEqual(body["state"]["budget"], 3)

        status, body = self.post(port, "/api/budget", {"budget": 99})
        self.assertEqual(body["budget"], 4)

        status, body = self.post(port, "/api/car/stop", {})
        self.assertEqual(status, 200)
        self.assertFalse(body["auto"])
        self.assertFalse(body["state"]["auto"])

        status, body = self.post(port, "/api/replay/step", {"hours": 2})
        self.assertEqual(body["index"], 2)

        status, body = self.post(port, "/api/replay", {"night": "2025-01-10"})
        self.assertEqual(body["night"], "2025-01-10")

        status, body = self.post(port, "/api/replay/auto", {"on": True, "sec_per_hour": 1.0})
        self.assertTrue(body["auto"])
        self.assertTrue(wait_for(lambda: model.index >= 1, timeout=4))

        status, body = self.post(port, "/api/sensors/baseline", {})
        self.assertTrue(body["ok"])
        self.assertTrue(body["state"]["sensor"]["baseline_ready"])

        status, body = self.post(port, "/api/car/home", {})
        self.assertTrue(body["ok"])

        status, body = self.post(port, "/api/reset", {})
        self.assertTrue(body["ok"])
        self.assertEqual(body["state"]["budget"], 2)
        self.assertEqual(body["state"]["treated"], {})
        self.assertEqual(body["state"]["execution"]["state"], "idle")


class SilentCar(object):
    """명령은 받지만 아무 응답도 보내지 않는 차(ack 거절 시험용)."""

    mode = "udp"

    def __init__(self):
        self.sent = []

    def ok(self):
        return True

    def age(self):
        return 0.0

    def send(self, msg):
        self.sent.append(msg)
        return True

    def stop(self):
        pass


class RecordingModel(object):
    """차가 보낸 메시지를 순서대로 기록한다."""

    def __init__(self, model):
        self.inner = model
        self.messages = []

    def car_message(self, body, addr=None):
        self.messages.append(dict(body))
        return self.inner.car_message(body, addr)


class FakeCarTest(ServerBase):
    def test_fake_car_sends_telemetry_and_events(self):
        model = self.make_model(night=NIGHT, auto=False)
        car = self.attach_fake_car(model, arm_s=0.01)
        model.dispatch(order=["E"])
        self.assertIsNotNone(wait_for(lambda: model.execution["state"] == "done"))
        self.assertIn("E", model.treated)
        # 차는 arm_done 뒤에 plan_done 과 유휴 텔레메트리를 한 번 더 보낸다.
        self.assertIsNotNone(wait_for(lambda: model.car_state["state"] == "idle"))
        self.assertEqual(model.car_state["state"], "idle")
        self.assertEqual([model.car_state["x"], model.car_state["y"]], model.board["BASE_XY"])
        self.assertEqual(model.car_state["arm"], None)
        car.stop()
        self.assertTrue(any("갈래 살포 완료" in e["text"] for e in model.events))

    def test_fake_car_follows_protocol_order(self):
        """ack → plan_start → arm_start → spray_on/off → arm_done → plan_done."""
        model = self.make_model(night=NIGHT, auto=False)
        record = RecordingModel(model)
        car = srv.FakeCar(record, arm_s=0.02)
        model.car_link = car
        self.addCleanup(car.stop)
        model.dispatch(order=["E"])
        # 마지막 plan_done 까지 받았는지 보고난 뒤에 순서를 확인한다(서버는 arm_done 에 완료 처리).
        self.assertIsNotNone(wait_for(
            lambda: any(m.get("e") == "plan_done" for m in record.messages), timeout=4))
        messages = list(record.messages)
        self.assertEqual(messages[0]["t"], "ack")
        self.assertTrue(messages[0]["ok"])
        events = [m for m in messages if m.get("t") == "evt"]
        self.assertEqual([m["e"] for m in events],
                         ["plan_start", "arm_start", "spray_on", "spray_off",
                          "arm_done", "plan_done"])
        for item in events:
            self.assertIn("arm", item)
        self.assertEqual([m["arm"] for m in events if m["e"] == "arm_start"], ["E"])

    def test_fake_car_rejects_running_and_duplicate_plan(self):
        model = self.make_model(night=NIGHT, auto=False)
        record = RecordingModel(model)
        car = srv.FakeCar(record, arm_s=0.3)
        model.car_link = car
        self.addCleanup(car.stop)
        result = model.dispatch(order=["E"])
        self.assertIsNotNone(wait_for(lambda: model.execution["mode"] == "car"))
        car.send({"t": "plan", "seq": 99, "order": ["W"]})       # 실행 중
        car.send({"t": "plan", "seq": result["seq"], "order": ["W"]})  # 중복 seq
        acks = [m for m in record.messages if m.get("t") == "ack"]
        self.assertTrue(acks[0]["ok"])
        self.assertEqual(acks[1]["ok"], False)
        self.assertEqual(acks[1]["reason"], "실행 중")
        self.assertEqual(acks[2]["reason"], "중복")

    def test_car_ack_reject_fails_plan(self):
        model = self.make_model(night=NIGHT, auto=False)
        silent = SilentCar()
        model.car_link = silent
        result = model.dispatch(order=["E"])
        self.assertEqual(silent.sent[-1]["t"], "plan")
        model.car_message({"t": "ack", "seq": result["seq"], "ok": False, "reason": "실행 중"})
        self.assertIsNotNone(wait_for(lambda: model.execution["state"] == "failed"))
        self.assertIn("거절", model.execution["message"])

    def test_udp_datagram_is_single_json_without_newline(self):
        model = self.make_model(night=NIGHT, auto=False)
        link = srv.CarLink(model, listen_port=0).open()
        self.addCleanup(link.stop)
        port = link.sock.getsockname()[1]
        link.start()
        car = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        car.settimeout(2.0)
        self.addCleanup(car.close)
        car.sendto(json.dumps({"t": "hello", "id": "car1"}).encode("utf-8"),
                   ("127.0.0.1", port))
        self.assertIsNotNone(wait_for(lambda: link.addr is not None, timeout=3))
        link.send({"t": "plan", "seq": 7, "order": ["E"]})
        plan = None
        for _ in range(6):
            data, _addr = car.recvfrom(4096)
            self.assertNotIn(b"\n", data)
            body = json.loads(data.decode("utf-8"))
            if body.get("t") == "plan":
                plan = body
                break
        self.assertIsNotNone(plan, "plan 데이터그램을 받지 못했습니다")
        self.assertEqual(plan["order"], ["E"])

    def test_warns_when_mac_is_ipv6_only_clat(self):
        """차 hello는 왔는데 맥 출발 주소가 CLAT(192.0.0.x)이면 명령이 안 간다고 알린다."""
        model = self.make_model(night=NIGHT, auto=False)
        link = srv.CarLink(model, listen_port=0)
        real = srv.local_ip_for
        srv.local_ip_for = lambda ip, port: "192.0.0.2"
        try:
            link._check_route("172.20.10.5")
        finally:
            srv.local_ip_for = real
        self.assertTrue(any("CLAT" in e["text"] for e in model.events))
        before = len(model.events)
        link._check_route("127.0.0.1")              # 정상 경로면 조용하다
        self.assertEqual(len(model.events), before)


if __name__ == "__main__":
    unittest.main()
