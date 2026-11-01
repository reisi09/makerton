# CPython에서 pico_car/main.py를 그대로 돌리기 위한 가짜 machine·network·socket 모듈.
# 시험은 build()로 만든 모듈을 sys.modules에 잠깐 끼워 main을 import하고, 곧바로 되돌린다.
#
# 사용법
#   world, mods = fake_micropython.build()
#   (sys.modules에 mods 넣고 main import)
#   world.now = 1000
#   world.at(1000, 19, 1)      # 19번 핀이 1000ms부터 1
#   car.loop_once(1000)

import json
import os
import types

WORLD = None        # build()가 갈아 끼우는 전역. Pin/PWM이 호출 시점에 읽는다.

SERVO_DUTY_MIN = 1638
SERVO_DUTY_MAX = 8192

# 핀의 기본값. 가운데 라인센서는 유도선 위에 있고, 버튼은 풀업이라 안 누르면 1이다.
DEFAULTS = {19: 1, 21: 1}
LINE_L, LINE_C, LINE_R = 18, 19, 20


class World:
    """가짜 하드웨어의 상태. 시험이 시간·센서값·수신 패킷을 직접 넣는다."""

    def __init__(self):
        self.now = 0
        self.values = {}         # 핀 번호 → [(시각, 값)] (시각 오름차순)
        self.pulses = []         # [(시각, time_pulse_us 반환값 µs)]
        self.outputs = {}        # 핀 번호 → 마지막 출력 값
        self.duties = {}         # 핀 번호 → 마지막 duty_u16
        self.duty_log = []       # [(시각, 핀, duty)]
        self.sent = []           # [{"t": 시각, "addr": 주소, "data": 바이트}]
        self.inbox = []          # [바이트] recvfrom이 하나씩 돌려준다
        self.peer = ("192.168.43.10", 9100)
        self.wifi_connected = False
        self.connects = 0

    # ── 센서 스케줄 ──
    def at(self, t, pin, value):
        """tms부터 pin이 value가 된다(그 뒤 같은 핀의 다음 항목이 나올 때까지)."""
        self.values.setdefault(pin, []).append((t, value))
        self.values[pin].sort()

    def at_pulse(self, t, us):
        """tms부터 time_pulse_us가 us를 돌려준다(음수 = 시간 초과)."""
        self.pulses.append((t, us))
        self.pulses.sort()

    def bar(self, t, ms=60):
        """tms에 폭 ms짜리 검정 막대를 놓는다(세 라인센서 모두 검정). 지나면 다시 선 위로 돌아온다."""
        for pin in (LINE_L, LINE_C, LINE_R):
            self.at(t, pin, 1)
        self.line(t + ms)                  # 막대 뒤에는 가운데만 검정(유도선)

    def line(self, t):
        """가운데 센서만 검정인 정상 주행 상태로 되돌린다."""
        self.at(t, LINE_L, 0)
        self.at(t, LINE_C, 1)
        self.at(t, LINE_R, 0)

    def line_off(self, t):
        """유도선을 완전히 놓친 상태(세 센서 모두 흰색)."""
        for pin in (LINE_L, LINE_C, LINE_R):
            self.at(t, pin, 0)

    def value(self, pin):
        schedule = self.values.get(pin)
        value = DEFAULTS.get(pin, 0)
        if schedule:
            for when, v in schedule:
                if when > self.now:
                    break
                value = v
        return value

    def pulse(self):
        us = -1
        for when, v in self.pulses:
            if when > self.now:
                break
            us = v
        return us

    # ── 결과 조회 ──
    def messages(self):
        """차가 보낸 UDP 메시지를 dict 목록으로."""
        out = []
        for item in self.sent:
            try:
                out.append(json.loads(item["data"].decode()))
            except ValueError:
                pass
        return out

    def events(self):
        return [m for m in self.messages() if m.get("t") == "evt"]

    def event_names(self):
        return [m.get("e") for m in self.events()]

    def cells_marked(self):
        return [m.get("cell") for m in self.events()
                if m.get("e") == "marker" and m.get("cell")]

    def servo_angle(self, pin=16):
        duty = self.duties.get(pin)
        if duty is None:
            return None
        return (duty - SERVO_DUTY_MIN) * 180 // (SERVO_DUTY_MAX - SERVO_DUTY_MIN)


class Pin:
    OUT = 1
    IN = 0
    PULL_UP = 1
    PULL_DOWN = 2
    OPEN_DRAIN = 3

    def __init__(self, num, mode=None, pull=None):
        self.num = num
        self.mode = mode
        self.pull = pull

    def value(self, v=None):
        if v is None:
            return WORLD.value(self.num)
        WORLD.outputs[self.num] = v
        return None

    def high(self):
        return self.value(1)

    def low(self):
        return self.value(0)

    def on(self):
        return self.value(1)

    def off(self):
        return self.value(0)


class PWM:
    def __init__(self, pin, freq=None, duty=None):
        self.pin = pin
        self.freq_hz = freq

    def init(self, freq=None, duty=None):
        if freq is not None:
            self.freq_hz = freq
        if duty is not None:
            self.duty_u16(duty)

    def freq(self, f=None):
        if f is not None:
            self.freq_hz = f
        return self.freq_hz

    def duty_u16(self, value=None):
        if value is None:
            return WORLD.duties.get(self.pin.num, 0)
        WORLD.duties[self.pin.num] = value
        WORLD.duty_log.append((WORLD.now, self.pin.num, value))

    def deinit(self):
        self.duty_u16(0)


def time_pulse_us(pin, level, timeout_us=1000000):
    return WORLD.pulse()


class WLAN:
    STA_IF = 0
    AP_IF = 1

    def __init__(self, mode=0):
        self.mode = mode
        self.active_state = False

    def active(self, flag=None):
        if flag is None:
            return self.active_state
        self.active_state = bool(flag)

    def connect(self, ssid, password=None):
        WORLD.connects += 1

    def isconnected(self):
        return WORLD.wifi_connected

    def disconnect(self):
        WORLD.wifi_connected = False

    def ifconfig(self):
        return ("0.0.0.0", "255.255.255.0", "0.0.0.0", "0.0.0.0")

    def status(self):
        return 1 if WORLD.wifi_connected else 0


class FakeSocket:
    def __init__(self, family=None, kind=None):
        self.family = family
        self.kind = kind
        self.bound = None
        self.blocking = True
        self.closed = False

    def bind(self, addr):
        self.bound = addr

    def setblocking(self, flag):
        self.blocking = bool(flag)

    def recvfrom(self, size=512):
        if not WORLD.inbox:
            raise OSError(11, "EAGAIN")     # MicroPython과 같은 '자료 없음'
        return (WORLD.inbox.pop(0), WORLD.peer)

    def sendto(self, data, addr):
        if self.closed:
            raise OSError(9, "EBADF")
        WORLD.sent.append({"t": WORLD.now, "addr": addr, "data": data})
        return len(data)

    def close(self):
        self.closed = True


def build():
    """가짜 모듈 묶음을 만든다. WORLD 전역도 새로 만든다."""
    global WORLD
    WORLD = World()
    machine = types.ModuleType("machine")
    machine.Pin = Pin
    machine.PWM = PWM
    machine.time_pulse_us = time_pulse_us
    network = types.ModuleType("network")
    network.WLAN = WLAN
    network.STA_IF = 0
    network.AP_IF = 1
    sock = types.ModuleType("socket")
    sock.socket = FakeSocket
    sock.AF_INET = 2
    sock.SOCK_DGRAM = 2
    return WORLD, {"machine": machine, "network": network, "socket": sock}


class PipeStdin:
    """시험용 stdin. 마이크로파이썬 USB CDC처럼 '버퍼링 없이' 1글자씩 읽는다.

    os.fdopen(fd, "r")로 감싸면 파이썬이 미리 읽어 가서 select.poll이 빈손이 되는 일이 생긴다.
    """

    def __init__(self, fd):
        self.fd = os.fdopen(fd, "rb", buffering=0)

    def fileno(self):
        return self.fd.fileno()

    def read(self, n=1):
        data = self.fd.read(n)
        if not data:
            return ""
        return data.decode()

    def close(self):
        self.fd.close()
