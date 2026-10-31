# CPython에서 pico/sensors/main.py를 그대로 돌리기 위한 가짜 dht·machine·neopixel 모듈.
# build()가 만든 모듈을 sys.modules에 잠깐 끼워 main을 import하고, 끝나면 되돌린다.
# WORLD는 지금 쓰는 가짜 하드웨어 상태다(Pin/ADC/NeoPixel이 호출 시점에 읽는다).
import types

WORLD = None


class World:
    def __init__(self):
        self.outputs = {}        # 핀 번호 → 마지막 출력 값(0/1)
        self.adc = {}            # 핀 번호 → raw 값. 없으면 기본값을 쓴다
        self.adc_reads = {}      # 핀 번호 → 읽은 횟수
        self.dht = {2: (2.0, 90), 3: (1.5, 88), 4: (4.0, 70), 5: (5.0, 60)}  # 핀 → (온도, 습도)
        # DHT11은 0~50°C만 잰다. 그래서 가짜 값도 0 위로 둔다.
        self.dht_fail = set()    # 읽기를 실패시킬 핀 번호
        self.dht_reads = {}      # 핀 번호 → 읽은 횟수
        self.dht_log = []        # 읽은 순서(핀 번호)
        self.pixels = [(0, 0, 0)] * 8
        self.writes = 0          # NeoPixel.write() 호출 수
        self.i2c_writes = []     # (주소, 보낸 바이트 수)
        self.i2c_cmds = []       # 0x80 제어 바이트로 보낸 명령 바이트 값
        self.i2c_scan = [0x3C]   # I2C.scan() 결과

    def max_adc(self):
        return max(self.adc.values()) if self.adc else 0


ADC_DEFAULT = 40000           # 젖음 ADC 기본 raw(임계값과 같아 젖음으로 본다)


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
            return WORLD.outputs.get(self.num, 0)
        WORLD.outputs[self.num] = 1 if v else 0
        return None

    def on(self):
        return self.value(1)

    def off(self):
        return self.value(0)


class ADC:
    def __init__(self, pin):
        self.pin = pin

    def read_u16(self):
        n = self.pin.num
        WORLD.adc_reads[n] = WORLD.adc_reads.get(n, 0) + 1
        return WORLD.adc.get(n, ADC_DEFAULT)


class I2C:
    def __init__(self, i2c_id, sda=None, scl=None, freq=None):
        self.id = i2c_id
        self.sda = sda
        self.scl = scl
        self.freq = freq

    def scan(self):
        return list(WORLD.i2c_scan)

    def writeto(self, addr, buf):
        WORLD.i2c_writes.append((addr, len(buf)))
        if len(buf) >= 2 and buf[0] == 0x80:
            WORLD.i2c_cmds.append(buf[1])

    def writevto(self, addr, bufs):
        total = 0
        for b in bufs:
            total += len(b)
        WORLD.i2c_writes.append((addr, total))


class DHT11:
    def __init__(self, pin):
        self.pin = pin
        self._t = None
        self._rh = None

    def measure(self):
        n = self.pin.num
        WORLD.dht_reads[n] = WORLD.dht_reads.get(n, 0) + 1
        WORLD.dht_log.append(n)
        if n in WORLD.dht_fail:
            raise OSError("DHT11 응답 없음")
        got = WORLD.dht.get(n, (None, None))
        self._t = got[0]
        self._rh = got[1]

    def temperature(self):
        return self._t

    def humidity(self):
        return self._rh


class NeoPixel:
    def __init__(self, pin, n):
        self.pin = pin
        self.n = n
        self.pixels = [(0, 0, 0)] * n
        WORLD.pixels = self.pixels          # 시험이 바로 들여다본다

    def __setitem__(self, i, rgb):
        self.pixels[i] = rgb

    def __getitem__(self, i):
        return self.pixels[i]

    def write(self):
        WORLD.writes += 1


class FakePoll:
    """항상 '읽을 것이 있다'고 답한다. stdin이 비면 main이 빈 문자열을 보고 멈춘다."""

    def poll(self, timeout=0):
        return [1]


def _module(name):
    return types.ModuleType(name)


def build():
    """가짜 모듈 묶음을 만든다. WORLD 전역도 새로 만든다."""
    global WORLD
    WORLD = World()
    machine = _module("machine")
    machine.Pin = Pin
    machine.ADC = ADC
    machine.I2C = I2C
    dht = _module("dht")
    dht.DHT11 = DHT11
    neopixel = _module("neopixel")
    neopixel.NeoPixel = NeoPixel
    return WORLD, {"machine": machine, "dht": dht, "neopixel": neopixel}
