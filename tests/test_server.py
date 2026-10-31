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

HERE = os.path.dirname(os.path.abspath(__file__))
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


def telemetry(t_map, rh_map=None, ok=True, wet=False):
    rh_map = rh_map or {a: 80 for a in ARMS}
    return {"t": dict(t_map), "rh": dict(rh_map), "ok": {a: bool(ok) for a in ARMS},
            "wet_raw": 900 if wet else 2400, "wet": bool(wet), "light_raw": 1200,
            "warn": bool(wet), "up": 7}


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
    def test_auto_dispatch_arm_done_treated_then_next(self):
        """재생 → 자동 출동 → arm_done → treated 제외 → 다음 출동."""
        model = self.make_model(night=NIGHT, budget=1, auto=True)
        self.attach_fake_car(model)
        self.assertTrue(model.snapshot()["step"]["dispatch"]["recommend"])

        first = wait_for(lambda: model.execution["plan_id"] if model.execution["order"] == ["E"] else None)
        self.assertIsNotNone(first, "자동 출동이 일어나지 않았습니다")
        self.assertEqual(first, "P1")
        self.assertEqual(model.execution["mode"], "car")

        # 차가 arm_done 을 보내면 treated[E] = 재생 시각 + 3시간
        self.assertIsNotNone(wait_for(lambda: model.treated.get("E")))
        self.assertEqual(model.treated["E"], "2025-01-09T21:00:00")

        # 처리된 갈래는 다음 step 에서 제외되고, 다음 출동은 남은 W 로 간다
        wait_for(lambda: (model.step or {}).get("arms", {}).get("E", {}).get("level") == "done")
        self.assertEqual(model.step["arms"]["E"]["level"], "done")
        self.assertFalse(model.step["arms"]["E"]["candidate"])
        second = wait_for(lambda: model.execution["plan_id"] == "P2" and model.execution["order"] == ["W"])
        self.assertIsNotNone(second, "처리된 갈래를 뺀 다음 출동이 없습니다")

        # 두 갈래가 다 처리되면 더 출동하지 않는다
        self.assertIsNotNone(wait_for(lambda: model.treated.get("W")))
        wait_for(lambda: (model.step or {}).get("dispatch", {}).get("recommend") is False)
        self.assertFalse(model.step["dispatch"]["recommend"])
        self.assertEqual(model.step["dispatch"]["order"], [])
        self.assertEqual(model.execution["plan_id"], "P2")

    def test_estop_turns_auto_off(self):
        model = self.make_model(night=NIGHT, auto=True)
        self.attach_fake_car(model)
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
        self.assertTrue(local["E"]["wet"])
        self.assertNotIn("N", local)          # dt 0 이고 젖지 않은 갈래는 넣지 않는다

        model.refresh_step()
        arm = model.snapshot()["step"]["arms"]["E"]
        self.assertEqual(arm["local_dt"], -2.5)
        self.assertTrue(arm["wet"])
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
        self.assertIn("--deep-space-blue", html)
        self.assertIn("--light-blue", html)
        self.assertIn("자동 출동", html)

        status, raw = self.request(port, "/monitor")
        self.assertEqual(status, 200)
        monitor = raw.decode("utf-8")
        self.assertIn("--deep-space-blue", monitor)
        self.assertIn("--yale-blue-3", monitor)
        self.assertIn("--light-blue", monitor)
        self.assertIn("--sky-blue-light", monitor)
        self.assertIn("1920", monitor)
        self.assertIn("setInterval(refresh, 1000)", monitor)
        self.assertNotIn("cdn.", monitor.lower())
        self.assertNotIn("<button", monitor.lower())

        status, _raw = self.request(port, "/%EC%97%86%EB%8A%94%EA%B2%BD%EB%A1%9C")
        self.assertEqual(status, 404)

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
        self.assertEqual(model.car_state["x"], 450)
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


if __name__ == "__main__":
    unittest.main()
