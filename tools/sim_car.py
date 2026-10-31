# 실물 Pico 없이 pico/car/main.py를 맥에서 그대로 돌리는 가상 제설차.
#
# machine·network·time은 가짜(tests/fake_mpy_car.py)이고 socket만 진짜다. 그래서 서버와는 실제 UDP로
# hello·tel·plan·stop·home을 주고받고, 서버 화면에는 '제설차 연결'로 보인다.
# 코일 핀 출력만 보고 바퀴가 몇 스텝 돌았는지 거꾸로 읽어 차 위치를 따로 적분한다.
# 펌웨어가 스스로 계산하는 추측 위치(car_core.Pose)와 별개라서, 둘이 어긋나면 펌웨어 버그다.
#
#   python3 tools/sim_car.py                   # 이 맥에서 도는 서버(UDP 9200)에 붙는다. Ctrl+C로 끝낸다
#   python3 tools/sim_car.py --speed 20        # 20배속(기본 10)
import argparse
import importlib.util
import math
import os
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICO = os.path.join(ROOT, "pico", "car")
sys.path.insert(0, os.path.join(ROOT, "tests"))
import fake_mpy_car  # noqa: E402

ROADS = ((515, 650, -1, 911), (-1, 926, 404, 552))   # 실측 세로·가로 도로(x0, x1, y0, y1), mm
SWAPPED = ("main", "config", "car_core", "machine", "network", "socket", "time")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PICO, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_firmware(server_ip, server_port, car_port):
    """가짜 하드웨어 + 진짜 socket으로 main.py를 읽는다. sys.modules는 읽은 뒤 되돌린다."""
    world, mods = fake_mpy_car.build()
    mods["socket"] = socket
    saved = {k: sys.modules.get(k) for k in SWAPPED}
    try:
        sys.modules.update(mods)
        cfg = _load("config", "config.py")
        cfg.SERVER_IP, cfg.SERVER_PORT, cfg.UDP_PORT = server_ip, server_port, car_port
        sys.modules["config"] = cfg
        sys.modules["car_core"] = _load("car_core", "car_core.py")
        main = _load("main", "main.py")
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return world, cfg, main


def on_road_or_door(x, y, dock_x, dock_y, center_x, tol=3.0):
    """차 중심이 도로 위이거나 차고~N 도로 출입구 길 위인가(건물을 가로지르지 않는가)."""
    if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, x1, y0, y1 in ROADS):
        return True
    return abs(y - dock_y) < tol and center_x - tol <= x <= dock_x + tol


class Wheel(object):
    """코일 4개의 패턴 → 바퀴 한 스텝(+1 앞, -1 뒤, 0 그대로). 한 tick에 모터마다 최대 한 스텝이다."""

    def __init__(self, pins, invert, half_step):
        self.pins = pins
        self.sign = -1 if invert else 1          # 오른쪽 모터는 마주 보게 달려 있다
        self.half_step = half_step
        self.idx = 0                             # Motors도 0에서 시작한다

    def read(self, outputs):
        pattern = tuple(outputs.get(n, 0) for n in self.pins)
        if not any(pattern):
            return 0
        i = self.half_step.index(pattern)
        d = (i - self.idx) % 8
        self.idx = i
        if d == 0:
            return 0
        if d not in (1, 7):
            raise AssertionError("코일이 한 번에 %d단계 건너뛰었다(실물이면 헛돈다)" % d)
        return self.sign * (1 if d == 1 else -1)


class SimCar(object):
    def __init__(self, server_ip="127.0.0.1", server_port=9200, car_port=9201, speed=10.0, log=None):
        self.world, self.cfg, main = load_firmware(server_ip, server_port, car_port)
        self.core_mod = main.car_core
        self.speed = float(speed)
        # 서버 ping은 실제 시간 1초마다 온다. 빨리 돌리면 차에게는 그 간격이 배속만큼 길어 보이므로 타임아웃도 늘린다
        self.cfg.LINK_TIMEOUT_MS = int(self.cfg.LINK_TIMEOUT_MS * self.speed)
        self.dev = main.CarDevice(self.cfg)
        self.log = log
        hs = self.core_mod.HALF_STEP
        self.left = Wheel(self.cfg.PIN_LEFT, self.cfg.LEFT_INVERT, hs)
        self.right = Wheel(self.cfg.PIN_RIGHT, self.cfg.RIGHT_INVERT, hs)
        self.x, self.y, self.h = float(self.cfg.BASE_X), float(self.cfg.BASE_Y), float(self.cfg.BASE_H)
        self.steps = 0
        self.off_road = []                       # 도로를 벗어난 (x, y)
        self.max_err = 0.0                       # 펌웨어 추측 위치와 바퀴 적분 위치의 최대 차이(mm)
        self.events = []                         # 차가 서버로 보낸 evt 이름
        self.stop_flag = threading.Event()
        send = self.dev.link.send

        def recording_send(obj):
            if obj.get("t") == "evt":
                self.events.append(obj.get("e"))
                if self.log:
                    self.log("evt %-10s %-4s 바퀴 기준 (%4.0f, %4.0f) %3.0f도" %
                             (obj.get("e"), obj.get("arm") or "", self.x, self.y, self.h % 360))
            return send(obj)
        self.dev.link.send = recording_send

    def coils_off(self):
        return self.world.coils_off(self.cfg.PIN_LEFT) and self.world.coils_off(self.cfg.PIN_RIGHT)

    def dock_error(self):
        """(위치 오차 mm, 방위 오차 도) — 바퀴 적분 위치와 차고 도킹 자세의 차이."""
        dh = (self.h - self.cfg.BASE_H + 180.0) % 360.0 - 180.0
        return math.hypot(self.x - self.cfg.BASE_X, self.y - self.cfg.BASE_Y), abs(dh)

    def _track(self):
        mm = self.core_mod.MM_PER_STEP
        dl = self.left.read(self.world.outputs) * mm
        dr = self.right.read(self.world.outputs) * mm
        if not (dl or dr):
            return
        self.steps += 1
        dh = math.degrees((dl - dr) / self.cfg.TRACK_MM)    # 왼쪽이 앞으로 가면 시계 방향
        fwd = (dl + dr) / 2.0
        self.h += dh / 2.0
        self.x += math.sin(math.radians(self.h)) * fwd
        self.y -= math.cos(math.radians(self.h)) * fwd
        self.h += dh / 2.0
        if not on_road_or_door(self.x, self.y, self.cfg.BASE_X, self.cfg.BASE_Y, self.cfg.CENTER_X):
            self.off_road.append((round(self.x), round(self.y)))
        core = self.dev.core
        if core.state == self.core_mod.STATE_RUN:       # 계획이 끝나면 펌웨어는 자세를 차고로 맞춘다
            self.max_err = max(self.max_err, math.hypot(core.pose.x - self.x, core.pose.y - self.y))

    def run(self):
        debt = 0.0
        while not self.stop_flag.is_set():
            self.dev.tick()
            self._track()
            hint = max(self.dev.sleep_hint(), 50)
            self.world.advance_us(hint)
            debt += hint / 1e6 / self.speed
            if debt > 0.002:
                time.sleep(debt)
                debt = 0.0

    def start(self):
        thread = threading.Thread(target=self.run, name="sim-car", daemon=True)
        thread.start()
        return thread

    def stop(self):
        self.stop_flag.set()


def main(argv=None):
    p = argparse.ArgumentParser(description="실물 Pico 없이 제설차 펌웨어를 맥에서 돌린다")
    p.add_argument("--server", default="127.0.0.1", help="서버 IP(기본 이 맥)")
    p.add_argument("--udp-port", type=int, default=9200, help="서버가 듣는 UDP 포트")
    p.add_argument("--car-port", type=int, default=9201, help="가상 차가 듣는 UDP 포트")
    p.add_argument("--speed", type=float, default=10.0, help="배속(기본 10)")
    args = p.parse_args(argv)
    t0 = time.time()

    def log(msg):
        print("[%6.1fs] %s" % (time.time() - t0, msg), flush=True)

    car = SimCar(args.server, args.udp_port, args.car_port, args.speed, log=log)
    car.cfg.LOG_EVENTS = False
    log("가상 제설차 시작: 서버 %s:%d, 차 UDP %d, %g배속. 조작 화면에서 출동시키면 된다."
        % (args.server, args.udp_port, args.car_port, args.speed))
    car.start()
    done = 0
    try:
        while True:
            time.sleep(0.2)
            n = car.events.count("plan_done")
            if n > done:
                done = n
                err, herr = car.dock_error()
                log("계획 끝: 차고까지 %.1fmm·%.1f도 · 도로 이탈 %d점 · 펌웨어 추측과 최대 %.1fmm 차이 · 코일 %s"
                    % (err, herr, len(car.off_road), car.max_err, "꺼짐" if car.coils_off() else "켜짐"))
    except KeyboardInterrupt:
        car.stop()
        log("멈춤")
    return 0


if __name__ == "__main__":
    sys.exit(main())
