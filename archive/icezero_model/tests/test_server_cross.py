"""서버(icezero_server.py) 시험 — 하드웨어 없이 돈다.

두 갈래로 확인한다.
1. 프로세스 안에서 Model + ThreadingHTTPServer 를 띄우고 가짜 엔진·가짜 Pico 를 주입한다.
2. 실제 CLI 로 서버를 임의 포트에 띄운다(--no-llm --pico-serial none). 실제 엔진이 있으면
   실제 모델로, 없으면 '엔진 없음' 안내 상태로 확인한다.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER_DIR = os.path.join(ROOT, "server")
SERVER_PY = os.path.join(SERVER_DIR, "icezero_server.py")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import icezero_server as srv  # noqa: E402

ARMS = ("N", "E", "S", "W")
NIGHT = "2025-01-09"


# ---------------------------------------------------------------------------
# 가짜 엔진 — 계약 3절 step JSON 과 같은 형식
# ---------------------------------------------------------------------------


def _timeline(night):
    """18:00 부터 다음 날 09:00 까지 16개."""
    import datetime
    start = datetime.datetime.strptime(night + "T18:00:00", "%Y-%m-%dT%H:%M:%S")
    return [(start + datetime.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S")
            for i in range(16)]


class FakeEngine(object):
    """Engine 과 같은 메서드 이름. 값은 시각에 따라 단조롭게 변한다."""

    def __init__(self, nights=(NIGHT, "2025-01-10")):
        self._nights = [{"night": n, "t18": 4.0, "t_min": -3.0, "score": 9.0} for n in nights]
        self.loaded = False
        self.calls = []

    def load(self):
        self.loaded = True
        return self

    def nights(self, year=2025):
        return list(self._nights)

    def timeline(self, night):
        return _timeline(night)

    def step(self, ts, sensor=None, reports=None, budget=2):
        self.calls.append({"ts": ts, "sensor": sensor, "reports": reports, "budget": budget})
        hour = int(str(ts)[11:13])
        step_no = (hour - 18) % 24
        ground = round(6.0 - 0.6 * step_no, 3)
        pred = {"h0": round(ground - 0.2, 3), "h1": round(ground - 0.6, 3),
                "h3": round(ground - 1.1, 3), "h6": round(ground - 0.9, 3)}
        confirmed = []
        if reports:
            for r in reports:
                if isinstance(r, str) and r.strip().upper() in ARMS:
                    confirmed.append(r.strip().upper())
        risk = {"N": 0.581, "E": 0.914, "S": 0.521, "W": 0.792}
        p_base = {"N": 0.20, "E": 0.90, "S": 0.15, "W": 0.55}
        offset = 0.0
        source_default = "model"
        if sensor and sensor.get("t_bridge") is not None:
            offset = round(float(sensor["t_bridge"]) - pred["h0"] - 2.5, 3)
        arms = {}
        for arm in ARMS:
            t_eff = {}
            for h in ("h0", "h1", "h3", "h6"):
                t_eff[h] = round(pred[h] - 2.5 * (1 if arm == "E" else 0) + offset, 3)
            p_main = min(0.99, max(0.0, round(p_base[arm] + 0.02 * step_no, 3)))
            p = {"h0": round(max(0.0, p_main - 0.1), 3), "h1": p_main,
                 "h3": round(min(0.99, p_main + 0.03), 3), "h6": round(max(0.0, p_main - 0.05), 3)}
            p_max = max(p["h1"], p["h3"], p["h6"])
            level = "risk3" if p_max >= 0.6 else ("risk2" if p_max >= 0.3 else "risk1")
            priority = round(risk[arm] + (0.5 if arm in confirmed else 0.0), 3)
            arms[arm] = {
                "name": {"N": "테헤란로115길", "E": "올림픽로", "S": "역삼로107길", "W": "테헤란로"}[arm],
                "label": "bridge" if arm == "E" else "general",
                "structure": 1 if arm == "E" else 0,
                "shadow_index": 0.38 if arm == "W" else 0.0,
                "risk_v2": risk[arm], "risk_v2_pct": 0.86,
                "t_eff": t_eff, "p_freeze": p, "p_max": p_max,
                "source": ("sensor" if (arm == "E" and offset) else source_default),
                "level": level, "candidate": bool(p_max >= 0.5 or arm in confirmed),
                "priority": priority, "reasons": ["가짜 엔진"],
            }
        cands = [a for a in ARMS if arms[a]["candidate"]]
        order = sorted(cands, key=lambda a: (-arms[a]["priority"], ARMS.index(a)))[:max(0, int(budget))]
        return {
            "time": ts,
            "obs": {"temp": round(ground + 1.5, 3), "humidity": 82, "wind": 1.2,
                    "precip": 0.0, "snow": 0.0, "ground_temp": ground},
            "forecast": pred,
            "arms": arms,
            "dispatch": {"recommend": bool(order), "selected": order, "order": order,
                         "budget": budget, "threshold": 0.5},
            "model": {"name": "가짜 엔진(시험)", "rmse": {"h3": 1.1},
                      "persistence_rmse": {"h3": 1.6}, "brier": {"h3": 0.12}},
            "notes": ["가짜 엔진"],
        }


class ClocklessEngine(FakeEngine):
    """step 이 항상 실패하는 엔진(오류 표시 시험)."""

    def step(self, ts, sensor=None, reports=None, budget=2):
        raise RuntimeError("모델 파일이 깨졌습니다")


# ---------------------------------------------------------------------------
# 가짜 Pico — 시리얼 대신 내부 큐
# ---------------------------------------------------------------------------


class FakePico(object):
    """pyserial 과 같은 readline/write/flush/close. 받은 명령을 commands 에 쌓는다."""

    def __init__(self, done_after=0.05):
        self.done_after = done_after
        self._tx = []
        self._lock = threading.Lock()
        self.commands = []

    def readline(self):
        with self._lock:
            if self._tx:
                return self._tx.pop(0)
        return b""

    def write(self, data):
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            self.commands.append(line)
            if line.startswith("@@SPRAY"):
                body = json.loads(line[len("@@SPRAY"):].strip())
                if self.done_after is not None:
                    threading.Timer(self.done_after, self._done,
                                    args=(body.get("seq"), body.get("arm"))).start()
            elif line.startswith("@@STOP"):
                self._push({"e": "stopped", "seq": 0, "arm": None})
        return len(data)

    def flush(self):
        return None

    def close(self):
        return None

    def _push(self, body):
        with self._lock:
            self._tx.append(("@@EVT " + json.dumps(body, ensure_ascii=False) + "\n").encode("utf-8"))

    def _done(self, seq, arm):
        self._push({"e": "spray_done", "seq": seq, "arm": arm})

    def spray_lines(self):
        return [c for c in self.commands if c.startswith("@@SPRAY")]

    def has_stop(self):
        return any(c.startswith("@@STOP") for c in self.commands)


# ---------------------------------------------------------------------------
# 공통 도구
# ---------------------------------------------------------------------------


def http_get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post(base, path, body=None):
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def wait_for(fn, timeout=8.0, label="조건"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = fn()
        except Exception as e:  # 서버가 아직 응답하지 않을 수 있다
            last = e
        else:
            if last:
                return last
        time.sleep(0.05)
    raise AssertionError("%s 이 %.1f초 안에 만족되지 않았습니다(마지막 값 %r)" % (label, timeout, last))


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LiveServer(object):
    """프로세스 안에서 서버를 띄우는 도우미."""

    def __init__(self, engine=None, pico=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.events = os.path.join(self.tmp.name, "events.jsonl")
        self.engine = engine if engine is not None else FakeEngine()
        self.model = srv.Model(engine=self.engine, no_llm=True, events_path=self.events)
        self.link = None
        if pico is not None:
            self.link = srv.PicoLink(self.model, pico, "가짜 Pico", "fake")
            self.model.pico = self.link
            self.model.pico_state["mode"] = "fake"
            self.model.pico_state["port"] = "가짜 Pico"
            self.link.start()
        self.httpd = srv.serve(self.model, "127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.model.stop()
        thread = getattr(self.model, "_dispatch_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=8)  # 실행 스레드가 끝난 뒤에 임시 폴더를 지운다
        if self.link is not None:
            self.link.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()


class ServerBase(unittest.TestCase):
    pico_factory = None

    def setUp(self):
        self.pico = self.pico_factory() if self.pico_factory else None
        self.server = LiveServer(pico=self.pico)
        self.model = self.server.model
        self.base = self.server.base
        self._timeout = srv.SPRAY_TIMEOUT_S

    def tearDown(self):
        srv.SPRAY_TIMEOUT_S = self._timeout
        self.server.close()

    def state(self):
        return http_get(self.base, "/api/state")

    def post(self, path, body=None):
        return http_post(self.base, path, body)


# ---------------------------------------------------------------------------
# 기본 흐름(가짜 엔진, Pico 없음)
# ---------------------------------------------------------------------------


class ServerFlowTest(ServerBase):
    def test_state_has_step_json(self):
        st = self.state()
        self.assertTrue(st["engine"]["ok"])
        self.assertIsNone(st["engine"]["error"])
        step = st["step"]
        for key in ("time", "obs", "forecast", "arms", "dispatch", "model", "notes"):
            self.assertIn(key, step)
        for arm in ARMS:
            self.assertIn(arm, step["arms"])
            self.assertIn("p_max", step["arms"][arm])
            self.assertIn("t_eff", step["arms"][arm])
        self.assertEqual(st["replay"]["night"], NIGHT)
        self.assertEqual(st["replay"]["total"], 16)
        self.assertEqual(st["replay"]["ts"], NIGHT + "T18:00:00")
        self.assertEqual(st["pico"]["mode"], "none")
        self.assertFalse(st["pico"]["ok"])

    def test_dashboard_served_without_cdn(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
        self.assertIn("십자 사거리", html)
        self.assertIn("/api/state", html)
        self.assertNotIn("http://cdn", html)
        self.assertNotIn("https://cdn", html)
        self.assertNotIn("결빙 확정", html)

    def test_replay_night_and_step(self):
        status, body = self.post("/api/replay", {"night": "2025-01-10"})
        self.assertEqual(status, 200)
        self.assertEqual(body["night"], "2025-01-10")
        self.assertEqual(body["state"]["replay"]["ts"], "2025-01-10T18:00:00")

        status, body = self.post("/api/replay/step", {"hours": 3})
        self.assertEqual(status, 200)
        self.assertEqual(body["index"], 3)
        self.assertEqual(body["ts"], "2025-01-10T21:00:00")

        # 범위를 넘어가면 끝에서 멈춘다.
        status, body = self.post("/api/replay/step", {"hours": 99})
        self.assertEqual(body["index"], 15)
        status, body = self.post("/api/replay/step", {"hours": -99})
        self.assertEqual(body["index"], 0)

    def test_replay_auto_advances(self):
        status, body = self.post("/api/replay/auto", {"on": True, "sec_per_hour": 0.2})
        self.assertEqual(status, 200)
        self.assertTrue(body["auto"])
        wait_for(lambda: self.state()["replay"]["index"] >= 2, timeout=5, label="자동 재생 진행")
        self.post("/api/replay/auto", {"on": False})
        st = self.state()
        idx = st["replay"]["index"]
        time.sleep(0.5)
        self.assertEqual(self.state()["replay"]["index"], idx)

    def test_report_confirm_updates_dispatch(self):
        status, body = self.post("/api/report", {"text": "올림픽로 교량이 미끄럽습니다"})
        self.assertEqual(status, 200)
        self.assertEqual(body["engine"], "rule")
        pending = self.state()["pending_report"]
        self.assertEqual(pending["rule"]["arms"], ["E"])
        self.assertIn("error", pending)

        status, body = self.post("/api/report/confirm", {"arms": ["E"], "budget": 3})
        self.assertEqual(status, 200)
        st = self.state()
        self.assertIsNone(st["pending_report"])
        self.assertEqual(len(st["reports"]), 1)
        self.assertEqual(st["reports"][0]["arms"], ["E"])
        self.assertEqual(st["budget"], 3)
        self.assertIn("E", st["step"]["dispatch"]["order"])
        # 확인된 제보는 우선순위를 올린다.
        self.assertGreater(st["step"]["arms"]["E"]["priority"], 0.914)
        self.assertEqual(st["execution"]["state"], "idle")

    def test_report_reject_keeps_state(self):
        self.post("/api/report", {"text": "테헤란로 그늘이 얼음 같아요"})
        status, _ = self.post("/api/report/reject", {})
        self.assertEqual(status, 200)
        st = self.state()
        self.assertIsNone(st["pending_report"])
        self.assertEqual(st["reports"], [])

    def test_budget_bounds(self):
        status, body = self.post("/api/budget", {"budget": 9})
        self.assertEqual(body["budget"], 4)
        status, body = self.post("/api/budget", {"budget": -2})
        self.assertEqual(body["budget"], 0)
        status, body = self.post("/api/budget", {"budget": 2})
        self.assertEqual(body["budget"], 2)
        status, body = self.post("/api/budget", {"budget": "이상한 값"})
        self.assertEqual(status, 400)

    def test_sensor_manual_applied(self):
        status, body = self.post("/api/sensor", {"use_sensor": True, "t_bridge": -5.0})
        self.assertEqual(status, 200)
        st = self.state()
        self.assertTrue(st["sensor"]["use_sensor"])
        self.assertEqual(st["sensor"]["source"], "manual")
        self.assertEqual(st["sensor"]["t_bridge"], -5.0)
        # 가짜 엔진이 센서 값을 받았는지 확인한다.
        self.assertTrue(any(c["sensor"] for c in self.server.engine.calls))
        self.assertEqual(st["step"]["arms"]["E"]["source"], "sensor")

        self.post("/api/sensor", {"use_sensor": False})
        st = self.state()
        self.assertEqual(st["sensor"]["source"], "none")
        self.assertIsNone(st["sensor"]["t_bridge"])

    def test_approve_and_mock_dispatch(self):
        status, body = self.post("/api/budget", {"budget": 2})
        self.assertEqual(body["budget"], 2)
        status, body = self.post("/api/plan/approve", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["plan_id"], "P1")
        self.assertEqual(len(body["order"]), 2)
        self.assertFalse(body["sent"])  # Pico 없음

        status, body = self.post("/api/dispatch", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["mode"], "mock")
        wait_for(lambda: self.state()["execution"]["state"] == "done", timeout=8, label="모의 실행 완료")
        st = self.state()
        self.assertEqual(st["execution"]["mode"], "mock")
        self.assertEqual(st["execution"]["done"], st["execution"]["order"])

    def test_dispatch_requires_approved_plan(self):
        status, body = self.post("/api/dispatch", {})
        self.assertEqual(status, 409)
        self.assertIn("승인", body["error"])

    def test_estop_and_reset(self):
        self.post("/api/plan/approve", {})
        self.post("/api/dispatch", {})
        status, body = self.post("/api/estop", {})
        self.assertEqual(status, 200)
        wait_for(lambda: self.state()["execution"]["state"] == "stopped", timeout=8, label="비상 정지")
        status, body = self.post("/api/reset", {})
        self.assertEqual(status, 200)
        st = self.state()
        self.assertEqual(st["execution"]["state"], "idle")
        self.assertIsNone(st["approved"])
        self.assertEqual(st["reports"], [])
        self.assertEqual(st["replay"]["index"], 0)

    def test_events_written_to_jsonl(self):
        self.post("/api/report", {"text": "역삼로107길 사고"})
        wait_for(lambda: os.path.exists(self.server.events), timeout=3, label="events.jsonl 생성")
        with open(self.server.events, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertTrue(lines)
        self.assertIn("report", [e["kind"] for e in lines])

    def test_unknown_route_404(self):
        status, body = self.post("/api/nope", {})
        self.assertEqual(status, 404)

    def test_engine_step_failure_is_reported(self):
        broken = LiveServer(engine=ClocklessEngine())
        try:
            with urllib.request.urlopen(broken.base + "/api/state", timeout=5) as r:
                st = json.loads(r.read().decode("utf-8"))
            self.assertIsNone(st["step"])
            self.assertFalse(st["engine"]["ok"])
            self.assertIn("step", st["engine"]["error"])
        finally:
            broken.close()


# ---------------------------------------------------------------------------
# Pico 시리얼 경로(가짜 Pico 주입)
# ---------------------------------------------------------------------------


class PicoSerialTest(ServerBase):
    def setUp(self):
        self.pico = FakePico(done_after=0.05)
        self.server = LiveServer(pico=self.pico)
        self.model = self.server.model
        self.base = self.server.base
        self._timeout = srv.SPRAY_TIMEOUT_S
        # 텔레메트리가 살아 있는 상태로 만든다(pico_ok).
        self.model.pico_telemetry({"t_bridge": -4.0, "t_air": -1.0, "wet": True,
                                   "wet_raw": 900, "warn": True, "busy": False, "up": 1})
        wait_for(lambda: self.state()["pico"]["ok"], timeout=5, label="Pico 텔레메트리")

    def test_telemetry_used_for_sensor(self):
        self.post("/api/sensor", {"use_sensor": True})
        wait_for(lambda: self.state()["sensor"]["source"] == "pico", timeout=5, label="Pico 센서 사용")
        st = self.state()
        self.assertEqual(st["sensor"]["t_bridge"], -4.0)
        self.assertTrue(st["pico"]["tel"]["warn"])

    def test_spray_in_order_with_done_events(self):
        self.post("/api/budget", {"budget": 3})
        status, approved = self.post("/api/plan/approve", {})
        self.assertTrue(approved["sent"])  # Pico 가 있어 LED 를 보냈다
        order = approved["order"]
        self.assertGreaterEqual(len(order), 2)
        self.assertLessEqual(len(order), 3)

        status, body = self.post("/api/dispatch", {})
        self.assertEqual(body["result"]["mode"], "pico")
        wait_for(lambda: self.state()["execution"]["state"] == "done", timeout=10, label="Pico 실행 완료")

        sprays = [json.loads(line[len("@@SPRAY"):].strip()) for line in self.pico.spray_lines()]
        self.assertEqual([s["arm"] for s in sprays], order)
        self.assertEqual([s["seq"] for s in sprays], list(range(1, len(order) + 1)))
        self.assertTrue(all(s["ms"] == 600 for s in sprays))
        st = self.state()
        self.assertEqual(st["execution"]["done"], order)
        self.assertTrue(any(c.startswith("@@LED") for c in self.pico.commands))
        led = json.loads(self.pico.commands[-1][len("@@LED"):].strip())
        self.assertEqual(set(led["arms"]), set(ARMS))
        for arm in order:
            self.assertEqual(led["arms"][arm], "done")

    def test_spray_timeout_stops_dispatch(self):
        srv.SPRAY_TIMEOUT_S = 0.4
        self.pico.done_after = None  # 완료를 보내지 않는 Pico
        self.post("/api/budget", {"budget": 2})
        self.post("/api/plan/approve", {})
        self.post("/api/dispatch", {})
        wait_for(lambda: self.state()["execution"]["state"] == "failed", timeout=6, label="시간초과 중단")
        st = self.state()
        self.assertIn("시간초과", st["execution"]["message"])
        self.assertTrue(self.pico.has_stop())
        # 첫 갈래만 보냈고 나머지는 보내지 않았다.
        self.assertEqual(len(self.pico.spray_lines()), 1)

    def test_estop_during_dispatch_sends_stop(self):
        srv.SPRAY_TIMEOUT_S = 3.0
        self.pico.done_after = 2.5  # 첫 갈래가 늦게 끝난다
        self.post("/api/budget", {"budget": 2})
        self.post("/api/plan/approve", {})
        self.post("/api/dispatch", {})
        wait_for(lambda: len(self.pico.spray_lines()) >= 1, timeout=5, label="첫 살포 명령")
        status, body = self.post("/api/estop", {})
        self.assertEqual(status, 200)
        self.assertTrue(body["sent"])
        self.assertTrue(self.pico.has_stop())
        wait_for(lambda: self.state()["execution"]["state"] == "stopped", timeout=6, label="정지 상태")

    def test_redispatch_after_estop(self):
        """정지 뒤 다시 출동해도 멈춘 옛 스레드가 새 실행을 덮어쓰지 않는다."""
        srv.SPRAY_TIMEOUT_S = 1.0
        self.pico.done_after = 1.5   # 첫 실행은 늦게 끝난다
        self.post("/api/budget", {"budget": 2})
        status, approved = self.post("/api/plan/approve", {})
        order = approved["order"]
        self.post("/api/dispatch", {})
        wait_for(lambda: len(self.pico.spray_lines()) >= 1, timeout=5, label="첫 살포")
        self.post("/api/estop", {})
        wait_for(lambda: self.state()["execution"]["state"] == "stopped", timeout=4, label="정지")

        self.pico.done_after = 0.05
        status, body = self.post("/api/dispatch", {})
        self.assertEqual(status, 200)
        wait_for(lambda: self.state()["execution"]["state"] == "done", timeout=8, label="재출동 완료")
        st = self.state()
        self.assertEqual(st["execution"]["done"], order)
        self.assertEqual(st["execution"]["state"], "done")

    def test_led_shows_plan_after_approval(self):
        self.post("/api/budget", {"budget": 2})
        self.post("/api/plan/approve", {})
        order = self.state()["approved"]["order"]
        wait_for(lambda: any(c.startswith("@@LED") for c in self.pico.commands), timeout=5, label="LED 전송")
        leds = [json.loads(c[len("@@LED"):].strip()) for c in self.pico.commands if c.startswith("@@LED")]
        last = leds[-1]["arms"]
        for arm in order:
            self.assertEqual(last[arm], "plan")


# ---------------------------------------------------------------------------
# 실제 CLI(서브프로세스)
# ---------------------------------------------------------------------------


class CliBase(unittest.TestCase):
    engine_module = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.port = free_port()
        self.base = "http://127.0.0.1:%d" % self.port
        self.events = os.path.join(self.tmp.name, "events.jsonl")
        self.log_path = os.path.join(self.tmp.name, "server.log")
        self.log = open(self.log_path, "w", encoding="utf-8")
        env = dict(os.environ)
        env.pop("ICEZERO_TOKEN", None)
        env["CMD_API_KEY"] = ""  # 실수로 LLM 을 부르지 않게
        env["ICEZERO_EVENTS"] = self.events
        if self.engine_module:
            env["ICEZERO_ENGINE_MODULE"] = self.engine_module
        self.proc = subprocess.Popen(
            [sys.executable, SERVER_PY, "--no-llm", "--pico-serial", "none",
             "--host", "127.0.0.1", "--port", str(self.port), "--events", self.events],
            env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.wait_ready()

    def wait_ready(self, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                with open(self.log_path, encoding="utf-8") as f:
                    raise AssertionError("서버가 바로 종료했습니다:\n" + f.read()[-3000:])
            try:
                with urllib.request.urlopen(self.base + "/api/state", timeout=1) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.1)
        raise AssertionError("서버가 %.0f초 안에 응답하지 않았습니다" % timeout)

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.log.close()
        self.tmp.cleanup()

    def state(self):
        return http_get(self.base, "/api/state")

    def post(self, path, body=None):
        return http_post(self.base, path, body)


class MissingEngineCliTest(CliBase):
    engine_module = "icezero_cross_없는모듈"

    def test_reports_missing_engine(self):
        st = self.state()
        self.assertIsNone(st["step"])
        self.assertFalse(st["engine"]["present"])
        self.assertIn("엔진 모듈", st["engine"]["error"])
        # 엔진이 없어도 제보·예산 API 는 살아 있다.
        status, body = self.post("/api/budget", {"budget": 1})
        self.assertEqual(status, 200)
        self.assertEqual(body["budget"], 1)


class RealEngineCliTest(CliBase):
    """실제 엔진(모델)으로 재생 → 제보 → 확인 → 승인 → 출동(모의) → 상태."""

    def setUp(self):
        models = os.path.join(ROOT, "engine", "models")
        if not (os.path.exists(os.path.join(ROOT, "engine", "icezero_cross.py"))
                and os.path.exists(os.path.join(models, "xgb_h3.json"))):
            raise unittest.SkipTest("engine/models 가 없어 실제 엔진 시험을 건너뜁니다")
        CliBase.setUp(self)

    def test_full_flow_with_real_engine(self):
        st = self.state()
        self.assertTrue(st["engine"]["ok"], st["engine"]["error"])
        step = st["step"]
        self.assertIn("forecast", step)
        self.assertIn("arms", step)
        night = st["replay"]["night"]
        self.assertTrue(night)

        # 시각을 밤 중간으로 옮긴다.
        status, body = self.post("/api/replay/step", {"hours": 6})
        self.assertEqual(status, 200)
        self.assertEqual(body["index"], 6)

        # 제보 → 규칙 해석 → 사람 확인.
        status, body = self.post("/api/report", {"text": "올림픽로 교량 쪽이 미끄럽습니다"})
        self.assertEqual(status, 200)
        self.assertEqual(body["engine"], "rule")
        self.post("/api/report/confirm", {"arms": ["E"], "budget": 2})
        st = self.state()
        self.assertEqual(st["reports"][0]["arms"], ["E"])

        # 승인 → 출동(모의 실행) → 완료.
        status, approved = self.post("/api/plan/approve", {})
        self.assertEqual(status, 200)
        order = approved["order"]
        self.assertTrue(order)
        status, body = self.post("/api/dispatch", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["mode"], "mock")
        wait_for(lambda: self.state()["execution"]["state"] == "done", timeout=20, label="모의 실행 완료")
        st = self.state()
        self.assertEqual(st["execution"]["done"], order)

        # 실행 기록이 events.jsonl 에 남는다.
        with open(self.events, encoding="utf-8") as f:
            kinds = [json.loads(line)["kind"] for line in f if line.strip()]
        for kind in ("replay", "report", "confirm", "approve", "dispatch", "spray"):
            self.assertIn(kind, kinds)


if __name__ == "__main__":
    unittest.main()
