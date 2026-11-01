# ICE-ZERO 보드(Pico #1) 시험. 하드웨어 없이 CPython으로 돈다(가짜 machine/onewire/ds18x20/neopixel 주입).
import contextlib
import importlib
import io
import json
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICO_BOARD = os.path.join(ROOT, "pico_board")
if PICO_BOARD not in sys.path:
    sys.path.insert(0, PICO_BOARD)

import board_core  # noqa: E402  (sys.path를 먼저 넣는다)


# ---------------------------------------------------------------- 가짜 하드웨어
class FakePin:
    OUT = 1
    IN = 0
    instances = []

    def __init__(self, n, mode=None):
        self.n = n
        self.mode = mode
        self.state = 0
        FakePin.instances.append(self)

    def value(self, v=None):
        if v is None:
            return self.state
        self.state = 1 if v else 0
        return None


class FakeADC:
    RAW = [20000]

    def __init__(self, pin):
        self.pin = pin

    def read_u16(self):
        return FakeADC.RAW[0]


class FakeOneWire:
    def __init__(self, pin):
        self.pin = pin


class FakeDS18X20:
    ROMS = [b"\x28\x00\x01", b"\x28\x00\x02"]
    TEMPS = {b"\x28\x00\x01": 0.5, b"\x28\x00\x02": 21.5625}

    def __init__(self, ow):
        self.ow = ow
        self.conversions = 0

    def scan(self):
        return list(FakeDS18X20.ROMS)

    def convert_temp(self):
        self.conversions += 1

    def read_temp(self, rom):
        return FakeDS18X20.TEMPS.get(rom)


class FakeNeoPixel:
    def __init__(self, pin, n):
        self.pin = pin
        self.n = n
        self.pixels = [(0, 0, 0)] * n
        self.writes = 0

    def __setitem__(self, i, rgb):
        self.pixels[i] = rgb

    def write(self):
        self.writes += 1


class FakePoll:
    """항상 '읽을 것이 있다'고 답한다. stdin이 비면 main이 빈 문자열을 보고 멈춘다."""

    def poll(self, timeout=0):
        return [1]


class FakeWLAN:
    def __init__(self, iface):
        self.iface = iface

    def active(self, on=None):
        return True

    def isconnected(self):
        return True

    def connect(self, ssid, password):
        return None


class FakeResponse:
    def __init__(self, obj, status=200):
        self.obj = obj
        self.status_code = status
        self.closed = False

    def json(self):
        return self.obj

    def close(self):
        self.closed = True


def _fake_modules():
    machine = types.ModuleType("machine")
    machine.Pin = FakePin
    machine.ADC = FakeADC
    onewire = types.ModuleType("onewire")
    onewire.OneWire = FakeOneWire
    ds18x20 = types.ModuleType("ds18x20")
    ds18x20.DS18X20 = FakeDS18X20
    neopixel = types.ModuleType("neopixel")
    neopixel.NeoPixel = FakeNeoPixel

    network = types.ModuleType("network")
    network.STA_IF = 0
    network.WLAN = FakeWLAN

    urequests = types.ModuleType("urequests")
    urequests.REPLY = {}
    urequests.FAIL = False
    urequests.CALLS = []

    def post(url, data=None, headers=None, timeout=None):
        urequests.CALLS.append({"url": url, "data": data, "headers": headers or {}, "timeout": timeout})
        if urequests.FAIL:
            raise OSError("연결 실패(시험)")
        return FakeResponse(urequests.REPLY)

    urequests.post = post
    return {"machine": machine, "onewire": onewire, "ds18x20": ds18x20,
            "neopixel": neopixel, "network": network, "urequests": urequests}


@contextlib.contextmanager
def fake_board():
    FakePin.instances = []
    FakeADC.RAW = [20000]
    fakes = _fake_modules()
    saved = dict((k, sys.modules.get(k)) for k in fakes)
    saved_main = sys.modules.get("main")
    sys.modules.pop("main", None)
    sys.modules.update(fakes)
    try:
        yield fakes
    finally:
        for k in fakes:
            if saved[k] is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = saved[k]
        sys.modules.pop("main", None)
        if saved_main is not None:
            sys.modules["main"] = saved_main


def _pin(n):
    for p in FakePin.instances:
        if p.n == n:
            return p
    return None


def _load_main():
    main = importlib.import_module("main")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):    # 부팅 ROM 로그는 따로 본다
        main.setup()
    return main, out.getvalue()


# ---------------------------------------------------------------- 순수 로직 시험
class LocalWarnTest(unittest.TestCase):
    def test_off_keeps_state_until_three_false(self):
        st = {"warn": False, "off": 0}
        st = board_core.local_warn(0.5, True, st)      # 1도 이하 + 젖음 → 켜짐
        self.assertTrue(st["warn"])
        st = board_core.local_warn(5.0, False, st)     # 1회 거짓
        self.assertTrue(st["warn"])
        st = board_core.local_warn(5.0, False, st)     # 2회 거짓
        self.assertTrue(st["warn"])
        st = board_core.local_warn(5.0, False, st)     # 3회 연속 거짓 → 꺼짐
        self.assertFalse(st["warn"])

    def test_on_conditions(self):
        self.assertTrue(board_core.local_warn(1.0, True, {})["warn"])    # 경계 포함
        self.assertFalse(board_core.local_warn(1.0, False, {})["warn"])  # 1.0인데 마름
        self.assertTrue(board_core.local_warn(-2.0, False, {})["warn"])  # 어는점 이하
        self.assertFalse(board_core.local_warn(0.5, False, {})["warn"])

    def test_none_temperature_holds(self):
        st = {"warn": True, "off": 0}
        for _ in range(5):
            st = board_core.local_warn(None, True, st)
        self.assertTrue(st["warn"])          # 센서 오류로 표시가 흔들리지 않는다
        st2 = board_core.local_warn(None, True, {"warn": False, "off": 0})
        self.assertFalse(st2["warn"])

    def test_does_not_mutate_input(self):
        st = {"warn": True, "off": 0}
        board_core.local_warn(5.0, False, st)
        self.assertEqual(st, {"warn": True, "off": 0})


class WetTest(unittest.TestCase):
    def test_when_low(self):
        self.assertTrue(board_core.is_wet(100, 30000, True))
        self.assertFalse(board_core.is_wet(60000, 30000, True))
        self.assertTrue(board_core.is_wet(30000, 30000, True))   # 경계

    def test_when_high(self):
        self.assertTrue(board_core.is_wet(60000, 30000, False))
        self.assertFalse(board_core.is_wet(100, 30000, False))

    def test_none(self):
        self.assertFalse(board_core.is_wet(None, 30000, True))
        self.assertFalse(board_core.is_wet(None, 30000, False))


class LedColorTest(unittest.TestCase):
    def test_modes(self):
        green = board_core.led_rgb("risk1")
        yellow = board_core.led_rgb("risk2")
        red = board_core.led_rgb("risk3")
        white = board_core.led_rgb("salted")
        self.assertEqual(green, (0, 48, 0))
        self.assertEqual(red, (48, 0, 0))
        self.assertTrue(yellow[0] > 0 and yellow[1] > 0 and yellow[2] == 0)
        self.assertTrue(white[0] == white[1] == white[2] > 0)
        self.assertEqual(board_core.led_rgb("off"), (0, 0, 0))
        self.assertEqual(board_core.led_rgb("이상한값"), (0, 0, 0))

    def test_plan_blinks_2hz(self):
        self.assertEqual(board_core.led_rgb("plan", 0), (0, 15, 48))
        self.assertEqual(board_core.led_rgb("plan", 249)[2], 48)   # 켜진 구간
        self.assertEqual(board_core.led_rgb("plan", 300), (0, 0, 0))
        self.assertEqual(board_core.led_rgb("plan", 500)[2], 48)   # 다음 주기

    def test_brightness_low(self):
        rgb = board_core.led_rgb("salted", 0, 255)
        self.assertEqual(rgb, (255, 255, 255))
        self.assertTrue(max(board_core.led_rgb("salted")) <= 64)


class LedViewTest(unittest.TestCase):
    def setUp(self):
        self.cells = dict((c, "risk1") for c in board_core.CELL_IDS)
        self.cells["U2"] = "risk3"

    def test_recent(self):
        view = board_core.led_view(self.cells, 1000, 2000)
        self.assertEqual(view["U2"], "risk3")
        self.assertEqual(view["D1"], "risk1")

    def test_stale_is_off(self):
        view = board_core.led_view(self.cells, 1000, 11000, 10000)
        self.assertEqual(set(view.values()), set(["off"]))

    def test_no_command_is_off(self):
        self.assertEqual(set(board_core.led_view({}, None, 0).values()), set(["off"]))
        self.assertEqual(set(board_core.led_view(None, 500, 600).values()), set(["off"]))


class ParseLedTest(unittest.TestCase):
    def _full(self):
        return dict((c, "off") for c in board_core.CELL_IDS)

    def test_valid(self):
        cells = self._full()
        cells["U2"] = "risk3"
        cells["D3"] = "plan"
        got = board_core.parse_led_line("@@LED " + json.dumps({"cells": cells}) + "\n")
        self.assertEqual(got["U2"], "risk3")
        self.assertEqual(got["D3"], "plan")
        self.assertEqual(sorted(got.keys()), sorted(board_core.CELL_IDS))

    def test_partial_fills_off(self):
        got = board_core.parse_led_line('@@LED {"cells":{"U1":"salted"}}')
        self.assertEqual(got["U1"], "salted")
        self.assertEqual(got["D4"], "off")

    def test_bad_cell_id_ignored(self):
        self.assertIsNone(board_core.parse_led_line('@@LED {"cells":{"X9":"risk1"}}'))

    def test_bad_mode_ignored(self):
        self.assertIsNone(board_core.parse_led_line('@@LED {"cells":{"U1":"red"}}'))

    def test_bad_json_ignored(self):
        self.assertIsNone(board_core.parse_led_line("@@LED {망가진 json"))
        self.assertIsNone(board_core.parse_led_line("@@LED "))
        self.assertIsNone(board_core.parse_led_line("@@LED [1,2]"))
        self.assertIsNone(board_core.parse_led_line('@@LED {"led":{}}'))

    def test_other_line_ignored(self):
        self.assertIsNone(board_core.parse_led_line("@@TEL {}"))
        self.assertIsNone(board_core.parse_led_line("hello"))


class TelemetryTest(unittest.TestCase):
    def test_shape(self):
        tel = board_core.telemetry(0.0625, 21.5625, True, 12345, False, 7)
        self.assertEqual(set(tel.keys()), set(["t_piece", "t_air", "wet", "wet_raw", "warn", "up"]))
        self.assertEqual(tel["t_piece"], 0.06)
        self.assertIs(tel["wet"], True)
        self.assertIs(tel["warn"], False)
        self.assertIsInstance(tel["wet_raw"], int)
        self.assertIsInstance(tel["up"], int)

    def test_nulls(self):
        tel = board_core.telemetry(None, None, False, None, False, 0)
        self.assertIsNone(tel["t_piece"])
        self.assertIsNone(tel["t_air"])
        self.assertEqual(tel["wet_raw"], -1)
        line = board_core.tel_line(tel)
        self.assertTrue(line.startswith("@@TEL "))
        self.assertIn("null", line)


class LoopIndexTest(unittest.TestCase):
    def test_order(self):
        self.assertEqual([board_core.loop_index(c) for c in board_core.CELL_IDS], list(range(8)))
        self.assertEqual(board_core.loop_index("D1"), 7)
        self.assertIsNone(board_core.loop_index("X1"))
        self.assertEqual(board_core.pick_roms([b"a", b"b"], 1), (b"b", b"a"))
        self.assertEqual(board_core.pick_roms([b"a"], 5), (b"a", None))
        self.assertEqual(board_core.pick_roms([], 0), (None, None))


# ---------------------------------------------------------------- main.py USB 모드
class UsbMainTest(unittest.TestCase):
    def test_setup_logs_roms_and_piece(self):
        with fake_board():
            main, log = _load_main()
            self.assertIn("DS18B20 센서 2개", log)
            self.assertIn("시험편", log)
            self.assertIn("28:00:01", log)
            self.assertEqual(main.piece_rom, b"\x28\x00\x01")
            self.assertEqual(main.air_rom, b"\x28\x00\x02")

    def test_usb_cycle_prints_telemetry(self):
        with fake_board():
            main, _ = _load_main()
            main.ds_tick(1000)      # 변환 시작
            main.ds_tick(1800)      # 750ms 지남 → 읽기
            main.ds_tick(1900)      # 다음 변환 시작
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main.loop_once(1900)
            lines = [l for l in out.getvalue().splitlines() if l.startswith("@@TEL ")]
            self.assertEqual(len(lines), 1)
            tel = json.loads(lines[0][6:])
            self.assertEqual(set(tel.keys()), set(["t_piece", "t_air", "wet", "wet_raw", "warn", "up"]))
            self.assertEqual(tel["t_piece"], 0.5)
            self.assertEqual(tel["t_air"], 21.56)
            self.assertIs(tel["wet"], True)      # raw 20000 ≤ 30000
            self.assertEqual(tel["wet_raw"], 20000)
            self.assertIs(tel["warn"], True)     # 0.5도 + 젖음 → 로컬 경고
            self.assertIsInstance(tel["up"], int)
            self.assertEqual(_pin(15).state, 1)  # 주의 LED 즉시 켜짐

    def test_telemetry_is_one_per_second(self):
        with fake_board():
            main, _ = _load_main()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main.loop_once(5000)
                main.loop_once(5500)     # 1초가 안 됐다
                main.loop_once(6000)
            lines = [l for l in out.getvalue().splitlines() if l.startswith("@@TEL ")]
            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0][6:])
            self.assertIsNone(first["t_piece"])   # 아직 온도를 못 읽었다

    def test_usb_led_line_applied_and_stale_off(self):
        with fake_board():
            main, _ = _load_main()
            cells = dict((c, "off") for c in board_core.CELL_IDS)
            cells["U2"] = "plan"
            cells["D3"] = "salted"
            old_stdin = sys.stdin
            sys.stdin = io.StringIO("@@LED " + json.dumps({"cells": cells}) + "\n")
            try:
                main.usb_poll = FakePoll()
                with contextlib.redirect_stdout(io.StringIO()):
                    main.loop_once(5000)
                    main.show_leds(5000)
            finally:
                sys.stdin = old_stdin
            self.assertEqual(main.cells["U2"], "plan")
            led = main.cell_led
            self.assertEqual(led.pixels[1], (0, 15, 48))     # U2 = 루프 2번째 = plan 파랑
            self.assertEqual(led.pixels[5], (48, 48, 48))    # D3 = 흰색
            # 명령이 10초 넘게 없으면 꺼진다
            with contextlib.redirect_stdout(io.StringIO()):
                main.show_leds(16000)
            self.assertEqual(set(led.pixels), set([(0, 0, 0)]))

    def test_local_warn_works_without_server(self):
        with fake_board():
            main, _ = _load_main()
            FakeDS18X20.TEMPS = {b"\x28\x00\x01": -3.0, b"\x28\x00\x02": 10.0}
            main.ds_tick(100)
            main.ds_tick(900)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main.loop_once(950)      # 서버 응답이 없는 상태
            self.assertEqual(_pin(15).state, 1)
            FakeDS18X20.TEMPS = {b"\x28\x00\x01": 0.5, b"\x28\x00\x02": 21.5625}


class WifiMainTest(unittest.TestCase):
    def _run(self, main, now):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main.loop_once(now)
        return out.getvalue()

    def test_post_and_apply_led(self):
        with fake_board() as fakes:
            main, _ = _load_main()
            old = main.config.TRANSPORT
            main.config.TRANSPORT = "wifi"
            main.config.TOKEN = "team-secret"
            cells = dict((c, "off") for c in board_core.CELL_IDS)
            cells["U2"] = "risk2"
            fakes["urequests"].REPLY = {"cells": cells}
            try:
                self._run(main, 1000)
            finally:
                main.config.TRANSPORT = old
                main.config.TOKEN = ""
            self.assertEqual(main.cells["U2"], "risk2")
            call = fakes["urequests"].CALLS[0]
            self.assertTrue(call["url"].endswith("/api/board/telemetry"))
            self.assertEqual(call["headers"]["X-Token"], "team-secret")
            self.assertEqual(json.loads(call["data"]).keys(), board_core.telemetry(0, 0, False, 0, False, 0).keys())

    def test_failure_keeps_local_warning(self):
        with fake_board() as fakes:
            main, _ = _load_main()
            old = main.config.TRANSPORT
            main.config.TRANSPORT = "wifi"
            fakes["urequests"].FAIL = True
            FakeDS18X20.TEMPS = {b"\x28\x00\x01": -1.0, b"\x28\x00\x02": 3.0}
            main.ds_tick(100)
            main.ds_tick(900)
            try:
                out = self._run(main, 950)
            finally:
                main.config.TRANSPORT = old
                fakes["urequests"].FAIL = False
                FakeDS18X20.TEMPS = {b"\x28\x00\x01": 0.5, b"\x28\x00\x02": 21.5625}
            self.assertIn("서버 연결 실패", out)
            self.assertEqual(_pin(15).state, 1)      # 연결이 끊겨도 주의 LED는 켜진다
            self.assertEqual(main.cells, {})         # 서버 LED 명령은 없었다


if __name__ == "__main__":
    unittest.main()
