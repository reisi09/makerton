"""makerton — 고색고 십자 사거리 결빙 예보 · 자동 제설 서버(대시보드 + 재생 + 센서·차 링크).

실행 예
    python3 server/gosaek_server.py --car udp --sensors-serial auto
    python3 server/gosaek_server.py --stn 108 --car none --sensors-serial none
    python3 server/gosaek_server.py --car fake --sensors-serial fake --no-auto --port 8799

역할
- model/icezero/engine.py 의 Engine 으로 겨울밤 한 밤을 재생하거나 실시간으로 계산한다.
- 센서 Pico(#1, USB 시리얼)의 @@TEL 을 받아 갈래별 현장 보정(local_dt)을 만든다.
- 제설차 Pico(#2, Wi-Fi UDP)와 plan·stop·home·ping 을 주고받는다.
- 예측 동결확률이 기준을 넘으면 auto 조건에서 저절로 출동한다.
- 패드 사진은 규칙(vision.py)과, ANTHROPIC_API_KEY 와 MAKERTON_KEY 가 둘 다 있으면 Claude(claude_vision.py)가 함께 본다. 둘이 다르면 전체 청소.
- Claude를 부르는 요청(/api/vision/detect, /api/vision/boxes)은 X-Makerton-Key 헤더가 MAKERTON_KEY 와 같아야 한다.
"""

import argparse
import datetime
import glob
import hmac
import json
import mimetypes
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC_DIR = os.path.join(HERE, "static")
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")
MONITOR_PATH = os.path.join(STATIC_DIR, "monitor.html")
BOARD_PATH = os.path.join(HERE, "board.json")
EVENTS_PATH = os.environ.get("GOSAEK_EVENTS", os.path.join(HERE, "events.jsonl"))
APP_DIR = os.path.join(ROOT, "web", "out-app")   # npm run build:app 결과(패드용 화면)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server import claude_vision, route, vision  # noqa: E402

HTTP_PORT = 8000
ARMS = ("N", "E", "S", "W")

BASELINE_S = 30.0        # 시작 후 이 시간 동안의 평균을 기준값으로 쓴다(계약 5절)
SENSOR_FRESH_S = 10.0    # 센서가 이 시간 넘게 조용하면 local 을 비운다(계약 5절)
TREAT_HOURS = 3          # 살포 효과를 보는 시간(계약 5절)
MOCK_ARM_S = 3.0         # 차가 없을 때 갈래당 모의 실행 시간(계약 5절)
CAR_FRESH_S = 5.0        # 차 링크가 살아 있다고 보는 시간(계약 7절 LINK_TIMEOUT_MS)
PING_S = 1.0             # 차로 보내는 ping 주기(계약 5절)
PLAN_ARM_TIMEOUT_S = 180.0  # 차가 arm_done 을 보내주지 않으면 계획을 접는다(첫 갈래는 기지 출발 포함 실기 약 95초)
PLAN_DONE_TIMEOUT_S = 90.0  # 마지막 갈래 뒤 기지 도킹(plan_done)을 기다리는 한계(귀환은 실기 약 40초)
FAKE_ARM_S = 0.8         # --car fake: 구간당 시간(시연에서 움직임이 보이게)
FAKE_TEL_S = 2.0         # --sensors-serial fake: @@TEL 주기(계약 6절 2초)
SHOW_RESEND_S = 2.0      # @@SHOW 를 같은 내용으로 다시 보내는 주기
MAX_EVENT_LINES = 80
DEFAULT_BUDGET = 2
DEFAULT_SEC_PER_HOUR = 6.0
TICK_S = 0.1

# board.json 이 없을 때 쓰는 기본값(계약 7·8·9절). board.json 과 같은 2026-10-31 실측값이다.
BOARD_DEFAULTS = {
    "note": "사진 추정값. 줄자로 재서 pico/car/config.py 와 함께 고친다.",
    "CENTER_X": 582, "CENTER_Y": 480, "BASE_XY": [764, 250], "BASE_H": 270,
    "ROAD_MM": 135, "PLAZA_MM": [297, 420],
    "PLAZA_EDGE_MM": {"N": 243, "S": 176, "W": 157, "E": 140},
    "ARM_END_MM": {"N": 480, "E": 343, "W": 582, "S": 430},
    "ARM_OUT_MM": {"N": 375, "E": 238, "W": 477, "S": 325},
    "SPRAY_WIN": {"N": [100, 375], "E": [100, 238], "S": [100, 325], "W": [100, 477]},
    "BASE_MM": [320, 230],
    "WET_ARM": "W",
    "BOARD_MM": [925, 910],
}
AUTO_COOLDOWN_S = 10.0  # 출동이 끝난 뒤 자동 출동을 다시 판단하기까지(눈이 남아 있으면 한 번 더)


class HttpError(Exception):
    """핸들러가 상태 코드와 함께 던지는 오류."""

    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status
        self.message = message


def _float_or_none(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "y")
    return False


def load_board(path=None):
    """server/board.json 을 읽는다. 없거나 깨졌으면 기본값에 사유를 붙여 돌려준다."""
    board = json.loads(json.dumps(BOARD_DEFAULTS))
    path = path or BOARD_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            for key, value in raw.items():
                board[key] = value
        else:
            board["note"] = "board.json 형식이 객체가 아닙니다: %s" % path
    except OSError:
        board["note"] = "board.json 이 없어 기본값(사진 추정)을 씁니다: %s" % path
    except ValueError as e:
        board["note"] = "board.json 을 읽지 못했습니다(%s). 기본값을 씁니다." % str(e)[:60]
    return board


def _arm(value):
    if isinstance(value, str) and value.strip().upper() in ARMS:
        return value.strip().upper()
    return None


def _arms_of(values):
    """갈래 목록을 N·E·S·W 로 제한하고 중복을 뺀다. 순서는 그대로 둔다(최적 경로가 정한 순서다)."""
    if not values:
        return []
    if isinstance(values, str):
        values = values.replace(",", " ").split()
    out = []
    for item in values:
        arm = _arm(item)
        if arm and arm not in out:
            out.append(arm)
    return out


def _json_tail(line, prefix):
    raw = line[len(prefix):].strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def lan_ip():
    """같은 와이파이에서 접속할 맥북 주소. en0 등에서 찾고, 없으면 127.0.0.1."""
    for iface in ("en0", "en1", "en2", "bridge0"):
        try:
            out = subprocess.check_output(["ipconfig", "getifaddr", iface],
                                          stderr=subprocess.DEVNULL)
        except (OSError, subprocess.CalledProcessError):
            continue
        text = out.decode("utf-8", "replace").strip()
        if text:
            return text
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def monitor_url(ip=None, port=HTTP_PORT):
    return "http://%s:%d/monitor" % (ip or lan_ip(), port)


def find_serial_ports():
    """auto 모드 후보. usbmodem·ttyACM·cu.usbserial 계열을 찾는다."""
    found = []
    for pattern in ("/dev/cu.usbmodem*", "/dev/tty.usbmodem*", "/dev/ttyACM*", "/dev/cu.usbserial*"):
        found.extend(glob.glob(pattern))
    if os.name == "nt":
        try:
            import serial.tools.list_ports as list_ports
            found.extend(p.device for p in list_ports.comports())
        except Exception:  # pyserial 이 없으면 여기서 조용히 넘어간다
            pass
    return sorted(set(found))


# ---------------------------------------------------------------------------
# 가짜 장치(시험·시연 대비)
# ---------------------------------------------------------------------------


class FakeSensorSerial(object):
    """시리얼 대신 쓰는 가짜 기지 Pico(#1).

    pyserial 과 같은 readline/write/flush/close 를 흉내 낸다. 2초마다 @@TEL 을 내보내고,
    E 갈래 기온은 서서히 내려가 기준값과의 차이(dt)가 생긴다.
    model 을 주면 차 상태에 맞춰 dock 을 바꾸고, 귀환할 때마다 refills 를 하나 늘린다.
    """

    def __init__(self, period=FAKE_TEL_S, wet=True, drift=0.35, beats=9, model=None):
        self.period = period
        self.wet = wet
        self.drift = drift
        self.beats = beats
        self.model = model
        self.refills = 3
        self.refilling = False
        self._docked = None
        self._refill_left = 0
        self._rx = []
        self._tx = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._n = 0
        self.t = {"N": 0.4, "E": -0.6, "S": 1.2, "W": -1.0}
        self.rh = {"N": 78, "E": 88, "S": 74, "W": 82}
        self.commands = []
        self._thread = threading.Thread(target=self._beat, name="fake-sensor", daemon=True)
        self._thread.start()

    def _beat(self):
        while not self._stop.is_set():
            self._push("@@TEL " + json.dumps(self.payload(), ensure_ascii=False))
            self._stop.wait(self.period)

    def _dock(self):
        """차가 차고에 있으면 도킹으로 본다."""
        if self.model is None:
            return True
        state = (getattr(self.model, "car_state", None) or {}).get("state")
        return state in ("idle", "done", "home", None)

    def _base_state(self):
        dock = self._dock()
        if self._docked is None:
            self._docked = dock
        elif dock and not self._docked:
            self._docked = True
            self.refills += 1
            self._refill_left = 2      # 두 번의 텔레메트리 동안 보충 중으로 보인다
        elif not dock and self._docked:
            self._docked = False
        if self._refill_left > 0:
            self.refilling = True
            self._refill_left -= 1
        else:
            self.refilling = False
        return {"dock": dock, "refills": self.refills, "refilling": self.refilling}

    def payload(self):
        self._n += 1
        if self._n <= self.beats:
            self.t["E"] = round(self.t["E"] - self.drift, 2)
        t_map = {}
        for arm in ARMS:
            t_map[arm] = self.t[arm] if self._n > 1 else None
        body = {
            "t": t_map,
            "rh": {a: self.rh[a] for a in ARMS},
            "ok": {a: True for a in ARMS},
            "wet_raw": 900 if self.wet else 2400,
            "wet": bool(self.wet),
            "light_raw": 1200,
            "warn": bool(self.wet),
            "up": int(time.time()) % 100000,
        }
        body.update(self._base_state())
        return body

    def _push(self, text):
        with self._lock:
            self._tx.append((text + "\n").encode("utf-8"))

    def readline(self):
        with self._lock:
            if self._tx:
                return self._tx.pop(0)
        return b""

    def write(self, data):
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        for line in text.splitlines():
            line = line.strip()
            if line:
                self.commands.append(line)
        return len(data)

    def flush(self):
        return None

    def close(self):
        self._stop.set()


class FakeCar(object):
    """프로세스 안 가짜 제설차.

    계약 7절 순서를 흉내 낸다: ack → plan_start → (기지 출발) → arm_start → spray_on …
    북동쪽 기지 차고에서 서쪽 출입구로 나와 N 도로로 교차로에 가고, 갈래를 돈 뒤 같은 길로 후진해 들어온다.
    x·y 는 board.json 기준 mm다.
    """

    mode = "fake"
    BEARING = {"N": 0, "E": 90, "S": 180, "W": 270}

    def __init__(self, model, arm_s=FAKE_ARM_S):
        self.model = model
        self.arm_s = arm_s
        self.seq = 0
        self.state = {"state": "idle", "phase": "idle", "arm": None,
                      "x": self._dock()[0], "y": self._dock()[1],
                      "h": self._num("BASE_H", 270), "spray": False, "obst_cm": None, "up": 0}
        self._cancel = threading.Event()
        self._seen_seq = set()
        self._running = False
        self._lock = threading.Lock()

    # -- 링크 인터페이스(CarLink 와 같다) ----------------------------------
    def ok(self):
        return True

    def age(self):
        return 0.0

    def stop(self):
        """시험·종료용. 주행 스레드에 취소 신호만 보낸다."""
        self._cancel.set()

    def send(self, msg):
        if not isinstance(msg, dict):
            return False
        kind = msg.get("t")
        if kind == "plan":
            seq = _int_or_none(msg.get("seq"))
            order = _arms_of(msg.get("order"))
            with self._lock:
                if seq is not None and seq in self._seen_seq:
                    self._ack(seq, False, "중복")
                    return True
                if self._running:
                    self._ack(seq, False, "실행 중")
                    return True
                if not order:
                    self._ack(seq, False, "갈래 없음")
                    return True
                if seq is not None:
                    self._seen_seq.add(seq)
                self._running = True
            self._cancel.clear()
            self._ack(seq, True, "")
            threading.Thread(target=self._run, args=(order,), name="fake-car",
                             daemon=True).start()
        elif kind == "stop":
            self._cancel.set()
            with self._lock:
                self._running = False
            self._emit("stopped", None)
            self._state(state="stopped", phase="idle", arm=None, spray=False)
        elif kind == "home":
            self._cancel.set()
            with self._lock:
                self._running = False
            self._emit("plan_done", None)
            self._state(state="idle", phase="home", x=self._dock()[0],
                        y=self._dock()[1], h=self._num("BASE_H", 270), spray=False, arm=None)
        elif kind == "ping":
            self._tel()
        return True

    # -- 좌표 --------------------------------------------------------------
    def _num(self, key, default):
        board = getattr(self.model, "board", None) or {}
        try:
            return float(board.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _dock(self):
        xy = (getattr(self.model, "board", None) or {}).get("BASE_XY") or [764, 250]
        return float(xy[0]), float(xy[1])

    def _arm_out(self, arm):
        board = getattr(self.model, "board", None) or {}
        table = board.get("ARM_OUT_MM") or {}
        try:
            return float(table.get(arm, 380))
        except (TypeError, ValueError):
            return 380.0

    # -- 내부 --------------------------------------------------------------
    def _ack(self, seq, ok, reason):
        self.model.car_message({"t": "ack", "seq": seq, "ok": bool(ok), "reason": reason})

    def _emit(self, name, arm):
        self.seq += 1
        self.model.car_message({"t": "evt", "e": name, "seq": self.seq, "arm": arm})

    def _tel(self):
        self.seq += 1
        body = {"t": "tel", "id": "car1", "seq": self.seq, "up": 0}
        body.update(self.state)
        self.model.car_message(body)

    def _state(self, **kw):
        self.state.update(kw)
        self._tel()

    def _travel(self, x0, y0, x1, y1, **kw):
        """짧은 간격으로 tel 을 내보내며 직선 보간한다."""
        steps = 4
        for i in range(1, steps + 1):
            if self._cancel.is_set():
                return False
            frac = float(i) / steps
            self._state(x=round(x0 + (x1 - x0) * frac),
                        y=round(y0 + (y1 - y0) * frac), **kw)
            if self._cancel.wait(self.arm_s / steps):
                return False
        return True

    def _run(self, order):
        cx = self._num("CENTER_X", 480)
        cy = self._num("CENTER_Y", 340)
        dock_x, dock_y = self._dock()
        dock_h = self._num("BASE_H", 270)
        self._emit("plan_start", None)

        # 1) 출발: 차고 → 서쪽 출입구 → N 도로 가운데 → 남쪽으로 교차로 중심
        self._state(state="run", phase="depart", arm=None, h=dock_h, spray=False)
        if not self._travel(dock_x, dock_y, cx, dock_y, phase="depart", arm=None, h=dock_h, spray=False):
            return
        if not self._travel(cx, dock_y, cx, cy, phase="depart", arm=None, h=180, spray=False):
            return

        # 2) 갈래: 회전 → 나가며 살포 → 복귀
        for arm in order:
            if self._cancel.is_set():
                return
            heading = self.BEARING.get(arm, 0)
            out = self._arm_out(arm)
            if arm == "E":
                tx, ty = cx + out, cy
            elif arm == "W":
                tx, ty = cx - out, cy
            elif arm == "S":
                tx, ty = cx, cy + out
            else:
                tx, ty = cx, cy - out
            self._emit("arm_start", arm)
            self._state(state="run", phase="turn", arm=arm, h=heading, spray=False)
            if self._cancel.wait(self.arm_s):
                return
            if not self._travel(cx, cy, tx, ty, phase="out", arm=arm, h=heading, spray=False):
                return
            self._emit("spray_on", arm)
            self._state(phase="out", spray=True)
            if self._cancel.wait(self.arm_s):
                return
            self._emit("spray_off", arm)
            self._state(phase="back", spray=False)
            if not self._travel(tx, ty, cx, cy, phase="back", arm=arm, h=heading, spray=False):
                return
            self._emit("arm_done", arm)
            self._state(phase="back", arm=None, spray=False)

        # 3) 귀환: 중심 → 북쪽으로 출입구 높이 → 출입구를 보고 후진해 차고로
        self._state(state="run", phase="home", h=0, spray=False, arm=None)
        if not self._travel(cx, cy, cx, dock_y, phase="home", h=0, spray=False, arm=None):
            return
        if not self._travel(cx, dock_y, dock_x, dock_y, phase="home", h=dock_h, spray=False, arm=None):
            return
        self._emit("plan_done", None)
        with self._lock:
            self._running = False
        self._state(state="idle", phase="idle", x=dock_x, y=dock_y, h=dock_h, spray=False, arm=None)


# ---------------------------------------------------------------------------
# 센서 링크(USB 시리얼)
# ---------------------------------------------------------------------------


class SensorLink(threading.Thread):
    """시리얼 115200. '@@TEL {..}' 를 읽고 '@@SHOW {..}' 를 보낸다."""

    mode = "serial"

    def __init__(self, model, port, path=""):
        threading.Thread.__init__(self, name="sensor", daemon=True)
        self.model = model
        self.port = port
        self.path = path
        self._stop_flag = threading.Event()
        self._wlock = threading.Lock()

    def write_line(self, line):
        with self._wlock:
            self.port.write((line + "\n").encode("utf-8"))
            self.port.flush()

    def run(self):
        if self.port is None:
            return
        while not self._stop_flag.is_set():
            try:
                line = self.port.readline()
            except Exception as e:  # 케이블이 빠지면 링크만 끈다
                self.model.event("sensor", "시리얼 읽기 실패: %s" % str(e)[:60])
                with self.model.lock:
                    self.model.sensor_state["mode"] = "none"
                break
            if line:
                text = line.decode("utf-8", "replace").strip()
                if text.startswith("@@TEL"):
                    self.model.sensor_telemetry(_json_tail(text, "@@TEL"))
            else:
                time.sleep(0.02)
        try:
            self.port.close()
        except Exception:
            pass

    def stop(self):
        self._stop_flag.set()


def open_sensor_base_serial(spec, model=None):
    """--sensors-serial auto|<포트>|none|fake. (port, path, mode) 를 돌려준다.

    fake 는 기지 상태(dock·refills)를 차 상태와 맞추려고 model 을 넘겨받는다.
    """
    if spec in ("none", "", None):
        return None, "", "none"
    if spec == "fake":
        return FakeSensorSerial(model=model), "가짜 기지", "fake"
    target = ""
    if spec == "auto":
        ports = find_serial_ports()
        if not ports:
            print("[센서] 시리얼 포트를 찾지 못했습니다. 센서 없이 계속합니다.")
            return None, "", "none"
        if len(ports) > 1:
            print("[센서] 시리얼 후보가 2개 이상입니다:")
            for p in ports:
                print("   ", p)
            print("      하나만 꽂거나 --sensors-serial <포트> 로 지정하세요.")
            return None, "", "none"
        target = ports[0]
    else:
        target = spec
    try:
        import serial
    except ImportError:
        print("[센서] pyserial 이 없어 시리얼 연결을 끕니다.")
        return None, "", "none"
    try:
        ser = serial.Serial(target, 115200, timeout=0.2)
    except Exception as e:
        print("[센서] 시리얼 열기 실패(%s): %s — 센서 없이 계속합니다." % (target, e))
        return None, "", "none"
    print("[센서] 시리얼 연결:", target)
    return ser, target, "serial"


# ---------------------------------------------------------------------------
# 차 링크(Wi-Fi UDP)
# ---------------------------------------------------------------------------


def local_ip_for(ip, port):
    """ip로 보낼 때 운영체제가 고르는 이 노트북의 출발 주소. 패킷은 보내지 않는다."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((ip, port))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


class CarLink(threading.Thread):
    """UDP 로 듣고(기본 9200) hello·tel 을 보낸 주소로 plan·stop·home·ping 을 보낸다."""

    mode = "udp"

    def __init__(self, model, listen_port=9200, car_port=9201, ping_s=PING_S, fresh_s=CAR_FRESH_S):
        threading.Thread.__init__(self, name="car", daemon=True)
        self.model = model
        self.listen_port = listen_port
        self.car_port = car_port
        self.ping_s = ping_s
        self.fresh_s = fresh_s
        self.addr = None
        self.last_seen = 0.0
        self.last_ping = 0.0
        self.sock = None
        self._stop_flag = threading.Event()
        self._send_lock = threading.Lock()

    def open(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.2)
        sock.bind(("0.0.0.0", self.listen_port))
        self.sock = sock
        return self

    def run(self):
        if self.sock is None:
            return
        while not self._stop_flag.is_set():
            data = None
            addr = None
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                pass
            except OSError as e:
                self.model.event("car", "UDP 수신을 멈춥니다: %s" % str(e)[:60])
                break
            if data:
                try:
                    body = json.loads(data.decode("utf-8", "replace"))
                except ValueError:
                    body = None
                if isinstance(body, dict):
                    if self.addr is None or self.addr[0] != addr[0]:
                        self._check_route(addr[0])
                    self.addr = (addr[0], addr[1])
                    self.last_seen = time.time()
                    self.model.car_message(body, self.addr)
            self._maybe_ping()
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass

    def _check_route(self, ip):
        """맥이 IPv6 전용(CLAT, 192.0.0.x)이면 차의 브로드캐스트는 들어와도 차로 보내는 명령은 사라진다.
        SKT 아이폰 핫스팟에서 2026-10-31에 실제로 겪었다."""
        local = local_ip_for(ip, self.car_port)
        if local and local.startswith("192.0.0."):
            self.model.event("car", "맥이 IPv6 전용(CLAT %s)이라 차(%s)로 명령이 가지 않습니다. "
                                    "맥 Wi-Fi > 세부사항 > TCP/IP > IPv6 구성을 '링크-로컬 전용'으로 바꾸고 "
                                    "핫스팟에 다시 연결하세요" % (local, ip))

    def _maybe_ping(self):
        if self.addr is None:
            return
        now = time.time()
        if now - self.last_ping < self.ping_s:
            return
        self.last_ping = now
        self.send({"t": "ping"})

    def send(self, msg):
        with self._send_lock:
            if self.sock is None or self.addr is None:
                return False
            try:
                # 데이터그램 하나에 JSON 하나만 넣는다(개행 없음, 계약 7절).
                line = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
                self.sock.sendto(line.encode("utf-8"), self.addr)
                return True
            except OSError as e:
                self.model.event("car", "UDP 송신 실패: %s" % str(e)[:60])
                return False

    def ok(self):
        return bool(self.addr and self.last_seen and time.time() - self.last_seen <= self.fresh_s)

    def age(self):
        if not self.last_seen:
            return None
        return round(time.time() - self.last_seen, 1)

    def stop(self):
        self._stop_flag.set()


# ---------------------------------------------------------------------------
# 상태 모형
# ---------------------------------------------------------------------------


class Model(object):
    """공유 상태. 모든 변경은 self.lock 안에서 하고, 스냅숏은 복사본을 돌려준다."""

    def __init__(self, engine=None, station=None, engine_error=None, events_path=None,
                 night=None, budget=DEFAULT_BUDGET, auto=True, mode="replay",
                 car_link=None, sensor_link=None, monitor_url=None,
                 board=None, wet_arm=None, claude=False, access_key=None,
                 mock_arm_s=MOCK_ARM_S, baseline_s=BASELINE_S, sensor_fresh_s=SENSOR_FRESH_S,
                 car_fresh_s=CAR_FRESH_S, tick_s=TICK_S, auto_cooldown_s=AUTO_COOLDOWN_S):
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.log_lock = threading.Lock()
        self.engine = engine
        self.engine_error = engine_error
        self.station = station or {"id": "119", "label": "수원 119", "replaced": False, "note": None}
        self.events_path = events_path or EVENTS_PATH
        self.monitor_url = monitor_url or ""
        self.mode = "live" if mode == "live" else "replay"
        self.board = board if isinstance(board, dict) else load_board()
        self.wet_arm = _arm(wet_arm) or _arm(self.board.get("WET_ARM")) or "W"
        self.vision_last = None
        self.claude = bool(claude)      # 패드 사진을 Claude에게도 보인다(키가 환경변수에 있을 때)
        self.vision_live = None         # Claude가 보는 중이면 {"thinking": 지금까지의 사고 요약}
        self._access_key = access_key or ""   # Claude 요청을 여는 보안키(MAKERTON_KEY). 파일·로그·스냅숏에 두지 않는다

        self.car_link = car_link
        self.sensor_link = sensor_link
        self.mock_arm_s = mock_arm_s
        self.baseline_s = baseline_s
        self.sensor_fresh_s = sensor_fresh_s
        self.car_fresh_s = car_fresh_s
        self.tick_s = tick_s
        self.auto_cooldown_s = auto_cooldown_s

        self.budget = self._clamp_budget(budget)
        self.nights = []
        self.night = None
        self.timeline = []
        self.index = 0
        self.step = None
        self.auto = bool(auto)          # 자동 출동
        self.replay_auto = False        # 재생 자동 진행
        self.sec_per_hour = DEFAULT_SEC_PER_HOUR
        self._replay_next = 0.0

        self.treated = {}               # {arm: "효과가 끝나는 ISO 시각"}
        self.execution = self._blank_execution()
        self._plan_counter = 0
        self._seq = 0
        self._run_id = 0
        self._estop_flag = False
        self._auto_cooldown = 0.0
        self._plan_done_seq = 0
        self._dirty = True
        self._step_cache = {}
        self.series = {}
        self._series_busy = set()

        self.sensor_state = {"mode": "none", "port": "", "tel": None, "seen": 0.0, "received": 0}
        self.base_state = {"dock": None, "refills": None, "refilling": None}
        self.baseline = {"ready": False, "started": time.time(), "at": None,
                         "arms": {a: None for a in ARMS}}
        self.samples = {a: [] for a in ARMS}
        self._last_show = None
        self._last_show_at = 0.0

        # 차의 초기 추측 자세는 기지 도킹 위치다(계약 7절).
        try:
            dock_x, dock_y = (float(v) for v in self.board.get("BASE_XY", [764, 250]))
            dock_h = float(self.board.get("BASE_H", 270))
        except (TypeError, ValueError):
            dock_x, dock_y, dock_h = 764.0, 250.0, 270.0
        self.car_state = {"state": "idle", "phase": "idle", "arm": None, "x": dock_x, "y": dock_y,
                          "h": dock_h, "spray": False, "obst_cm": None, "up": 0}
        self.car_seen = 0.0
        self.car_id = ""

        self.events = []
        self._stopped = False

        self._load_nights(night)
        if self.mode == "live":
            self.timeline = []
        self.refresh_step(force=True)
        self._loop_thread = threading.Thread(target=self._loop, name="tick", daemon=True)
        self._loop_thread.start()

    # -- 작은 도구 ---------------------------------------------------------
    @staticmethod
    def _clamp_budget(value):
        n = _int_or_none(value)
        if n is None:
            return DEFAULT_BUDGET
        return max(0, min(4, n))

    def _blank_execution(self):
        return {"state": "idle", "mode": "none", "plan_id": None, "order": [],
                "current": None, "done": [], "seq": None, "message": "",
                "started": None, "finished": None}

    def event(self, kind, text):
        entry = {"ts": round(time.time(), 3), "time": time.strftime("%H:%M:%S"),
                 "kind": kind, "text": text}
        with self.lock:
            self.events.append(entry)
            del self.events[:-MAX_EVENT_LINES]
        try:
            with self.log_lock:
                with open(self.events_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:  # 기록 실패가 현장 동작을 막지 않게 한다
            print("[이벤트 기록 실패]", e)

    def stop(self):
        """시험·종료용. 자동 진행 스레드를 멈춘다."""
        self._stopped = True

    # -- 엔진·재생 ---------------------------------------------------------
    def _load_nights(self, night=None):
        nights = []
        if self.engine is not None:
            try:
                raw = self.engine.nights() or []
            except Exception as e:
                self.engine_error = "밤 목록을 읽지 못했습니다: %s" % str(e)[:120]
                raw = []
            for item in raw:
                if isinstance(item, str):
                    nights.append(item[:10])
                elif isinstance(item, dict):
                    value = item.get("night") or item.get("date") or item.get("day")
                    if value:
                        nights.append(str(value)[:10])
        seen = []
        for n in nights:
            if n not in seen:
                seen.append(n)
        self.nights = seen
        if night:
            self.night = str(night)[:10]
        elif self.mode == "replay":
            default = None
            try:
                default = getattr(self.engine, "default_night", None)
            except Exception:
                default = None
            if isinstance(default, str) and default.strip():
                self.night = default.strip()[:10]
            elif seen:
                self.night = seen[0]
        self._rebuild_timeline()

    def _rebuild_timeline(self):
        self.timeline = []
        self.index = 0
        self.step = None
        self._step_cache = {}
        if self.engine is None or not self.night or self.mode == "live":
            return
        try:
            ts = list(self.engine.timeline(self.night) or [])
        except Exception as e:
            self.engine_error = "시각 목록을 만들지 못했습니다: %s" % str(e)[:120]
            return
        self.timeline = [str(t) for t in ts]
        self._ensure_series(self.night)

    def current_ts(self):
        with self.lock:
            if self.mode == "live":
                return time.strftime("%Y-%m-%dT%H:%M:%S")
            if not self.timeline:
                return None
            idx = max(0, min(self.index, len(self.timeline) - 1))
            return self.timeline[idx]

    def _engine_step(self, ts, local, treated):
        """엔진 step 1회. lock 없이 부른다(0.2초 걸릴 수 있다)."""
        if self.engine is None or ts is None:
            return None
        try:
            result = self.engine.step(ts, local=local, treated=treated, budget=self.budget)
        except Exception as e:
            with self.lock:
                self.engine_error = "step 계산 실패: %s" % str(e)[:160]
            return None
        if not isinstance(result, dict):
            with self.lock:
                self.engine_error = "step 결과가 JSON 객체가 아닙니다"
            return None
        with self.lock:
            self.engine_error = None
        return result

    def refresh_step(self, force=False):
        """현재 시각·센서·처리 상태로 step 을 다시 계산하고 @@SHOW 를 보낸다."""
        with self.lock:
            ts = self.current_ts()
            if ts is None:
                self.step = None
                return None
            local = self.local_payload()
            treated = dict(self.treated)
            key = (ts, json.dumps(local, sort_keys=True), json.dumps(treated, sort_keys=True),
                   self.budget)
            cached = self._step_cache.get(key)
        if cached is not None and not force:
            with self.lock:
                self.step = cached
            self.push_show()
            return cached
        result = self._engine_step(ts, local, treated)
        with self.lock:
            if result is not None:
                self.step = result
            if len(self._step_cache) > 96:
                self._step_cache.clear()
            if result is not None:
                self._step_cache[key] = result
        self.push_show()
        return result

    def _ensure_series(self, night):
        """그 밤 관측 지면온도와 +3h 예측을 한 번만 계산해 둔다(그래프용)."""
        if self.engine is None or not night or night in self.series or night in self._series_busy:
            return
        self._series_busy.add(night)
        timeline = list(self.timeline)

        def work():
            try:
                times, obs, pred = [], [], []
                for ts in timeline:
                    st = self._engine_step(ts, {}, {})
                    if st is None:
                        continue
                    times.append(str(ts))
                    obs.append((st.get("obs") or {}).get("ground_temp"))
                    pred.append((st.get("forecast") or {}).get("h3"))
                with self.lock:
                    if times:
                        self.series[night] = {"time": times, "obs_ground": obs, "pred_h3": pred}
            finally:
                self._series_busy.discard(night)

        threading.Thread(target=work, name="series", daemon=True).start()

    def set_night(self, night):
        if self.mode == "live":
            raise HttpError(409, "실시간 모드에서는 재생 밤을 바꿀 수 없습니다")
        night = str(night or "").strip()[:10]
        if not night:
            raise HttpError(400, "night 값이 필요합니다(YYYY-MM-DD)")
        with self.lock:
            self.night = night
            self._rebuild_timeline()
            self.replay_auto = False
            self.execution = self._blank_execution()
            self.treated = {}
            self._run_id += 1
        self.refresh_step(force=True)
        ts = self.current_ts()
        self.event("replay", "재생 밤을 %s 로 바꿨습니다(18:00부터)" % night)
        return {"night": night, "ts": ts}

    def move(self, hours):
        if self.mode == "live":
            raise HttpError(409, "실시간 모드에서는 시각을 옮길 수 없습니다")
        n = _int_or_none(hours)
        if n is None:
            raise HttpError(400, "hours 는 정수입니다")
        with self.lock:
            if not self.timeline:
                raise HttpError(409, "재생할 시각이 없습니다")
            self.index = max(0, min(self.index + n, len(self.timeline) - 1))
            self.replay_auto = False
            idx = self.index
        self.refresh_step(force=True)
        ts = self.current_ts()
        self.event("replay", "시각 이동: %s" % ts)
        return {"ts": ts, "index": idx}

    def set_replay_auto(self, on, sec_per_hour=None):
        with self.lock:
            if not self.timeline:
                raise HttpError(409, "재생할 시각이 없습니다")
            self.replay_auto = bool(on)
            if sec_per_hour is not None:
                value = _float_or_none(sec_per_hour)
                if value is None or value < 0.2:
                    value = DEFAULT_SEC_PER_HOUR
                self.sec_per_hour = min(60.0, value)
            self._replay_next = time.time() + self.sec_per_hour
            state = self.replay_auto
        if state:
            self.event("replay", "자동 재생 시작(%.1f초/시간)" % self.sec_per_hour)
        else:
            self.event("replay", "자동 재생 정지")
        return {"auto": state, "sec_per_hour": self.sec_per_hour}

    def _loop(self):
        while not self._stopped:
            time.sleep(self.tick_s)
            try:
                with self.lock:
                    if self.replay_auto and self.timeline and time.time() >= self._replay_next:
                        if self.index >= len(self.timeline) - 1:
                            self.replay_auto = False
                        else:
                            self.index += 1
                            self._replay_next = time.time() + self.sec_per_hour
                            self._dirty = True
                    dirty = self._dirty
                    self._dirty = False
                if dirty:
                    self.refresh_step()
                    self.push_show()
                self._maybe_auto_dispatch()
            except Exception as e:  # 루프는 어떤 경우에도 살아 있어야 한다
                print("[루프 오류]", str(e)[:120])

    # -- 센서 --------------------------------------------------------------
    def sensor_fresh_locked(self):
        seen = self.sensor_state["seen"]
        return bool(seen and time.time() - seen <= self.sensor_fresh_s)

    def sensor_telemetry(self, body):
        if not isinstance(body, dict):
            return
        now = time.time()
        t_map = body.get("t") or {}
        rh_map = body.get("rh") or {}
        ok_map = body.get("ok") or {}
        tel = {
            "t": {a: _float_or_none(t_map.get(a)) for a in ARMS},
            "rh": {a: _int_or_none(rh_map.get(a)) for a in ARMS},
            "ok": {a: _bool(ok_map.get(a)) for a in ARMS},
            "wet_raw": _int_or_none(body.get("wet_raw")),
            "wet": _bool(body.get("wet")),
            "light_raw": _int_or_none(body.get("light_raw")),
            "warn": _bool(body.get("warn")),
            "up": _int_or_none(body.get("up")),
        }
        base = {
            "dock": _bool(body.get("dock")) if body.get("dock") is not None else None,
            "refills": _int_or_none(body.get("refills")),
            "refilling": (_bool(body.get("refilling"))
                          if body.get("refilling") is not None else None),
        }
        with self.lock:
            prev = (self.sensor_state.get("tel") or {}).get("warn")
            prev_dock = self.base_state.get("dock")
            prev_refills = self.base_state.get("refills")
            self.sensor_state["tel"] = tel
            self.base_state = base
            self.sensor_state["seen"] = now
            self.sensor_state["received"] += 1
            self._dirty = True
            if not self.baseline["ready"]:
                for arm in ARMS:
                    value = tel["t"][arm]
                    if value is not None:
                        self.samples[arm].append(value)
                if now - self.baseline["started"] >= self.baseline_s:
                    self._finish_baseline_locked(now)
        if prev is not None and prev != tel["warn"]:
            self.event("sensor", "현장 경고 %s" % ("켜짐" if tel["warn"] else "꺼짐"))
        if prev_dock is not None and base["dock"] is not None and prev_dock != base["dock"]:
            self.event("base", "제설차 %s" % ("도킹" if base["dock"] else "기지 이탈"))
        if (prev_refills is not None and base["refills"] is not None
                and base["refills"] > prev_refills):
            self.event("base", "제설제 보충 %d회째" % base["refills"])

    def _finish_baseline_locked(self, now=None):
        tel = self.sensor_state.get("tel") or {}
        t_map = tel.get("t") or {}
        for arm in ARMS:
            values = self.samples.get(arm) or []
            value = None
            if values:
                value = sum(values) / len(values)
            elif t_map.get(arm) is not None:
                value = float(t_map[arm])
            self.baseline["arms"][arm] = None if value is None else round(value, 3)
        self.baseline["ready"] = True
        self.baseline["at"] = now or time.time()
        self.samples = {a: [] for a in ARMS}
        self._dirty = True
        self.event("sensor", "센서 기준값을 잡았습니다: %s" % ", ".join(
            "%s %s" % (a, "—" if self.baseline["arms"][a] is None else "%.1f℃" % self.baseline["arms"][a])
            for a in ARMS))

    def sensor_baseline(self):
        with self.lock:
            self._finish_baseline_locked()
            baseline = dict(self.baseline["arms"])
        return {"ok": True, "baseline": baseline}

    def local_payload(self):
        """엔진에 넘길 local. 센서가 10초 넘게 조용하거나 기준값이 없으면 빈 dict."""
        with self.lock:
            if not self.sensor_fresh_locked():
                return {}
            if not self.baseline["ready"]:
                return {}
            tel = self.sensor_state.get("tel") or {}
            t_map = tel.get("t") or {}
            wet_now = bool(tel.get("wet"))
            local = {}
            for arm in ARMS:
                base = self.baseline["arms"].get(arm)
                value = t_map.get(arm)
                dt = 0.0
                if value is not None and base is not None:
                    dt = round(max(-6.0, min(3.0, float(value) - float(base))), 3)
                wet = wet_now and arm == self.wet_arm
                if dt != 0.0 or wet:
                    local[arm] = {"dt": dt, "wet": wet}
            return local

    def sensor_rows(self):
        """대시보드 센서 표: 갈래별 기온·습도·보정량·측정 성공·젖음."""
        with self.lock:
            fresh = self.sensor_fresh_locked()
            tel = self.sensor_state.get("tel") or {}
            t_map = tel.get("t") or {}
            rh_map = tel.get("rh") or {}
            ok_map = tel.get("ok") or {}
            rows = {}
            for arm in ARMS:
                value = t_map.get(arm)
                base = self.baseline["arms"].get(arm)
                dt = None
                if fresh and self.baseline["ready"] and value is not None and base is not None:
                    dt = round(max(-6.0, min(3.0, float(value) - float(base))), 3)
                rows[arm] = {"t": value if fresh else None,
                             "rh": rh_map.get(arm) if fresh else None,
                             "ok": bool(ok_map.get(arm)) if fresh else False,
                             "dt": dt,
                             "wet": bool(tel.get("wet")) and arm == self.wet_arm if fresh else False}
            return rows

    def push_show(self, force=False):
        """@@SHOW 로 갈래 상태를 센서 Pico 에 보낸다. 내용이 같으면 2초에 한 번만."""
        link = self.sensor_link
        if link is None:
            return False
        payload = {"arms": self.arm_modes(), "msg": self.show_message(),
                   "beacon": self.show_beacon()}
        line = "@@SHOW " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        with self.lock:
            same = line == self._last_show
            recent = now - self._last_show_at < SHOW_RESEND_S
        if same and recent and not force:
            return False
        try:
            link.write_line(line)
        except Exception as e:
            self.event("sensor", "@@SHOW 전송 실패: %s" % str(e)[:60])
            return False
        with self.lock:
            self._last_show = line
            self._last_show_at = now
        return True

    def show_beacon(self):
        """출동 중이면 기지 지붕 경광등을 돌린다(계약 5·6절)."""
        with self.lock:
            return self.execution.get("state") == "running"

    def arm_modes(self):
        """센서 Pico 로 보낼 갈래 상태: risk1~3 | plan | done | off."""
        with self.lock:
            modes = {}
            ex = self.execution
            for arm in ARMS:
                if self.treated.get(arm):
                    modes[arm] = "done"
                elif ex.get("state") == "running" and arm in (ex.get("order") or []):
                    modes[arm] = "plan"
                else:
                    row = ((self.step or {}).get("arms") or {}).get(arm) or {}
                    modes[arm] = row.get("level") or "off"
            return modes

    def show_message(self):
        """OLED 는 ASCII 만 그린다. 16자 이내 영문만 쓴다."""
        with self.lock:
            ex = self.execution
            if ex.get("state") == "stopped":
                return "STOP"
            if ex.get("state") == "running":
                current = ex.get("current") or ""
                return ("RUN %s" % current).strip()[:16]
            if not self.auto:
                return "AUTO OFF"
            order = list((self.step or {}).get("dispatch", {}).get("order") or [])
            if order:
                return ("PLAN " + " ".join(order))[:16]
            if self.treated:
                return ("DONE " + " ".join(sorted(self.treated)))[:16]
            return "AUTO ON"

    # -- 차 링크 -----------------------------------------------------------
    def _car_fresh_locked(self):
        link = self.car_link
        if link is None:
            return False
        try:
            return bool(link.ok())
        except Exception:
            return False

    def _treated_now_locked(self):
        """아직 효과가 남아 있는(재생 시각 기준) 처리됨 갈래."""
        ts = self.current_ts() or ""
        active = set()
        for arm, end in self.treated.items():
            if not ts or str(end) > ts:
                active.add(arm)
        return active

    def base_gate_locked(self):
        """기지 링크가 살아 있으면 dock 이 참일 때만 자동 출동한다(계약 5절)."""
        if self.sensor_state["mode"] in ("none", "") or not self.sensor_fresh_locked():
            return True
        return bool(self.base_state.get("dock"))

    def car_idle_locked(self):
        if not self._car_fresh_locked():
            return True  # 차가 없으면 모의 실행 대상이므로 idle 로 본다
        return self.car_state.get("state") in ("idle", "done", "home")

    def car_message(self, body, addr=None):
        if not isinstance(body, dict):
            return
        kind = body.get("t")
        with self.lock:
            self.car_seen = time.time()
            if addr is not None:
                self.car_id = body.get("id") or self.car_id
        if kind == "tel":
            with self.lock:
                self.car_state = {
                    "state": str(body.get("state") or "idle")[:12],
                    "phase": str(body.get("phase") or "idle")[:10],
                    "arm": _arm(body.get("arm")),
                    "x": _float_or_none(body.get("x")),
                    "y": _float_or_none(body.get("y")),
                    "h": _float_or_none(body.get("h")),
                    "spray": _bool(body.get("spray")),
                    "obst_cm": _float_or_none(body.get("obst_cm")),
                    "up": _int_or_none(body.get("up")),
                }
            return
        if kind == "ack":
            ok = _bool(body.get("ok"))
            reason = str(body.get("reason") or "")[:80]
            seq = _int_or_none(body.get("seq"))
            self.event("car", "명령 확인 seq %s: %s%s" % (
                seq if seq is not None else "—",
                "수락" if ok else "거절",
                (" (%s)" % reason) if reason else ""))
            if not ok:
                with self.lock:
                    ex = self.execution
                    if (ex.get("state") == "running" and seq is not None
                            and ex.get("seq") == seq):
                        self.execution.update({
                            "state": "failed", "current": None,
                            "message": "차가 계획을 거절했습니다: %s" % (reason or "이유 없음"),
                            "finished": round(time.time(), 3)})
                        self.cond.notify_all()
                        self._dirty = True
            return
        if kind == "evt":
            name = str(body.get("e") or "")
            arm = _arm(body.get("arm"))
            if name == "arm_done" and arm:
                self.arm_done(arm, via="car")
            elif name == "plan_done":
                with self.lock:
                    self._plan_done_seq += 1
                    self.cond.notify_all()
                self.event("car", "계획 실행 완료 신호")
            elif name == "stopped":
                self.event("car", "제설차가 정지했습니다")
            elif name == "spray_on":
                self.event("car", "살포 시작%s" % ((" · %s" % arm) if arm else ""))
            elif name == "spray_off":
                self.event("car", "살포 끝%s" % ((" · %s" % arm) if arm else ""))
            elif name == "aborted":
                self.event("car", "제설차가 계획을 중단했습니다")
                with self.lock:
                    if self.execution.get("state") == "running":
                        self.execution.update({"state": "failed", "current": None,
                                               "message": "차가 계획을 중단했습니다",
                                               "finished": round(time.time(), 3)})
                    self.cond.notify_all()
            else:
                self.event("car", "%s%s" % (name or "이벤트", (" · %s" % arm) if arm else ""))
            return

    def _treated_until(self):
        if self.mode == "live" or not self.timeline:
            base = datetime.datetime.now()
        else:
            ts = self.current_ts()
            try:
                base = datetime.datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%S")
            except (TypeError, ValueError):
                base = datetime.datetime.now()
        return (base + datetime.timedelta(hours=TREAT_HOURS)).strftime("%Y-%m-%dT%H:%M:%S")

    def arm_done(self, arm, via="car"):
        arm = _arm(arm)
        if not arm:
            return
        with self.lock:
            end = self._treated_until()
            self.treated[arm] = end
            ex = self.execution
            if ex.get("state") == "running" and arm in (ex.get("order") or []) and arm not in ex["done"]:
                ex["done"].append(arm)
            self.cond.notify_all()
            self._dirty = True
        self.event("car" if via == "car" else "spray",
                   "%s 갈래 살포 완료 → %s 까지 처리됨" % (arm, end))

    def _send_car(self, msg):
        link = self.car_link
        if link is None:
            return False
        try:
            return bool(link.send(msg))
        except Exception as e:
            self.event("car", "명령 전송 실패: %s" % str(e)[:60])
            return False

    # -- 자동 출동 ---------------------------------------------------------
    def _maybe_auto_dispatch(self):
        with self.lock:
            if not self.auto or self.step is None:
                return
            if self.execution.get("state") == "running":
                return
            if time.time() < self._auto_cooldown:
                return
            # 출동은 눈을 봤을 때만 한다(패드 사진은 vision_detect, 여기는 기지 조도센서 = 젖음 입력).
            # 날씨 예보 모델은 화면 참고용이고 출동을 정하지 않는다. 조도센서는 어느 갈래인지 모르니 네 갈래를 다 돈다.
            tel = self.sensor_state.get("tel") or {}
            if not (self.sensor_fresh_locked() and tel.get("wet")):
                return
            order = route.plan({a: {"area_mm2": 1000} for a in ("C",) + ARMS})["order"]
            if not self.car_idle_locked():
                return
            if not self.base_gate_locked():
                return
        try:
            self.dispatch(order=order, source="auto")
        except HttpError:
            pass

    def dispatch(self, order=None, source="manual"):
        with self.lock:
            if self.execution.get("state") == "running":
                raise HttpError(409, "이미 출동 중입니다.")
            if order is None:
                order = ((self.step or {}).get("dispatch") or {}).get("order")
            order = _arms_of(order)
            if not order:
                raise HttpError(409, "출동할 갈래가 없습니다(예측 후보 없음)")
            mode = "car" if self._car_fresh_locked() else "mock"
            self._run_id += 1
            run_id = self._run_id
            self._estop_flag = False
            self._plan_counter += 1
            plan_id = "P%d" % self._plan_counter
            self._seq += 1
            seq = self._seq
            self._plan_done_seq = 0
            self.execution = {"state": "running", "mode": mode, "plan_id": plan_id,
                              "order": order, "current": None, "done": [], "seq": seq,
                              "message": "제설차 출동" if mode == "car" else "모의 실행(차 링크 없음)",
                              "started": round(time.time(), 3), "finished": None}
        sent = False
        if mode == "car":
            sent = self._send_car({"t": "plan", "seq": seq, "order": order})
            if not sent:
                with self.lock:
                    mode = "mock"
                    self.execution["mode"] = "mock"
                    self.execution["message"] = "차 링크가 끊겨 모의 실행"
        self.event("dispatch", "%s 출동 %s: %s (%s)" % (
            {"auto": "자동", "vision": "사진", "sweep": "전체 청소"}.get(source, "수동"), plan_id, " → ".join(order),
            "제설차" if mode == "car" else "모의 실행"))
        thread = threading.Thread(target=self._run_plan, args=(order, plan_id, mode, run_id),
                                  name="plan", daemon=True)
        thread.start()
        return {"plan_id": plan_id, "order": order, "mode": mode, "seq": seq,
                "sent": sent, "source": source}

    # -- 사진 인식(패드) ----------------------------------------------------
    def vision_detect(self, body):
        """패드 사진 한 장 → 도로 위 눈을 갈래별로 센다 → 기지에서 눈 있는 갈래를 도는 최적 순서로 출동."""
        try:
            img = vision.decode_image(body.get("image"))
        except Exception:
            raise HttpError(400, "사진을 읽지 못했습니다. JPEG base64가 필요합니다.")
        found = vision.analyze(img, float(self.board.get("ROAD_MM", 135)))
        if found is None:
            raise HttpError(422, "검은 도로를 찾지 못했습니다. 보드 전체가 보이도록 위에서 찍으면 됩니다.")
        eye = self._ask_claude(img, found["turns"]) if self.claude else None
        decision = route.decide(found["arms"], found["sure"], eye if eye and "error" not in eye else None)
        if eye and "error" in eye:
            decision["text"] += " (Claude 판정 실패로 규칙만 사용: %s)" % eye["error"]
        plan = decision.pop("plan")
        dispatch = None
        if plan and body.get("go", True):
            try:
                dispatch = self.dispatch(order=plan["order"], source="vision")
            except HttpError as e:
                dispatch = {"error": e.message}
        result = {"time": time.strftime("%H:%M:%S"), "ts": time.time(), "arms": found["arms"], "turns": found["turns"],
                  "decision": decision, "route": plan, "dispatch": dispatch, "eye": eye}
        with self.lock:
            self.vision_last = result
        self.event("vision", decision["text"])
        return dict(result, view=found["view"])

    def require_key(self, given):
        """Claude를 부르는 요청의 보안키 확인. 서버에 키가 없으면 어떤 값도 통과시키지 않는다."""
        key = self._access_key.encode("utf-8")
        # 헤더는 latin-1로 풀려 오므로 같은 방식으로 되돌려 바이트를 맞춘다
        if not key or not hmac.compare_digest((given or "").encode("latin-1", "replace"), key):
            raise HttpError(401, "보안키가 맞지 않습니다")

    def vision_boxes(self, body, given_key):
        """사진 한 장 → Claude가 찾은 눈 자리 상자(0..1 비율). 규칙·출동·vision_last와 무관한 화면 표시용."""
        if not self._access_key:
            also = "" if claude_vision.enabled() else " (ANTHROPIC_API_KEY도 없습니다)"
            raise HttpError(503, "서버에 MAKERTON_KEY 환경변수가 없어 AI 눈 상자를 쓸 수 없습니다" + also)
        self.require_key(given_key)
        if not self.claude:
            raise HttpError(503, "서버에 ANTHROPIC_API_KEY 환경변수가 없어 AI 눈 상자를 쓸 수 없습니다")
        try:
            img = vision.decode_image(body.get("image"))
        except Exception:
            raise HttpError(400, "사진을 읽지 못했습니다. JPEG base64가 필요합니다.")
        try:
            found = claude_vision.boxes(img)
        except Exception as e:
            raise HttpError(502, "Claude 호출에 실패했습니다: %s" % str(e)[:120])
        self.event("vision", "AI 눈 상자 %d곳" % len(found["boxes"]))
        return {"boxes": found["boxes"], "note": found["note"], "secs": found["secs"],
                "width": int(img.shape[1]), "height": int(img.shape[0]), "time": time.strftime("%H:%M:%S")}

    def _ask_claude(self, img, turns):
        """Claude 판정. 사고 요약은 오는 대로 vision_live에 두어 화면이 폴링으로 보게 한다. 실패하면 {"error"}."""
        def show(text):
            with self.lock:
                self.vision_live = {"thinking": text}
        show("")
        try:
            return claude_vision.judge(img, turns, show)
        except Exception as e:
            return {"error": str(e)[:120]}
        finally:
            with self.lock:
                self.vision_live = None

    def sweep_all(self, body):
        """전체 청소: 사진 없이 네 갈래를 모두 최적 순서로 돈다. 이미 출동 중이면 409."""
        plan = route.plan(route.ALL)
        dispatch = self.dispatch(order=plan["order"], source="sweep")
        text = "전체 청소 → 최적 순서 %s, 약 %d초" % ("→".join(plan["order"]), plan["seconds"])
        result = {"time": time.strftime("%H:%M:%S"), "ts": time.time(), "arms": None, "turns": 0,
                  "decision": {"go": True, "text": text}, "route": plan, "dispatch": dispatch}
        with self.lock:
            self.vision_last = result
        return result

    def _alive(self, run_id):
        return self._run_id == run_id and not self._estop_flag

    def _wait_arm(self, arm, run_id):
        """차가 arm_done 을 보낼 때까지 기다린다. done|timeout|stopped|superseded."""
        deadline = time.time() + PLAN_ARM_TIMEOUT_S
        with self.lock:
            while time.time() < deadline:
                if self._run_id != run_id:
                    return "superseded"
                if self._estop_flag:
                    return "stopped"
                if self.execution.get("state") != "running":
                    return "aborted"
                if arm in (self.execution.get("done") or []):
                    return "done"
                self.cond.wait(0.05)
        return "timeout"

    def _run_plan(self, order, plan_id, mode, run_id):
        for arm in order:
            with self.lock:
                if self._run_id != run_id:
                    return
                if self._estop_flag:
                    break
                self.execution["current"] = arm
            if mode == "mock":
                deadline = time.time() + self.mock_arm_s
                stopped = False
                while time.time() < deadline:
                    with self.lock:
                        if self._run_id != run_id:
                            return
                        if self._estop_flag:
                            stopped = True
                            break
                    time.sleep(0.02)
                if stopped:
                    break
                self.arm_done(arm, via="mock")
            else:
                outcome = self._wait_arm(arm, run_id)
                if outcome == "aborted":
                    return
                if outcome in ("stopped", "superseded"):
                    if outcome == "stopped":
                        self._finish_plan(run_id, "stopped", "비상 정지")
                    return
                if outcome != "done":
                    self._send_car({"t": "stop"})
                    self._finish_plan(run_id, "failed",
                                      "%s 갈래 완료를 %d초 안에 받지 못했습니다(시간초과)"
                                      % (arm, int(PLAN_ARM_TIMEOUT_S)))
                    return
        if mode == "car" and not self._wait_plan_done(run_id):
            self.event("dispatch", "%s: 도킹 완료 신호가 늦어 계획을 먼저 닫습니다" % plan_id)
        self._finish_plan(run_id, "done", "계획 실행 완료")

    def _wait_plan_done(self, run_id):
        """마지막 갈래 뒤 차가 기지로 돌아와 plan_done 을 보낼 때까지 기다린다."""
        deadline = time.time() + PLAN_DONE_TIMEOUT_S
        with self.lock:
            while time.time() < deadline:
                if self._run_id != run_id or self._estop_flag:
                    return False
                if self._plan_done_seq:
                    return True
                self.cond.wait(0.05)
        return False

    def _finish_plan(self, run_id, state, message):
        with self.lock:
            if self._run_id != run_id:
                return
            if self._estop_flag:
                state, message = "stopped", "비상 정지"
            self.execution.update({"state": state, "current": None, "message": message,
                                   "finished": round(time.time(), 3)})
            self._auto_cooldown = time.time() + self.auto_cooldown_s
            self._dirty = True
            plan_id = self.execution.get("plan_id")
            self.cond.notify_all()
        if state == "done":
            self.event("dispatch", "%s 실행 완료" % plan_id)
        elif state == "failed":
            self.event("dispatch", "%s 중단: %s" % (plan_id, message))

    def set_auto(self, on):
        with self.lock:
            self.auto = _bool(on)
            state = self.auto
        self.event("auto", "자동 출동 %s" % ("켜짐" if state else "꺼짐"))
        return {"auto": state}

    def estop(self):
        with self.lock:
            self._estop_flag = True
            self._run_id += 1
            self.auto = False
            running = self.execution.get("state") == "running"
            self.execution.update({"state": "stopped", "current": None,
                                   "message": "비상 정지", "finished": round(time.time(), 3)})
            self.cond.notify_all()
            self._dirty = True
        sent = self._send_car({"t": "stop"})
        self.event("estop", "비상 정지 → 자동 출동 꺼짐%s" % ("" if sent else " (차 링크 없음)"))
        return {"ok": True, "sent": sent, "was_running": running, "auto": False}

    def car_home(self):
        sent = self._send_car({"t": "home"})
        self.event("car", "제설차 복귀 명령%s" % ("" if sent else " (차 링크 없음)"))
        return {"ok": True, "sent": sent}

    def set_budget(self, value):
        n = _int_or_none(value)
        if n is None:
            raise HttpError(400, "budget 은 0~4 정수입니다")
        with self.lock:
            self.budget = self._clamp_budget(n)
            budget = self.budget
        self.refresh_step(force=True)
        self.event("budget", "예산을 %d갈래로 바꿨습니다" % budget)
        return {"budget": budget}

    def reset(self):
        with self.lock:
            self._run_id += 1
            self._estop_flag = False
            self.treated = {}
            self.execution = self._blank_execution()
            self.budget = DEFAULT_BUDGET
            self.replay_auto = False
            self._dirty = True
            if self.timeline:
                self.index = 0
            self.sensor_state["tel"] = None
            self.baseline = {"ready": False, "started": time.time(), "at": None,
                             "arms": {a: None for a in ARMS}}
            self.samples = {a: [] for a in ARMS}
            self._last_show = None
            self._last_show_at = 0.0
        self._send_car({"t": "stop"})
        self.refresh_step(force=True)
        self.push_show(force=True)
        self.event("reset", "시연 초기화(처리됨·출동·센서 기준값)")
        return {"ok": True}

    # -- 스냅숏 ------------------------------------------------------------
    def snapshot(self):
        now = time.time()
        with self.lock:
            seen = self.sensor_state["seen"]
            sensor_age = round(now - seen, 1) if seen else None
            sensor_ok = self.sensor_fresh_locked()
            link = self.car_link
            car_mode = "none" if link is None else getattr(link, "mode", "udp")
            car_ok = False
            car_age = None
            car_addr = ""
            if link is not None:
                try:
                    car_ok = bool(link.ok())
                    car_age = link.age() if hasattr(link, "age") else None
                except Exception:
                    car_ok = False
                addr = getattr(link, "addr", None)
                if addr:
                    car_addr = "%s:%d" % (addr[0], addr[1])
            series = self.series.get(self.night or "")
            payload = {
                "now": round(now, 3),
                "time": time.strftime("%H:%M:%S"),
                "mode": self.mode,
                "monitor_url": self.monitor_url or monitor_url("127.0.0.1", HTTP_PORT),
                "station": dict(self.station),
                "engine": {"present": self.engine is not None,
                           "ok": bool(self.engine is not None and self.step is not None),
                           "error": self.engine_error},
                "step": self.step,
                "replay": {
                    "night": self.night,
                    "index": self.index,
                    "total": len(self.timeline),
                    "ts": self.current_ts(),
                    "auto": self.replay_auto,
                    "sec_per_hour": self.sec_per_hour,
                    "nights": list(self.nights),
                    "timeline": list(self.timeline),
                },
                "series": ({"ready": True,
                            "time": list(series["time"]),
                            "obs_ground": list(series["obs_ground"]),
                            "pred_h3": list(series["pred_h3"]),
                            "note": "센서·처리 보정 전 모델 예측"}
                           if series else {"ready": False, "note": "계산 중"}),
                "budget": self.budget,
                "auto": self.auto,
                "board": json.loads(json.dumps(self.board)),
                "wet_arm": self.wet_arm,
                "vision": json.loads(json.dumps(self.vision_last)),
                "vision_live": dict(self.vision_live) if self.vision_live else None,
                "claude": self.claude,
                "base": {
                    "ok": bool(sensor_ok and self.sensor_state["mode"] != "none"),
                    "dock": self.base_state.get("dock"),
                    "refills": self.base_state.get("refills"),
                    "refilling": self.base_state.get("refilling"),
                    "beacon": self.execution.get("state") == "running",
                    "age": sensor_age,
                    "wet_arm": self.wet_arm,
                },
                "treated": dict(self.treated),
                "execution": json.loads(json.dumps(self.execution)),
                "sensor": {
                    "mode": self.sensor_state["mode"],
                    "port": self.sensor_state["port"],
                    "ok": sensor_ok,
                    "age": sensor_age,
                    "baseline_ready": self.baseline["ready"],
                    "baseline": dict(self.baseline["arms"]),
                    "local": self.local_payload(),
                    "tel": json.loads(json.dumps(self.sensor_state["tel"])) if self.sensor_state["tel"] else None,
                    "rows": self.sensor_rows(),
                },
                "car": {
                    "mode": car_mode,
                    "ok": car_ok,
                    "age": car_age,
                    "addr": car_addr,
                    "id": self.car_id,
                    "tel": dict(self.car_state),
                },
                "links": {
                    "engine": {"ok": bool(self.engine is not None and self.step is not None),
                               "present": self.engine is not None},
                    "sensor": {"mode": self.sensor_state["mode"], "ok": sensor_ok,
                               "age": sensor_age},
                    "car": {"mode": car_mode, "ok": car_ok, "age": car_age},
                },
                "events": list(self.events[-MAX_EVENT_LINES:]),
            }
        return payload


# ---------------------------------------------------------------------------
# 엔진 준비
# ---------------------------------------------------------------------------


def _engine_class(spec, engine_error=None):
    """엔진 클래스를 찾는다. GOSAEK_ENGINE='모듈:클래스' 로 시험용 가짜 엔진을 끼울 수 있다."""
    import importlib
    if spec:
        module_name, _, attr = spec.partition(":")
        module = importlib.import_module(module_name)
        cls = getattr(module, attr or "Engine", None)
        if cls is None:
            raise AttributeError("%s 에 %s 클래스가 없습니다" % (module_name, attr or "Engine"))
        return cls
    from model.icezero.engine import Engine
    return Engine


def _make_engine(cls, stn, models_dir):
    """Engine(stn=..) 을 만든다. 그 지점 모델이 있을 때만 load 한다.

    인자 이름이 다른 가짜 엔진도 받아 주려고 세 가지 모양을 차례로 시도한다.
    """
    attempts = [{"stn": stn, "models_dir": models_dir}, {"stn": stn}, {}]
    last = None
    for kwargs in attempts:
        try:
            engine = cls(**kwargs)
        except TypeError as e:
            last = e
            continue
        try:
            ready = bool(engine.available())
        except Exception:
            ready = True
        if ready:
            engine.load()
        return engine
    raise TypeError("엔진을 만들지 못했습니다: %s" % last)


def _engine_ready(engine):
    if engine is None:
        return False
    try:
        return bool(engine.available())
    except Exception:
        return False


def _station_info(stn, replaced=False, note=None):
    if str(stn) == "108":
        return {"id": "108", "label": "서울 108 대체" if replaced else "서울 108",
                "replaced": bool(replaced), "note": note}
    return {"id": "119", "label": "수원 119" if not replaced else "수원 119(모델 없음)",
            "replaced": bool(replaced), "note": note}


def load_engine(stn="119", models_dir=None):
    """Engine 을 불러온다. 119 모델이 없으면 108 로 대체한다.

    반환: (engine|None, station dict, error|None)
    """
    stn = str(stn or "119")
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    spec = os.environ.get("GOSAEK_ENGINE", "").strip()
    try:
        cls = _engine_class(spec)
    except Exception as e:
        message = "엔진 모듈을 불러오지 못했습니다: %s" % str(e)[:180]
        return None, _station_info(stn, replaced=False, note=message), message

    error = None
    try:
        engine = _make_engine(cls, stn, models_dir)
    except Exception as e:
        engine = None
        error = "엔진 준비 실패: %s" % str(e)[:180]
    if _engine_ready(engine):
        return engine, _station_info(stn), None

    if stn != "108":
        try:
            fallback = _make_engine(cls, "108", models_dir)
        except Exception as e:
            fallback = None
            if error is None:
                error = "서울 108 대체 실패: %s" % str(e)[:160]
        if _engine_ready(fallback):
            note = "수원 119 모델이 없어 서울 108 모델로 대체했습니다."
            return fallback, _station_info("108", replaced=True, note=note), note
    if error is None:
        error = "지점 %s 모델이 없습니다(model/models/%s). 예보 없이 화면만 뜹니다." % (stn, stn)
    return engine, _station_info(stn, replaced=False, note=error), error


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    model = None
    server_version = "makerton/1.0"

    def log_message(self, fmt, *args):
        code = str(args[1]) if len(args) > 1 else ""
        if code.startswith("4") or code.startswith("5"):
            print("[HTTP]", fmt % args)

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _body(self):
        length = _int_or_none(self.headers.get("Content-Length")) or 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HttpError(400, "JSON 본문이 아닙니다")
        if not isinstance(body, dict):
            raise HttpError(400, "JSON 객체 본문이 필요합니다")
        return body

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html", "/monitor", "/monitor.html"):
            target = MONITOR_PATH if path.startswith("/monitor") else INDEX_PATH
            try:
                with open(target, "rb") as f:
                    html = f.read()
            except OSError:
                self._send(500, {"error": "정적 화면 파일을 읽지 못했습니다: %s" % target})
                return
            self._send(200, html, "text/html; charset=utf-8")
        elif path == "/api/state":
            self._send(200, self.model.snapshot())
        elif path.startswith("/static/fonts/"):
            name = path[len("/static/fonts/"):]
            target = os.path.join(STATIC_DIR, "fonts", name)
            # 이 경로만 허용한다(디렉터리 밖으로 나가는 이름은 거절).
            if not name or os.path.basename(name) != name or not os.path.isfile(target):
                self._send(404, {"error": "폰트 파일이 없습니다: %s" % name})
                return
            with open(target, "rb") as f:
                data = f.read()
            ctype = "font/woff2" if name.endswith(".woff2") else "application/octet-stream"
            self._send(200, data, ctype)
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        elif path == "/app" or path.startswith("/app/"):
            self._send_app(urllib.parse.unquote(path[len("/app"):]))
        else:
            self._send(404, {"error": "없는 경로입니다: %s" % path})

    def _send_app(self, rel):
        """web/out-app(BASE_PATH=/app 정적 빌드)을 그대로 낸다. 폴더 밖 경로는 거절한다."""
        root = os.path.realpath(APP_DIR)
        target = os.path.realpath(os.path.join(root, rel.lstrip("/")))
        if target != root and not target.startswith(root + os.sep):
            self._send(404, {"error": "없는 경로입니다"})
            return
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        if not os.path.isfile(target):
            hint = "" if os.path.isdir(root) else " 패드용 화면을 먼저 빌드하세요: cd web && npm run build:app"
            self._send(404, {"error": "없는 경로입니다: /app%s.%s" % (rel, hint)})
            return
        with open(target, "rb") as f:
            data = f.read()
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, data, ctype)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
        route = {
            "/api/replay": self._replay,
            "/api/replay/step": self._step,
            "/api/replay/auto": self._replay_auto,
            "/api/auto": self._auto,
            "/api/dispatch": self._dispatch,
            "/api/car/stop": self._car_stop,
            "/api/car/home": self._car_home,
            "/api/budget": self._budget,
            "/api/sensors/baseline": self._baseline,
            "/api/reset": self._reset,
            "/api/vision/detect": self._vision_detect,
            "/api/vision/boxes": lambda body: (200, self.model.vision_boxes(body, self.headers.get("X-Makerton-Key"))),
            "/api/sweep": lambda body: (200, self.model.sweep_all(body)),
        }.get(path)
        if route is None:
            self._send(404, {"error": "없는 경로입니다: %s" % path})
            return
        try:
            status, payload = route(self._body())
        except HttpError as e:
            status, payload = e.status, {"error": e.message}
        except Exception as e:  # 마지막 그물
            status, payload = 500, {"error": "서버 오류: %s" % str(e)[:160]}
        self._send(status, payload)

    # -- 라우트 ------------------------------------------------------------
    def _vision_detect(self, body):
        if self.model.claude:       # Claude를 부르는 요청만 보안키가 필요하다(규칙만 쓸 때는 열려 있다)
            self.model.require_key(self.headers.get("X-Makerton-Key"))
        return 200, self.model.vision_detect(body)

    def _replay(self, body):
        night = body.get("night")
        if not isinstance(night, str):
            raise HttpError(400, "night 필드가 필요합니다(YYYY-MM-DD)")
        result = self.model.set_night(night)
        return 200, dict(result, state=self.model.snapshot())

    def _step(self, body):
        result = self.model.move(body.get("hours", 1))
        return 200, dict(result, state=self.model.snapshot())

    def _replay_auto(self, body):
        result = self.model.set_replay_auto(body.get("on", False), body.get("sec_per_hour"))
        return 200, dict(result, state=self.model.snapshot())

    def _auto(self, body):
        result = self.model.set_auto(body.get("on", False))
        return 200, dict(result, state=self.model.snapshot())

    def _dispatch(self, body):
        order = body.get("order")
        if order is not None and not isinstance(order, (list, tuple, str)):
            raise HttpError(400, "order 는 갈래 ID 목록입니다")
        result = self.model.dispatch(order=order, source="manual")
        return 200, dict(result, state=self.model.snapshot())

    def _car_stop(self, body):
        return 200, dict(self.model.estop(), state=self.model.snapshot())

    def _car_home(self, body):
        return 200, dict(self.model.car_home(), state=self.model.snapshot())

    def _budget(self, body):
        value = body.get("budget")
        if value is None or isinstance(value, bool) or not isinstance(value, (int, str)):
            raise HttpError(400, "budget 은 0~4 정수입니다")
        result = self.model.set_budget(value)
        return 200, dict(result, state=self.model.snapshot())

    def _baseline(self, body):
        return 200, dict(self.model.sensor_baseline(), state=self.model.snapshot())

    def _reset(self, body):
        return 200, dict(self.model.reset(), state=self.model.snapshot())


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(description="makerton 고색고 사거리 결빙 예보·자동 제설 서버")
    p.add_argument("--host", default="0.0.0.0", help="HTTP 바인드 주소(기본 0.0.0.0)")
    p.add_argument("--port", type=int, default=HTTP_PORT, help="HTTP 포트(기본 8000)")
    p.add_argument("--stn", default="119", choices=("119", "108"),
                   help="지점(기본 119, 모델이 없으면 108로 대체)")
    p.add_argument("--models-dir", default=None, help="학습 산출물 폴더(기본 model/models)")
    p.add_argument("--mode", default="replay", choices=("replay", "live"),
                   help="재생(기본) 또는 실시간")
    p.add_argument("--night", default=None, help="처음 재생할 밤(YYYY-MM-DD)")
    p.add_argument("--sensors-serial", default="auto", metavar="auto|PORT|none|fake",
                   help="센서 Pico 시리얼 포트(기본 auto, fake 는 가짜 센서)")
    p.add_argument("--car", default="udp", choices=("udp", "fake", "none"),
                   help="제설차 링크(기본 udp, fake/none 은 모의 실행)")
    p.add_argument("--udp-port", type=int, default=9200, help="차 텔레메트리를 받는 UDP 포트")
    p.add_argument("--car-port", type=int, default=9201, help="차가 듣는 UDP 포트")
    p.add_argument("--auto", dest="auto", action="store_true", help="자동 출동 켜기(기본)")
    p.add_argument("--no-auto", dest="auto", action="store_false", help="자동 출동 끄기")
    p.add_argument("--events", default=None, help="이벤트 기록 파일(기본 server/events.jsonl)")
    p.add_argument("--board", default=None, help="보드 치수 파일(기본 server/board.json)")
    p.add_argument("--wet-arm", default=None, choices=("N", "E", "S", "W"),
                   help="젖음 센서를 붙일 갈래(기본 board.json 의 WET_ARM)")
    p.set_defaults(auto=True)
    return p


def serve(model, host, port):
    Handler.model = model
    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    args = build_parser().parse_args(argv)
    engine, station, error = load_engine(args.stn, args.models_dir)
    if error:
        print("[엔진]", error)
    else:
        print("[엔진] 지점 %s 준비 완료" % station["id"])
    board = load_board(args.board)
    access_key = os.environ.get("MAKERTON_KEY", "")
    model = Model(engine=engine, station=station, engine_error=error,
                  events_path=args.events, night=args.night, budget=DEFAULT_BUDGET,
                  auto=args.auto, mode=args.mode, board=board, wet_arm=args.wet_arm,
                  claude=claude_vision.enabled() and bool(access_key), access_key=access_key)

    car_link = None
    if args.car == "fake":
        car_link = FakeCar(model)
        print("[차] 가짜 제설차를 붙였습니다(프로세스 안 시뮬레이션)")
    elif args.car == "udp":
        try:
            link = CarLink(model, listen_port=args.udp_port, car_port=args.car_port).open()
            link.start()
            car_link = link
            print("[차] UDP %d 에서 듣습니다(차는 %d)" % (args.udp_port, args.car_port))
        except OSError as e:
            print("[차] UDP %d 를 열지 못했습니다: %s — 모의 실행으로 계속합니다."
                  % (args.udp_port, e))
    else:
        print("[차] 링크 없음 — 출동하면 모의 실행으로 표시합니다")
    model.car_link = car_link

    port, path, smode = open_sensor_base_serial(args.sensors_serial, model)
    sensor_link = None
    if port is not None:
        sensor_link = SensorLink(model, port, path)
        sensor_link.start()
    model.sensor_link = sensor_link
    model.sensor_state["mode"] = smode
    model.sensor_state["port"] = path
    model._dirty = True

    httpd = serve(model, args.host, args.port)
    ip = lan_ip()
    mon = monitor_url(ip, args.port)
    model.monitor_url = mon
    print("=" * 66)
    print("makerton 고색고 사거리 서버를 시작했습니다.")
    print("  모니터(1920x1080):   %s" % mon)
    print("  조작 대시보드:       http://%s:%d/" % (ip, args.port))
    print("  이 노트북에서:       http://127.0.0.1:%d/monitor" % args.port)
    print("  지점: %s%s" % (station["label"], (" — " + station["note"]) if station.get("note") else ""))
    print("  재생 밤: %s / 시각 %d/%d (%s)" % (
        model.night or "없음", model.index + 1 if model.timeline else 0,
        len(model.timeline), model.current_ts() or "—"))
    if model.nights:
        print("  후보 밤: %s" % ", ".join(model.nights[:5]))
    print("  기지 링크: %s / 젖음 갈래 %s" % (
        path if port is not None else "없음", model.wet_arm))
    print("  보드: 중심 (%s, %s) · 기지 차고 %s · %s" % (
        model.board.get("CENTER_X"), model.board.get("CENTER_Y"),
        model.board.get("BASE_XY"), model.board.get("note") or ""))
    print("  차 링크: %s" % ("가짜 제설차" if args.car == "fake"
                             else ("UDP %d" % args.udp_port if args.car == "udp" else "없음(모의 실행)")))
    print("  자동 출동: %s / 예산 %d갈래" % ("켜짐" if model.auto else "꺼짐", model.budget))
    missing = [n for n, ok in (("ANTHROPIC_API_KEY", claude_vision.enabled()), ("MAKERTON_KEY", access_key)) if not ok]
    print("  사진 판정: 규칙%s" % (" + Claude(%s), 요청마다 X-Makerton-Key 필요" % claude_vision.MODEL if model.claude
                                 else " 만(%s 없음)" % ", ".join(missing)))
    print("  이벤트 기록: %s" % model.events_path)
    print("=" * 66)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 멈춥니다.")
    finally:
        httpd.server_close()
        model.stop()
        for link in (sensor_link, car_link):
            if link is not None:
                try:
                    link.stop()
                except Exception:
                    pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
