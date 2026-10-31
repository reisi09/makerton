# 실물 Pico 없이 하는 통합 시험: 진짜 서버(Model·CarLink·HTTP) + 진짜 UDP + 진짜 펌웨어 main.py(tools/sim_car.py).
# 차 위치는 코일 핀에서 거꾸로 읽은 바퀴 회전으로 따로 적분하므로, 펌웨어가 스스로 계산한 위치를 믿지 않고 확인한다.
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import server.gosaek_server as srv          # noqa: E402
import sim_car                              # noqa: E402
from tests.fake_engine import FakeEngine    # noqa: E402


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for(predicate, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    return None


class SimCarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.model = srv.Model(engine=FakeEngine(), events_path=os.path.join(cls.tmp.name, "events.jsonl"),
                              auto=False, baseline_s=999.0, tick_s=0.02)
        udp, car_port = free_udp_port(), free_udp_port()
        cls.link = srv.CarLink(cls.model, listen_port=udp, car_port=car_port).open()
        cls.link.start()
        cls.model.car_link = cls.link
        cls.httpd = srv.serve(cls.model, "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.car = sim_car.SimCar("127.0.0.1", udp, car_port, speed=200)
        cls.car.cfg.LOG_EVENTS = False
        cls.car.start()

    @classmethod
    def tearDownClass(cls):
        cls.car.stop()
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.link.stop()
        cls.model.stop()
        cls.tmp.cleanup()

    def setUp(self):
        self.car.off_road = []
        self.car.max_err = 0.0

    def api(self, path, body=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def state(self):
        return self.api("/api/state")

    def assert_home_on_roads(self):
        err, herr = self.car.dock_error()
        self.assertLess(err, 1.0, "바퀴 기준 차고 위치 오차")
        self.assertLess(herr, 0.5, "바퀴 기준 차고 방위 오차")
        off = self.car.off_road
        self.assertEqual(len(off), 0, "도로·출입구 길을 벗어난 점, 처음 %s" % (off[:3],))
        self.assertLess(self.car.max_err, 1.0, "펌웨어 추측 위치와 바퀴 적분 위치의 차이")
        self.assertTrue(wait_for(self.car.coils_off, 2), "끝나면 코일을 끈다")

    def test_a_full_clean_runs_on_the_firmware_and_returns_to_the_garage(self):
        self.assertTrue(wait_for(lambda: self.state()["car"]["ok"], 10), "서버가 가상 차를 연결로 본다")
        res = self.api("/api/sweep", {})
        self.assertEqual(res["dispatch"]["mode"], "car")
        order = res["route"]["order"]
        self.assertEqual(sorted(order), ["E", "N", "S", "W"])
        ex = wait_for(lambda: (lambda e: e if e["state"] != "running" else None)(self.state()["execution"]), 120)
        self.assertIsNotNone(ex, "계획이 끝나지 않았다")
        self.assertEqual((ex["state"], ex["mode"], ex["done"]), ("done", "car", order))
        self.assertEqual([e for e in self.car.events if e in ("arm_done", "plan_done")],
                         ["arm_done"] * 4 + ["plan_done"])
        self.assertNotIn("resumed", self.car.events, "링크 타임아웃으로 멈춘 적이 없다")
        self.assert_home_on_roads()
        tel = self.state()["car"]["tel"]
        self.assertEqual((tel["state"], tel["x"], tel["y"], tel["h"]), ("idle", 775.0, 250.0, 270.0))

    def test_b_stop_mid_arm_then_home(self):
        self.assertTrue(wait_for(lambda: self.state()["car"]["ok"], 10))
        res = self.api("/api/sweep", {})
        first = res["route"]["order"][0]
        core = self.car.dev.core
        self.assertTrue(wait_for(lambda: core.arm == first and core.phase == "out" and core.spray, 60),
                        "첫 갈래에서 눈을 밀기 시작한다")
        self.api("/api/car/stop", {})
        self.assertTrue(wait_for(lambda: core.state == "stopped", 5), "정지 명령으로 선다")
        self.assertEqual(self.state()["execution"]["state"], "stopped")
        steps = self.car.steps
        time.sleep(0.3)
        self.assertEqual(self.car.steps, steps, "정지한 뒤에는 바퀴가 돌지 않는다")
        self.assertTrue(self.car.coils_off())
        self.api("/api/car/home", {})
        self.assertTrue(wait_for(lambda: core.state == "idle" and self.car.steps > steps, 60), "복귀를 마친다")
        self.assert_home_on_roads()


if __name__ == "__main__":
    unittest.main()
