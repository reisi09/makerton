"""끝에서 끝까지 스모크 시험 (계약 6·7·8절).

서버를 `--no-llm --board-serial none` 으로 임의 포트에 띄우고,
가짜 보드는 HTTP 텔레메트리로, 가짜 제설차는 UDP 소켓으로 붙는다.

    제보 → 확인 → 계획 승인 → 출동 승인 → marker/salt/done → 살포·완료 확인 → 비상 정지

하드웨어 없이 돈다. unittest 로 실행되고 `test_smoke_e2e.py` 가 이 모듈을 불러 간다.
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
SERVER = os.path.join(ROOT, "server", "icezero_server.py")


def free_port(kind=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeCar(threading.Thread):
    """계약 8절 메시지를 흉내 내는 가짜 제설차. hello 0.2초마다, plan/go/stop/resume/abort 에 ack."""

    def __init__(self, server_udp_port):
        threading.Thread.__init__(self, name="fake-car", daemon=True)
        self.addr = ("127.0.0.1", server_udp_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.lock = threading.Lock()
        self.st = "IDLE"
        self.plan = None
        self.cells = []
        self.salted = []
        self.pos = {"leg": 1, "seg": 1, "cell": "U1"}
        self.dist = 140
        self.received = []
        self.errors = []
        self._stop_flag = threading.Event()
        self._next_hello = 0.0

    # -- 전송 --------------------------------------------------------------
    def _send(self, msg):
        msg.setdefault("id", "car-1")
        self.sock.sendto(json.dumps(msg).encode("utf-8"), self.addr)

    def _hello(self):
        with self.lock:
            msg = {"t": "hello", "st": self.st, "plan": self.plan, "cells": list(self.cells),
                   "salted": list(self.salted), "pos": dict(self.pos), "dist": self.dist}
        self._send(msg)

    def _ack(self, seq):
        self._send({"t": "ack", "seq": seq})

    def _evt(self, kind, cell=None, grp=None):
        msg = {"t": "evt", "e": kind, "pos": dict(self.pos)}
        if cell:
            msg["cell"] = cell
        if grp:
            msg["grp"] = grp
        self._send(msg)

    # -- 수신 처리 ---------------------------------------------------------
    def _handle(self, msg):
        kind = msg.get("t")
        seq = msg.get("seq")
        with self.lock:
            self.received.append((kind, seq))
        if kind == "plan":
            with self.lock:
                self.plan = msg.get("plan_id")
                self.cells = list(msg.get("cells") or [])
                busy = self.st not in ("IDLE", "DONE")
            self._ack(seq)
            if busy:
                self._evt("warn")
        elif kind == "go":
            same = msg.get("plan_id") == self.plan
            self._ack(seq)
            if same:
                self._run_plan()
        elif kind == "stop":
            with self.lock:
                self.st = "HOLD_CMD"
            self._ack(seq)
            self._evt("estop")
        elif kind == "resume":
            with self.lock:
                if self.st == "HOLD_CMD":
                    self.st = "RUN"
            self._ack(seq)
            self._evt("resume")
        elif kind == "abort":
            with self.lock:
                self.st = "IDLE"
                self.plan = None
                self.cells = []
            self._ack(seq)

    def _run_plan(self):
        """실제 주행을 짧게 흉내 낸다: start → marker → 칸별 salt → done."""
        with self.lock:
            cells = list(self.cells)
            self.st = "RUN"
            self.pos = {"leg": 1, "seg": 1, "cell": cells[0] if cells else None}
        self._evt("start")
        for cell in cells:
            with self.lock:
                self.pos = {"leg": 1, "seg": 1, "cell": cell}
            self._evt("marker", cell=cell, grp=1)
            self._evt("salt", cell=cell)
            with self.lock:
                if cell not in self.salted:
                    self.salted.append(cell)
            time.sleep(0.03)
        with self.lock:
            self.st = "DONE"
            self.pos = {"leg": 4, "seg": 0, "cell": None}
        self._evt("done")
        self._hello()

    def run(self):
        while not self._stop_flag.is_set():
            now = time.time()
            if now >= self._next_hello:
                self._hello()
                self._next_hello = now + 0.2
            try:
                data, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(json.loads(data.decode("utf-8")))
            except Exception as e:  # 시험을 조용히 실패시키지 않으려고 모아 둔다
                self.errors.append(str(e))

    def stop(self):
        self._stop_flag.set()
        try:
            self.sock.close()
        except OSError:
            pass


class SmokeE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.http_port = free_port()
        cls.udp_port = free_port(socket.SOCK_DGRAM)
        cls.base = "http://127.0.0.1:%d" % cls.http_port
        cls.events_path = os.path.join(cls.tmp.name, "events.jsonl")
        env = dict(os.environ)
        env.pop("ICEZERO_TOKEN", None)
        env["CMD_API_KEY"] = ""          # 실수로 실제 LLM을 부르지 않게
        env["ICEZERO_EVENTS"] = cls.events_path
        cls.log_path = os.path.join(cls.tmp.name, "server.log")
        cls.log = open(cls.log_path, "w", encoding="utf-8")
        cls.proc = subprocess.Popen(
            [sys.executable, SERVER, "--no-llm", "--board-serial", "none",
             "--host", "127.0.0.1", "--port", str(cls.http_port),
             "--udp-port", str(cls.udp_port), "--events", cls.events_path],
            env=env, stdout=cls.log, stderr=subprocess.STDOUT)
        cls._wait_server()
        cls.car = FakeCar(cls.udp_port)
        cls.car.start()

    @classmethod
    def _wait_server(cls):
        deadline = time.time() + 20
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                with open(cls.log_path, encoding="utf-8") as f:
                    raise AssertionError("서버가 바로 종료했습니다:\n" + f.read()[-3000:])
            try:
                with urllib.request.urlopen(cls.base + "/api/state", timeout=1) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.1)
        raise AssertionError("서버가 20초 안에 응답하지 않았습니다")

    @classmethod
    def tearDownClass(cls):
        cls.car.stop()
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
            cls.proc.wait(timeout=5)
        cls.log.close()
        cls.tmp.cleanup()

    # -- 도구 --------------------------------------------------------------
    def call(self, method, path, body=None):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
                ctype = r.headers.get("Content-Type", "")
                if "json" in ctype:
                    return r.status, json.loads(raw.decode("utf-8"))
                return r.status, raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw.decode("utf-8"))
            except ValueError:
                return e.code, {"raw": raw.decode("utf-8", "replace")}

    def state(self):
        code, data = self.call("GET", "/api/state")
        self.assertEqual(code, 200, data)
        return data

    def post(self, path, body=None, expect=200):
        code, data = self.call("POST", path, body if body is not None else {})
        self.assertEqual(code, expect, data)
        return data

    def wait_for(self, fn, what, timeout=6.0):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = fn()
            if last:
                return last
            time.sleep(0.05)
        self.fail("%s 을(를) %.0f초 안에 보지 못했습니다 (마지막: %r)" % (what, timeout, last))

    def reset(self):
        self.post("/api/reset")

    # -- 시험 --------------------------------------------------------------
    def test_01_dashboard_and_state_shape(self):
        code, html = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn("ICE-ZERO", html)
        self.assertIn("관측 주의", html)
        self.assertNotIn("결빙 확정", html)
        for needle in ("/api/report", "/api/plan/approve", "/api/dispatch", "/api/estop", "/api/reset"):
            self.assertIn(needle, html)
        st = self.state()
        for key in ("cells", "budget", "sensors", "proposal", "approved", "car",
                    "pending_report", "links", "events"):
            self.assertIn(key, st)
        self.assertEqual(sorted(st["cells"]), sorted(["U1", "U2", "U3", "U4", "D1", "D2", "D3", "D4"]))
        for key in ("board", "car", "llm"):
            self.assertIn(key, st["links"])
        self.assertFalse(st["links"]["board"]["ok"])   # 시리얼 없이 띄웠다
        self.assertEqual(st["links"]["board"]["mode"], "none")

    def test_02_manual_observe_changes_bridge_score(self):
        self.reset()
        before = self.state()
        self.assertAlmostEqual(before["cells"]["U2"]["score"], 1.5)
        self.post("/api/observe", {"caution": True})
        after = self.state()
        self.assertAlmostEqual(after["cells"]["U2"]["score"], 3.5)
        self.assertEqual(after["sensors"]["caution"], True)
        self.post("/api/observe", {"caution": None})
        back = self.state()
        self.assertAlmostEqual(back["cells"]["U2"]["score"], 1.5)
        self.assertIsNone(back["sensors"]["caution"])
        # 잘못된 값은 400
        self.post("/api/observe", {"caution": "아마도"}, expect=400)
        self.post("/api/budget", {"budget": 99})
        self.assertEqual(self.state()["budget"], 8)
        self.reset()

    def test_03_dispatch_rejected_without_approval(self):
        self.reset()
        code, data = self.call("POST", "/api/dispatch", {})
        self.assertEqual(code, 409, data)
        self.assertIn("승인된 계획", data["error"])

    def test_04_full_flow(self):
        self.reset()

        # 1) 제보 → 규칙 해석(no-llm), pending 저장
        data = self.post("/api/report", {
            "text": "교량 위가 얼음 같아요. 상행 방향이고 제설제 3회분 남았습니다."})
        self.assertEqual(data["engine"], "rule")
        self.assertEqual(data["result"]["cells"], ["U2"])
        self.assertEqual(data["result"]["budget"], 3)
        self.assertIsNotNone(data["error"])  # 왜 규칙으로 갔는지 남는다
        pending = self.state()["pending_report"]
        self.assertIsNotNone(pending)
        self.assertEqual(pending["rule"]["cells"], ["U2"])

        # 2) 사람이 확인 (칸·예산 수정) → 제안 재계산
        data = self.post("/api/report/confirm", {"cells": ["U2"], "budget": 3, "lane1_closed": []})
        st = data["state"]
        self.assertIsNone(st["pending_report"])
        self.assertEqual(st["budget"], 3)
        self.assertTrue(st["cells"]["U2"]["in_proposal"])
        self.assertAlmostEqual(st["cells"]["U2"]["score"], 4.5)   # 제보 3.0 + 구조물 1.5
        self.assertEqual(st["proposal"]["cells"][0], "U2")

        # 3) 예산을 사람이 1회분으로 좁힌다 → 제안이 한 칸
        data = self.post("/api/budget", {"budget": 1})
        self.assertEqual(data["state"]["budget"], 1)
        self.assertEqual(data["state"]["proposal"]["cells"], ["U2"])

        # 4) 계획 승인 → plan_id 발급, UDP plan 전송, 차 ack
        data = self.post("/api/plan/approve")
        self.assertEqual(data["plan_id"], "P1")
        self.assertEqual(data["cells"], ["U2"])
        self.wait_for(lambda: (self.state()["plan_ack"] or {}).get("plan_id") == "P1",
                      "차의 계획 ack")
        kinds = [k for k, _ in list(self.car.received)]
        self.assertIn("plan", kinds)

        # 4) 출동 승인 → go → 가짜 차가 살포·완료 이벤트
        self.post("/api/dispatch")
        self.wait_for(lambda: self.state()["cells"]["U2"]["salted"], "U2 살포 반영")
        st = self.wait_for(lambda: self.state() if self.state()["car"]["st"] == "DONE" else None,
                           "차 상태 DONE")
        self.assertEqual(st["car"]["salted"], ["U2"])
        self.assertFalse(st["cells"]["U2"]["in_proposal"])
        self.assertAlmostEqual(st["cells"]["U2"]["score"], 0.0)
        texts = " / ".join(e["text"] for e in st["events"])
        self.assertIn("살포", texts)
        self.assertIn("출발", texts)
        self.assertIn("실행 완료", texts)

        # 5) 보드 텔레메트리(Wi-Fi 모드) → 응답이 LED 모드
        data = self.post("/api/board/telemetry", {
            "t_piece": -1.2, "t_air": 2.0, "wet": True, "wet_raw": 320,
            "warn": True, "up": 37})
        cells = data["cells"]
        self.assertEqual(cells["U2"], "salted")
        self.assertEqual(cells["D2"], "risk3")
        st = self.state()
        self.assertTrue(st["sensors"]["warn"])
        self.assertTrue(st["links"]["board"]["ok"])
        self.assertAlmostEqual(st["cells"]["D2"]["score"], 3.5)  # 구조물 1.5 + 관측 주의 2.0

        # 6) 비상 정지 → 차 HOLD_CMD
        self.post("/api/estop")
        self.wait_for(lambda: self.state()["car"]["st"] == "HOLD_CMD", "비상 정지 반영")
        self.assertIn("stop", [k for k, _ in list(self.car.received)])
        self.assertIn("비상 정지", " / ".join(e["text"] for e in self.state()["events"]))

        # 7) 초기화 → 살포·승인 계획·제보가 모두 지워진다
        data = self.post("/api/reset")
        st = data["state"]
        self.assertFalse(st["cells"]["U2"]["salted"])
        self.assertIsNone(st["approved"])
        self.assertIsNone(st["pending_report"])
        self.assertEqual(st["sensors"]["caution"], None)

        # 8) events.jsonl 에도 쌓였다
        with open(self.events_path, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertTrue(lines)
        self.assertTrue(any("살포" in e["text"] for e in lines))
        self.assertEqual(self.car.errors, [])

    def test_05_report_reject_and_bad_input(self):
        self.reset()
        self.post("/api/report", {"text": "어딘가 미끄럽대요"})
        self.assertIsNotNone(self.state()["pending_report"])
        self.post("/api/report/reject")
        self.assertIsNone(self.state()["pending_report"])
        self.post("/api/report", {"text": ""}, expect=400)
        self.post("/api/budget", {"budget": "많이"}, expect=400)
        self.post("/api/report/confirm", {"cells": "U2"}, expect=400)

    def test_06_abort_and_resume(self):
        self.reset()
        self.wait_for(lambda: self.state()["car"]["fresh"], "차 링크")
        data = self.post("/api/resume")
        self.assertEqual(data["command"], "resume")
        data = self.post("/api/abort")
        self.assertEqual(data["command"], "abort")
        self.wait_for(lambda: self.state()["car"]["st"] == "IDLE", "abort 후 IDLE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
