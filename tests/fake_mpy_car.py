# CPython에서 pico/car/main.py를 그대로 돌리기 위한 가짜 machine·network·socket·time 모듈.
# build()가 만든 모듈을 sys.modules에 잠깐 끼워 main을 import하고, 끝나면 되돌린다.
# WORLD는 지금 쓰는 가짜 하드웨어·시계·네트워크 상태다(호출 시점에 읽는다).
import types

WORLD = None


class World:
    def __init__(self):
        self.us = 0                  # 가짜 시계(마이크로초)
        self.outputs = {}            # 핀 번호 → 마지막 출력 값
        self.duty = {}               # 핀 번호 → 마지막 duty_u16
        self.duties = []             # (핀, duty) 호출 순서
        self.freqs = {}              # 핀 번호 → PWM 주파수
        self.sonar_us = -1           # time_pulse_us 반환값. -1이면 '비었음'
        self.sonar_reads = 0
        self.wifi_connected = True
        self.wifi_attempts = []      # connect(ssid, key) 인자들(비밀번호는 시험에서만 본다)
        self.inbox = []              # [(bytes, addr)] 차가 받을 패킷
        self.sent = []               # [(bytes, addr)] 차가 보낸 패킷
        self.sockets = 0
        self.bind = None
        self.button_down = False     # 택트 스위치를 누른 상태

    # ── 시계 ────────────────────────────────────────────────────────
    def advance_us(self, us):
        self.us += int(us)

    def advance_ms(self, ms):
        self.us += int(ms) * 1000

    # ── 초음파 ──────────────────────────────────────────────────────
    def sonar_cm(self, cm):
        """cm를 왕복 µs로 바꿔 둔다. None이면 '비었음'(-1)."""
        if cm is None:
            self.sonar_us = -1
        else:
            self.sonar_us = int(cm * 58)

    # ── 모터·서보 ───────────────────────────────────────────────────
    def coils(self, nums):
        return [self.outputs.get(n, 0) for n in nums]

    def coils_off(self, nums):
        for v in self.coils(nums):
            if v:
                return False
        return True


def _module(name):
    return types.ModuleType(name)


# ── machine ─────────────────────────────────────────────────────────
class Pin:
    OUT = 1
    IN = 0
    PULL_UP = 1
    PULL_DOWN = 2

    def __init__(self, num, mode=None, pull=None):
        self.num = num
        self.mode = mode
        self.pull = pull

    def value(self, v=None):
        if v is None:
            if self.mode == Pin.IN:
                # 풀업 + 스위치-GND: 누르면 0
                if self.num == BUTTON_PIN and WORLD.button_down:
                    return 0
                return 1
            return WORLD.outputs.get(self.num, 0)
        WORLD.outputs[self.num] = 1 if v else 0
        return None

    def on(self):
        return self.value(1)

    def off(self):
        return self.value(0)


BUTTON_PIN = 14          # pico/car/config.py PIN_BUTTON과 같다


class PWM:
    def __init__(self, pin):
        self.pin = pin

    def freq(self, f=None):
        if f is not None:
            WORLD.freqs[self.pin.num] = f
        return WORLD.freqs.get(self.pin.num, 0)

    def duty_u16(self, value=None):
        if value is None:
            return WORLD.duty.get(self.pin.num, 0)
        WORLD.duty[self.pin.num] = value
        WORLD.duties.append((self.pin.num, value))

    def deinit(self):
        self.duty_u16(0)


def time_pulse_us(pin, level, timeout_us):
    WORLD.sonar_reads += 1
    return WORLD.sonar_us


# ── network ─────────────────────────────────────────────────────────
class WLAN:
    STA_IF = 0
    AP_IF = 1

    def __init__(self, iface):
        self.iface = iface
        self.on = False

    def active(self, flag=None):
        if flag is None:
            return self.on
        self.on = bool(flag)

    def isconnected(self):
        return WORLD.wifi_connected

    def connect(self, ssid, key):
        WORLD.wifi_attempts.append((ssid, key))

    def disconnect(self):
        WORLD.wifi_connected = False


# ── socket ──────────────────────────────────────────────────────────
class Socket:
    def __init__(self, family=None, kind=None):
        self.family = family
        self.kind = kind
        self.blocking = True
        WORLD.sockets += 1

    def bind(self, addr):
        WORLD.bind = addr

    def setblocking(self, flag):
        self.blocking = bool(flag)

    def sendto(self, data, addr):
        WORLD.sent.append((bytes(data), addr))
        return len(data)

    def recvfrom(self, size):
        if not WORLD.inbox:
            raise OSError(11, "EAGAIN")     # MicroPython·CPython 모두 '자료 없음'
        return WORLD.inbox.pop(0)

    def close(self):
        pass


# ── time ────────────────────────────────────────────────────────────
def ticks_us():
    return WORLD.us & 0x3FFFFFFF


def ticks_ms():
    return (WORLD.us // 1000) & 0x3FFFFFFF


def sleep_us(n):
    WORLD.us += int(n)


def sleep_ms(n):
    WORLD.us += int(n) * 1000


def sleep(s):
    WORLD.us += int(s * 1000000)


def time_():
    return WORLD.us / 1000000.0


def build():
    """가짜 모듈 묶음을 만든다. WORLD 전역도 새로 만든다."""
    global WORLD
    WORLD = World()

    machine = _module("machine")
    machine.Pin = Pin
    machine.PWM = PWM
    machine.time_pulse_us = time_pulse_us

    network = _module("network")
    network.WLAN = WLAN
    network.STA_IF = 0
    network.AP_IF = 1

    sock = _module("socket")
    sock.AF_INET = 2
    sock.SOCK_DGRAM = 2
    sock.socket = Socket
    sock.error = OSError

    tm = _module("time")
    tm.ticks_us = ticks_us
    tm.ticks_ms = ticks_ms
    tm.sleep_us = sleep_us
    tm.sleep_ms = sleep_ms
    tm.sleep = sleep
    tm.time = time_
    tm.monotonic = time_

    return WORLD, {"machine": machine, "network": network,
                   "socket": sock, "time": tm}
