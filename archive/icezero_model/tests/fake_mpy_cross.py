# CPython에서 pico_cross/main.py를 그대로 돌리기 위한 가짜 machine·onewire·ds18x20·neopixel 모듈.
# build()가 만든 모듈을 sys.modules에 잠깐 끼워 main을 import하고, 끝나면 되돌린다.
# WORLD는 지금 쓰는 가짜 하드웨어 상태다(Pin/PWM/ADC가 호출 시점에 읽는다).
import types

WORLD = None


class World:
    def __init__(self):
        self.outputs = {}       # 핀 번호 → 마지막 출력 값
        self.duties = {}        # 핀 번호 → 마지막 duty_u16
        self.duty_log = []      # [(핀, duty)] 호출 순서
        self.adc_raw = 20000    # 젖음센서 raw(기본: 젖음)
        self.adc_reads = 0
        self.roms = [b"\x28\x00\x01", b"\x28\x00\x02"]
        self.temps = {b"\x28\x00\x01": 0.5, b"\x28\x00\x02": 21.5625}
        self.conversions = 0
        self.pixels = [(0, 0, 0)] * 4
        self.writes = 0

    def pixel_set(self):
        """서로 다른 색이 하나라도 있으면 True(출력 중)."""
        return len(set(self.pixels)) > 1 or self.pixels[0] != (0, 0, 0)


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


class PWM:
    def __init__(self, pin):
        self.pin = pin
        self.freq_hz = None

    def freq(self, f=None):
        if f is not None:
            self.freq_hz = f
        return self.freq_hz

    def duty_u16(self, value=None):
        if value is None:
            return WORLD.duties.get(self.pin.num, 0)
        WORLD.duties[self.pin.num] = value
        WORLD.duty_log.append((self.pin.num, value))

    def deinit(self):
        self.duty_u16(0)


class ADC:
    def __init__(self, pin):
        self.pin = pin

    def read_u16(self):
        WORLD.adc_reads += 1
        return WORLD.adc_raw


class OneWire:
    def __init__(self, pin):
        self.pin = pin


class DS18X20:
    def __init__(self, ow):
        self.ow = ow

    def scan(self):
        return list(WORLD.roms)

    def convert_temp(self):
        WORLD.conversions += 1

    def read_temp(self, rom):
        return WORLD.temps.get(rom)


class NeoPixel:
    def __init__(self, pin, n):
        self.pin = pin
        self.n = n
        self.pixels = [(0, 0, 0)] * n
        WORLD.pixels = self.pixels

    def __setitem__(self, i, rgb):
        self.pixels[i] = rgb

    def write(self):
        WORLD.writes += 1


def build():
    """가짜 모듈 묶음을 만든다. WORLD 전역도 새로 만든다."""
    global WORLD
    WORLD = World()
    machine = _module("machine")
    machine.Pin = Pin
    machine.PWM = PWM
    machine.ADC = ADC
    onewire = _module("onewire")
    onewire.OneWire = OneWire
    ds18x20 = _module("ds18x20")
    ds18x20.DS18X20 = DS18X20
    neopixel = _module("neopixel")
    neopixel.NeoPixel = NeoPixel
    return WORLD, {"machine": machine, "onewire": onewire,
                   "ds18x20": ds18x20, "neopixel": neopixel}


def _module(name):
    return types.ModuleType(name)


class FakePoll:
    """항상 '읽을 것이 있다'고 답한다. stdin이 비면 main이 빈 문자열을 보고 멈춘다."""

    def poll(self, timeout=0):
        return [1]
