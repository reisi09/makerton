# ICE-ZERO 센서 Pico(pico/sensors) 시험. 하드웨어 없이 CPython으로 돈다.
#   - sensor_core: 젖음 판정, 경고 조건·히스테리시스, DHT11 순환·유지, @@SHOW 파싱, 링 픽셀, OLED 줄, @@TEL
#   - main: 가짜 모듈(machine/dht/neopixel)로 한 주기 — @@TEL 형식, 링·OLED, 로컬 경고 LED·부저
#   - ssd1306: framebuf가 없는 맥북에서도 import되고 버퍼·I2C 전송이 도는지
import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICO = os.path.join(ROOT, "pico", "sensors")
TESTS = os.path.dirname(os.path.abspath(__file__))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

import fake_mpy_sensors  # noqa: E402  (sys.path를 먼저 넣는다)


def load_module(name, filename):
    """파일 경로로 직접 모듈을 읽는다(sys.path를 오염시키지 않는다)."""
    path = os.path.join(PICO, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sensor_core = load_module("sensor_core", "sensor_core.py")


# ---------------------------------------------------------------- 가짜 하드웨어 붙이기
@contextlib.contextmanager
def fake_pico():
    """가짜 모듈을 끼우고 main을 새로 읽어 setup까지 부른다."""
    world, mods = fake_mpy_sensors.build()
    names = ("main", "config", "sensor_core", "ssd1306", "lcd1602", "machine", "dht", "neopixel")
    saved = {}
    for k in names:
        saved[k] = sys.modules.get(k)
    for k in names:
        sys.modules.pop(k, None)
    sys.modules.update(mods)
    sys.modules["sensor_core"] = sensor_core       # 순수 로직 모듈을 그대로 쓴다
    try:
        sys.modules["config"] = load_module("config", "config.py")
        sys.modules["ssd1306"] = load_module("ssd1306", "ssd1306.py")
        sys.modules["lcd1602"] = load_module("lcd1602", "lcd1602.py")
        main = load_module("main", "main.py")
        sys.modules["main"] = main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main.setup()
        main.boot_log = out.getvalue()
        yield main, world
    finally:
        for k in names:
            sys.modules.pop(k, None)
        for k in names:
            if saved[k] is not None:
                sys.modules[k] = saved[k]


@contextlib.contextmanager
def usb_input(text):
    """main이 읽는 USB 입력을 흉내낸다(stdin은 문자열, poll은 항상 준비)."""
    old = sys.stdin
    sys.stdin = io.StringIO(text)
    try:
        yield
    finally:
        sys.stdin = old


def cycle(main, now):
    """loop_once를 돌리고 main이 출력한 줄들을 돌려준다."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main.loop_once(now)
    return out.getvalue().splitlines()


def tel_of(lines):
    for line in lines:
        if line.startswith("@@TEL "):
            return json.loads(line[6:])
    return None


class FakeOled:
    """main.draw_oled가 만든 줄을 그대로 모으는 대역. 실제 화면은 Pico에서만 나온다."""

    def __init__(self):
        self.lines = []
        self.fills = 0
        self.shows = 0

    def fill(self, col):
        self.fills += 1
        self.lines = []

    def text(self, string, x, y):
        self.lines.append(string)

    def show(self):
        self.shows += 1


class FakeLcd:
    """main.draw_lcd가 쓴 두 줄을 모으는 대역."""

    def __init__(self):
        self.shown = []

    def show(self, line1, line2=""):
        self.shown.append((line1, line2))


# ---------------------------------------------------------------- 순수 로직: 젖음
class WetTest(unittest.TestCase):
    def test_when_low(self):
        self.assertTrue(sensor_core.is_wet(10000, 40000, True))
        self.assertTrue(sensor_core.is_wet(40000, 40000, True))    # 임계값 포함
        self.assertFalse(sensor_core.is_wet(40001, 40000, True))

    def test_when_high_is_reversed(self):
        self.assertTrue(sensor_core.is_wet(60000, 40000, False))
        self.assertFalse(sensor_core.is_wet(39000, 40000, False))
        self.assertTrue(sensor_core.is_wet(40000, 40000, False))

    def test_missing_value_is_dry(self):
        self.assertFalse(sensor_core.is_wet(None))


# ---------------------------------------------------------------- 순수 로직: 경고
class WarnConditionTest(unittest.TestCase):
    def test_cold_and_humid_arm_warns(self):
        t = {"N": 2.0, "E": 10.0, "S": 12.0, "W": 11.0}
        rh = {"N": 90, "E": 50, "S": 50, "W": 50}
        self.assertTrue(sensor_core.warn_condition(t, rh, False, 3.0, 85))

    def test_either_condition_alone_is_not_enough(self):
        t = {"N": 2.0, "E": 3.0, "S": 4.0, "W": 5.0}
        rh = {"N": 80, "E": 84, "S": 50, "W": 50}
        self.assertFalse(sensor_core.warn_condition(t, rh, False, 3.0, 85))

    def test_wet_with_cold_w_warns(self):
        # 젖음 센서는 W 갈래에 있다. W가 차가우면 젖음만으로도 경고다
        t = {"N": 20.0, "E": 20.0, "S": 20.0, "W": 2.5}
        rh = {"N": 50, "E": 50, "S": 50, "W": 50}
        self.assertTrue(sensor_core.warn_condition(t, rh, True, 3.0, 85))

    def test_wet_with_cold_e_does_not_warn(self):
        t = {"N": 20.0, "E": 2.5, "S": 20.0, "W": 20.0}
        rh = {"N": 50, "E": 50, "S": 50, "W": 50}
        self.assertFalse(sensor_core.warn_condition(t, rh, True, 3.0, 85))

    def test_wet_alone_does_not_warn(self):
        t = {"N": 4.0, "E": 4.0, "S": 4.0, "W": 4.0}
        rh = {"N": 50, "E": 50, "S": 50, "W": 50}
        self.assertFalse(sensor_core.warn_condition(t, rh, True, 3.0, 85))

    def test_read_failure_never_warns(self):
        t = {"N": None, "E": None, "S": None, "W": None}
        rh = {"N": None, "E": None, "S": None, "W": None}
        self.assertFalse(sensor_core.warn_condition(t, rh, False, 3.0, 85))


class WarnHysteresisTest(unittest.TestCase):
    def test_off_after_three_false(self):
        st = {"warn": False, "off": 0}
        st = sensor_core.local_warn(True, st, 3)
        self.assertTrue(st["warn"])
        self.assertEqual(st["off"], 0)
        st = sensor_core.local_warn(False, st, 3)
        self.assertTrue(st["warn"])
        st = sensor_core.local_warn(False, st, 3)
        self.assertTrue(st["warn"])
        st = sensor_core.local_warn(False, st, 3)
        self.assertFalse(st["warn"])

    def test_true_in_between_resets_counter(self):
        st = {"warn": True, "off": 0}
        st = sensor_core.local_warn(False, st, 3)
        st = sensor_core.local_warn(False, st, 3)
        self.assertEqual(st["off"], 2)
        st = sensor_core.local_warn(True, st, 3)
        self.assertEqual(st["off"], 0)
        self.assertTrue(st["warn"])

    def test_input_not_mutated(self):
        st = {"warn": True, "off": 2}
        sensor_core.local_warn(False, st, 3)
        self.assertEqual(st, {"warn": True, "off": 2})


# ---------------------------------------------------------------- 순수 로직: DHT11 순환·유지
class SensorBankTest(unittest.TestCase):
    def make(self):
        return sensor_core.SensorBank(("N", "E", "S", "W"), 2000, 10000)

    def test_rotation_and_interval(self):
        bank = self.make()
        self.assertEqual(bank.due(0), "N")
        bank.apply("N", 1.0, 70, 0)
        self.assertEqual(bank.due(100), "E")
        bank.apply("E", 1.0, 70, 20)
        self.assertEqual(bank.due(200), "S")
        bank.apply("S", 1.0, 70, 40)
        self.assertEqual(bank.due(300), "W")
        bank.apply("W", 1.0, 70, 60)
        self.assertIsNone(bank.due(1000))       # 아직 2초가 안 지났다
        self.assertEqual(bank.due(2000), "N")   # 가장 오래된 갈래부터

    def test_failure_keeps_last_value_within_hold(self):
        bank = self.make()
        bank.apply("N", 2.0, 80, 0)
        t, rh, ok = bank.measured(0)
        self.assertEqual(t["N"], 2.0)
        self.assertEqual(rh["N"], 80)
        self.assertTrue(ok["N"])

        bank.apply("N", None, None, 2500)       # 실패
        t, rh, ok = bank.measured(2500)
        self.assertEqual(t["N"], 2.0)           # 마지막 정상값 유지
        self.assertEqual(rh["N"], 80)
        self.assertFalse(ok["N"])               # 그래도 실패로 표시

        t, rh, ok = bank.measured(10000)        # 10초까지는 유지
        self.assertEqual(t["N"], 2.0)
        t, rh, ok = bank.measured(10001)        # 넘으면 null
        self.assertIsNone(t["N"])
        self.assertIsNone(rh["N"])
        self.assertFalse(ok["N"])

    def test_never_read_is_null_and_not_ok(self):
        bank = self.make()
        t, rh, ok = bank.measured(0)
        self.assertIsNone(t["E"])
        self.assertFalse(ok["E"])

    def test_out_of_range_is_failure(self):
        bank = self.make()
        bank.apply("N", 60.0, 50, 0)            # DHT11 범위(0~50°C) 밖
        self.assertIsNone(bank.measured(0)[0]["N"])
        bank.apply("E", 2.0, 150, 0)            # 습도 범위 밖
        self.assertFalse(bank.measured(0)[2]["E"])
        bank.apply("S", -1.0, 80, 0)            # DHT11은 0°C 아래를 재지 않는다
        self.assertIsNone(bank.measured(0)[0]["S"])

    def test_rounding(self):
        bank = self.make()
        bank.apply("S", 2.349, 85.6, 0)
        t, rh, ok = bank.measured(0)
        self.assertEqual(t["S"], 2.3)
        self.assertEqual(rh["S"], 85)

    def test_first_success_after_failure_sets_ok(self):
        bank = self.make()
        bank.apply("N", None, None, 0)
        self.assertFalse(bank.measured(0)[2]["N"])
        bank.apply("N", 3.0, 70, 2000)
        self.assertTrue(bank.measured(2000)[2]["N"])


# ---------------------------------------------------------------- 순수 로직: @@SHOW 파싱
class ParseShowTest(unittest.TestCase):
    def test_partial_fills_off(self):
        got = sensor_core.parse_show_line('@@SHOW {"arms":{"E":"risk3"}}')
        self.assertEqual(got["arms"]["E"], "risk3")
        for arm in ("N", "S", "W"):
            self.assertEqual(got["arms"][arm], "off")
        self.assertEqual(got["msg"], "")

    def test_full_with_msg_and_newline(self):
        arms = {"N": "risk1", "E": "plan", "S": "done", "W": "off"}
        got = sensor_core.parse_show_line("@@SHOW " + json.dumps({"arms": arms, "msg": "E 살포"}) + "\n")
        self.assertEqual(got["arms"], arms)
        self.assertEqual(got["msg"], "E 살포")

    def test_lowercase_arm_accepted(self):
        got = sensor_core.parse_show_line('@@SHOW {"arms":{"e":"risk2"}}')
        self.assertEqual(got["arms"]["E"], "risk2")

    def test_bad_arm_rejects_whole_line(self):
        self.assertIsNone(sensor_core.parse_show_line('@@SHOW {"arms":{"X":"risk1"}}'))
        self.assertIsNone(sensor_core.parse_show_line('@@SHOW {"arms":{"NE":"risk1"}}'))

    def test_bad_mode_rejects(self):
        self.assertIsNone(sensor_core.parse_show_line('@@SHOW {"arms":{"N":"red"}}'))
        self.assertIsNone(sensor_core.parse_show_line('@@SHOW {"arms":{"N":1}}'))
        self.assertIsNone(sensor_core.parse_show_line('@@SHOW {"arms":{"N":true}}'))

    def test_msg_too_long_is_cut(self):
        got = sensor_core.parse_show_line('@@SHOW {"arms":{},"msg":"0123456789abcdefghij"}')
        self.assertEqual(len(got["msg"]), sensor_core.MSG_MAX)
        self.assertEqual(got["msg"], "0123456789abcdef")

    def test_bad_msg_rejects(self):
        self.assertIsNone(sensor_core.parse_show_line('@@SHOW {"arms":{},"msg":5}'))

    def test_beacon_flag(self):
        self.assertTrue(sensor_core.parse_show_line('@@SHOW {"arms":{},"beacon":true}')["beacon"])
        self.assertFalse(sensor_core.parse_show_line('@@SHOW {"arms":{}}')["beacon"])
        self.assertIsNone(sensor_core.parse_show_line('@@SHOW {"arms":{},"beacon":1}'))
        self.assertIsNone(sensor_core.parse_show_line('@@SHOW {"arms":{},"beacon":"true"}'))

    def test_non_ascii_msg_kept_then_sanitized_at_render(self):
        got = sensor_core.parse_show_line('@@SHOW {"arms":{},"msg":"북쪽"}')
        self.assertEqual(got["msg"], "북쪽")          # 파싱은 그대로 둔다
        lines = sensor_core.oled_lines({"N": 1.0}, {}, False, False, got["msg"], 0)
        self.assertEqual(lines[0], "??")              # OLED/LCD에서 ASCII로 바꾼다

    def test_malformed(self):
        self.assertIsNone(sensor_core.parse_show_line("@@SHOW {망가진 json"))
        self.assertIsNone(sensor_core.parse_show_line("@@SHOW "))
        self.assertIsNone(sensor_core.parse_show_line("@@SHOW [1,2]"))
        self.assertIsNone(sensor_core.parse_show_line('@@SHOW {"cells":{}}'))
        self.assertIsNone(sensor_core.parse_show_line("@@TEL {}"))
        self.assertIsNone(sensor_core.parse_show_line("hello"))
        self.assertIsNone(sensor_core.parse_show_line(""))

    def test_parse_line_dispatch(self):
        got = sensor_core.parse_line('@@SHOW {"arms":{"N":"done"}}')
        self.assertEqual(got[0], "show")
        self.assertEqual(got[1]["arms"]["N"], "done")
        self.assertIsNone(sensor_core.parse_line("@@TEL {}"))


# ---------------------------------------------------------------- 순수 로직: 링·표시
class RingTest(unittest.TestCase):
    def modes(self):
        return {"N": "risk3", "E": "risk1", "S": "off", "W": "done"}

    def test_two_pixels_per_arm_in_order(self):
        px = sensor_core.ring_pixels(self.modes(), 8, 0, 255, 2)
        self.assertEqual(len(px), 8)
        self.assertEqual(px[0], (255, 0, 0))
        self.assertEqual(px[1], (255, 0, 0))
        self.assertEqual(px[2], (0, 255, 0))
        self.assertEqual(px[3], (0, 255, 0))
        self.assertEqual(px[4], (0, 0, 0))
        self.assertEqual(px[5], (0, 0, 0))
        self.assertEqual(px[6], (255, 255, 255))
        self.assertEqual(px[7], (255, 255, 255))

    def test_brightness_scales(self):
        px = sensor_core.ring_pixels(self.modes(), 8, 0, 48, 2)
        self.assertEqual(px[0], (48, 0, 0))

    def test_smaller_ring_truncates(self):
        px = sensor_core.ring_pixels(self.modes(), 4, 0, 255, 2)
        self.assertEqual(len(px), 4)
        self.assertEqual(px[2], (0, 255, 0))

    def test_plan_blinks(self):
        self.assertEqual(sensor_core.ring_rgb("plan", 0, 255), (0, 80, 255))
        self.assertEqual(sensor_core.ring_rgb("plan", 100, 255), (0, 80, 255))
        self.assertEqual(sensor_core.ring_rgb("plan", 300, 255), (0, 0, 0))

    def test_unknown_mode_is_off(self):
        self.assertEqual(sensor_core.ring_rgb("wat", 0, 255), (0, 0, 0))

    def test_show_view_stale(self):
        modes = {"N": "risk3"}
        self.assertEqual(sensor_core.show_view(modes, None, 0)["N"], "off")
        self.assertEqual(sensor_core.show_view(modes, 0, 5000)["N"], "risk3")
        self.assertEqual(sensor_core.show_view(modes, 0, 10000)["N"], "risk3")
        self.assertEqual(sensor_core.show_view(modes, 0, 10001)["N"], "off")

    def test_show_view_drops_bad_mode(self):
        self.assertEqual(sensor_core.show_view({"N": "red"}, 0, 0)["N"], "off")


# ---------------------------------------------------------------- 순수 로직: OLED·텔레메트리
class OledTest(unittest.TestCase):
    def test_four_lines_within_sixteen_chars(self):
        t = {"N": -3.1, "E": None, "S": 2.0, "W": 1.0}
        ok = {"N": True, "E": False, "S": True, "W": True}
        lines = sensor_core.oled_lines(t, ok, True, True, "", 12)
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertLessEqual(len(line), 16)
        self.assertEqual(lines[0], "ICE-ZERO SENSOR")
        self.assertIn("N -3.1", lines[1])
        self.assertIn("E --.-", lines[1])
        self.assertIn("S 2.0", lines[2])
        self.assertIn("W 1.0", lines[2])
        self.assertTrue(lines[3].startswith("WARN WET"))
        self.assertTrue(lines[3].endswith("!"))     # 못 읽은 갈래가 있다

    def test_calm_line(self):
        t = {"N": 20.0, "E": 20.0, "S": 20.0, "W": 20.0}
        ok = {"N": True, "E": True, "S": True, "W": True}
        lines = sensor_core.oled_lines(t, ok, False, False, "", 5)
        self.assertTrue(lines[3].startswith("ok DRY"))
        self.assertFalse(lines[3].endswith("!"))

    def test_msg_replaces_header(self):
        t = {"N": 1.0, "E": 1.0, "S": 1.0, "W": 1.0}
        ok = {"N": True, "E": True, "S": True, "W": True}
        lines = sensor_core.oled_lines(t, ok, False, False, "E SPRAY NOW", 5)
        self.assertEqual(lines[0], "E SPRAY NOW")


class TelemetryTest(unittest.TestCase):
    def make(self):
        t = {"N": -3.14, "E": None, "S": 2.0, "W": 1.0}
        rh = {"N": 80, "E": None, "S": 90, "W": 70}
        ok = {"N": True, "E": False, "S": True, "W": True}
        return sensor_core.telemetry(t, rh, ok, 12345, True, None, True, True, 3, False, 42)

    def test_keys_and_types(self):
        tel = self.make()
        self.assertEqual(set(tel), {"t", "rh", "ok", "wet_raw", "wet", "light_raw", "warn",
                                    "dock", "refills", "refilling", "up"})
        self.assertEqual(set(tel["t"]), {"N", "E", "S", "W"})
        self.assertEqual(tel["t"]["N"], -3.1)
        self.assertIsNone(tel["t"]["E"])
        self.assertEqual(tel["rh"]["N"], 80)
        self.assertIsNone(tel["rh"]["E"])
        self.assertTrue(tel["ok"]["N"])
        self.assertFalse(tel["ok"]["E"])
        self.assertEqual(tel["wet_raw"], 12345)
        self.assertTrue(tel["wet"])
        self.assertIsNone(tel["light_raw"])
        self.assertTrue(tel["warn"])
        self.assertTrue(tel["dock"])
        self.assertEqual(tel["refills"], 3)
        self.assertFalse(tel["refilling"])
        self.assertEqual(tel["up"], 42)

    def test_wet_raw_none_becomes_zero(self):
        tel = sensor_core.telemetry({}, {}, {}, None, False, 111, False, False, 0, False, 0)
        self.assertEqual(tel["wet_raw"], 0)
        self.assertEqual(tel["light_raw"], 111)
        self.assertIsNone(tel["t"]["N"])

    def test_tel_line_format(self):
        line = sensor_core.tel_line(self.make())
        self.assertTrue(line.startswith("@@TEL "))
        self.assertNotIn("\n", line)
        obj = json.loads(line[6:])
        self.assertIsInstance(obj["t"]["N"], float)
        self.assertIsInstance(obj["rh"]["N"], int)
        self.assertIsInstance(obj["ok"]["N"], bool)
        self.assertIsInstance(obj["up"], int)
        self.assertIsInstance(obj["wet"], bool)
        self.assertIsInstance(obj["warn"], bool)
        self.assertIsInstance(obj["wet_raw"], int)
        self.assertIsInstance(obj["dock"], bool)
        self.assertIsInstance(obj["refills"], int)
        self.assertIsInstance(obj["refilling"], bool)


# ---------------------------------------------------------------- 순수 로직: 도킹 디바운스·보충
class DebounceTest(unittest.TestCase):
    def test_short_glitch_ignored(self):
        db = sensor_core.Debouncer(50)
        self.assertFalse(db.update(True, 0))
        self.assertFalse(db.update(True, 30))          # 아직 50ms가 안 됐다
        self.assertFalse(db.update(False, 40))         # 튀는 값이 사라지면 처음부터
        self.assertFalse(db.update(True, 1000))
        self.assertTrue(db.update(True, 1050))         # 50ms 유지 → 인정

    def test_stable_change(self):
        db = sensor_core.Debouncer(50, initial=True)
        self.assertTrue(db.update(True, 0))
        self.assertTrue(db.update(False, 10))          # 아직 50ms 전
        self.assertTrue(db.update(False, 59))
        self.assertFalse(db.update(False, 60))         # 50ms 유지 → 바뀐다
        self.assertFalse(db.value)

    def test_initial_value(self):
        self.assertFalse(sensor_core.Debouncer(50).value)
        self.assertTrue(sensor_core.Debouncer(50, initial=True).value)


class RefillTest(unittest.TestCase):
    def make(self, auto=True):
        return sensor_core.RefillController(auto, 800, 1000, 20000)

    def test_auto_waits_for_settle_then_opens_once(self):
        r = self.make()
        self.assertIsNone(r.update(True, 0))           # 도킹 시작, 정착 대기
        self.assertIsNone(r.update(True, 999))
        self.assertEqual(r.update(True, 1000), 800)    # 정착 → 연다
        self.assertEqual(r.count, 1)
        self.assertTrue(r.refilling())
        self.assertIsNone(r.update(True, 3000))        # 같은 도킹에서 다시 열지 않는다
        self.assertEqual(r.count, 1)

    def test_tick_closes_after_ms(self):
        r = self.make()
        r.update(True, 0)
        r.update(True, 1000)
        self.assertFalse(r.tick(1799))
        self.assertTrue(r.tick(1800))
        self.assertFalse(r.refilling())
        self.assertFalse(r.tick(1900))

    def test_cooldown_blocks_quick_redock(self):
        r = self.make()
        r.update(True, 0)
        r.update(True, 1000)
        r.tick(2000)
        r.update(False, 3000)                          # 도킹 해제
        r.update(True, 4000)                           # 곧바로 다시 도킹
        self.assertIsNone(r.update(True, 5000))         # 쿨다운 20초 전
        self.assertEqual(r.count, 1)

    def test_next_docking_after_cooldown(self):
        r = self.make()
        r.update(True, 0)
        r.update(True, 1000)
        r.update(False, 2000)
        r.update(True, 30000)
        self.assertEqual(r.update(True, 31000), 800)
        self.assertEqual(r.count, 2)

    def test_auto_off(self):
        r = self.make(auto=False)
        r.update(True, 0)
        self.assertIsNone(r.update(True, 5000))
        self.assertEqual(r.count, 0)

    def test_manual_only_when_docked(self):
        r = self.make()
        res = r.request(500, 0)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "not_docked")
        r.update(True, 0)
        res = r.request(500, 10)
        self.assertTrue(res["ok"])
        self.assertEqual(res["ms"], 500)
        self.assertEqual(r.count, 1)
        self.assertTrue(r.refilling())

    def test_manual_bad_ms(self):
        r = self.make()
        r.update(True, 0)
        for bad in (0, 10, 99999, "800", True, None):
            self.assertFalse(r.request(bad, 10)["ok"])

    def test_manual_counts_as_the_docking_refill(self):
        r = self.make()
        r.update(True, 0)
        r.request(800, 10)
        self.assertIsNone(r.update(True, 1000))         # 자동이 겹쳐 열지 않는다
        self.assertEqual(r.count, 1)

    def test_servo_duty(self):
        self.assertEqual(sensor_core.servo_duty(0), sensor_core.GATE_DUTY_MIN)
        self.assertEqual(sensor_core.servo_duty(180), sensor_core.GATE_DUTY_MAX)
        mid = sensor_core.servo_duty(90)
        self.assertTrue(sensor_core.GATE_DUTY_MIN < mid < sensor_core.GATE_DUTY_MAX)


class BeaconTest(unittest.TestCase):
    def test_white_pair_rotates(self):
        px = sensor_core.beacon_pixels(8, 0, 255)
        self.assertEqual(px[0], (255, 255, 255))
        self.assertEqual(px[1], (255, 255, 255))
        self.assertEqual(px[2], (0, 0, 63))            # 파랑 바탕
        px = sensor_core.beacon_pixels(8, sensor_core.BEACON_STEP_MS, 255)
        self.assertEqual(px[1], (255, 255, 255))
        self.assertEqual(px[2], (255, 255, 255))
        self.assertEqual(px[0], (0, 0, 63))

    def test_wraps_around(self):
        px = sensor_core.beacon_pixels(8, 7 * sensor_core.BEACON_STEP_MS, 255)
        self.assertEqual(px[7], (255, 255, 255))
        self.assertEqual(px[0], (255, 255, 255))       # 링을 한 바퀴 돌아 이어진다

    def test_ring_pixels_beacon_switch(self):
        modes = {"N": "risk3", "E": "risk1", "S": "off", "W": "done"}
        px = sensor_core.ring_pixels(modes, 8, 0, 255, 2, True)
        self.assertEqual(px[0], (255, 255, 255))
        self.assertEqual(px[4], (0, 0, 63))
        px = sensor_core.ring_pixels(modes, 8, 0, 255, 2, False)
        self.assertEqual(px[0], (255, 0, 0))


class LcdLinesTest(unittest.TestCase):
    def test_two_lines_ascii_sixteen(self):
        t = {"N": 12.0, "E": 11.0, "S": 12.0, "W": 10.0}
        lines = sensor_core.lcd_lines("BASE OK", t)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "BASE OK")
        self.assertEqual(lines[1], "N12 E11 S12 W10")
        for line in lines:
            self.assertLessEqual(len(line), 16)
            self.assertTrue(all(32 <= ord(c) <= 126 for c in line))

    def test_missing_temp_and_korean_msg(self):
        lines = sensor_core.lcd_lines("북쪽 주의", {"N": None, "E": 11.0, "S": None, "W": 10.0})
        self.assertEqual(lines[0], "?? ??")
        self.assertEqual(lines[1], "N-- E11 S-- W10")


# ---------------------------------------------------------------- @@REFILL 파싱
class ParseRefillTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(sensor_core.parse_refill_line('@@REFILL {"ms":800}'), {"ms": 800})
        self.assertEqual(sensor_core.parse_refill_line('@@REFILL {"ms":400}\n'), {"ms": 400})

    def test_ms_default(self):
        self.assertEqual(sensor_core.parse_refill_line("@@REFILL {}"), {"ms": sensor_core.REFILL_MS})

    def test_bad_values(self):
        for line in ('@@REFILL {"ms":10}', '@@REFILL {"ms":99999}', '@@REFILL {"ms":"800"}',
                     '@@REFILL {"ms":true}', "@@REFILL {깨짐", "@@REFILL ", "@@SHOW {}"):
            self.assertIsNone(sensor_core.parse_refill_line(line))

    def test_parse_line_dispatch(self):
        self.assertEqual(sensor_core.parse_line('@@REFILL {"ms":800}'), ("refill", {"ms": 800}))


# ---------------------------------------------------------------- SSD1306 드라이버
class DriverTest(unittest.TestCase):
    def test_import_and_transfer_without_framebuf(self):
        with fake_pico() as (main, world):
            machine = sys.modules["machine"]
            driver = sys.modules["ssd1306"].SSD1306_I2C(128, 32, machine.I2C(0), 0x3C)
            self.assertEqual(driver.width, 128)
            self.assertEqual(driver.pages, 4)
            self.assertEqual(len(driver.buffer), 512)
            self.assertGreater(len(world.i2c_cmds), 10)          # 초기화 명령을 보냈다
            driver.fill(1)
            driver.text("hello", 0, 0)                           # framebuf 없음 → 그리지 않는다
            driver.show()
            self.assertEqual(world.i2c_writes[-1][0], 0x3C)
            self.assertEqual(world.i2c_writes[-1][1], 513)       # 제어 바이트 1 + 버퍼 512
            self.assertEqual(driver.buffer[0], 0xFF)


# ---------------------------------------------------------------- main 한 주기
class MainTelemetryTest(unittest.TestCase):
    def test_tel_after_one_loop(self):
        with fake_pico() as (main, world):
            lines = cycle(main, 0)
            self.assertTrue(any(line.startswith("@@TEL ") for line in lines))
            tel = tel_of(lines)
            self.assertEqual(set(tel), {"t", "rh", "ok", "wet_raw", "wet", "light_raw", "warn",
                                    "dock", "refills", "refilling", "up"})
            self.assertEqual(tel["t"]["N"], 2.0)         # 가짜 DHT11 GP2
            self.assertEqual(tel["rh"]["N"], 90)
            self.assertTrue(tel["ok"]["N"])
            self.assertIsNone(tel["t"]["E"])             # 아직 읽지 않았다
            self.assertFalse(tel["ok"]["E"])
            self.assertEqual(tel["wet_raw"], 40000)
            self.assertTrue(tel["wet"])
            self.assertEqual(tel["light_raw"], 40000)
            self.assertFalse(tel["dock"])
            self.assertEqual(tel["refills"], 0)
            self.assertFalse(tel["refilling"])
            self.assertIsInstance(tel["up"], int)

    def test_one_sensor_per_loop_round_robin(self):
        with fake_pico() as (main, world):
            cycle(main, 0)
            cycle(main, 20)
            cycle(main, 40)
            cycle(main, 60)
            self.assertEqual(world.dht_log, [2, 3, 4, 5])
            cycle(main, 80)
            self.assertEqual(len(world.dht_log), 4)      # 2초가 안 지나 읽지 않는다
            cycle(main, 2000)
            self.assertEqual(world.dht_log[-1], 2)

    def test_failure_keeps_value_then_null(self):
        with fake_pico() as (main, world):
            cycle(main, 0)                               # 네 갈래를 한 번씩 읽어 둔다
            cycle(main, 20)
            cycle(main, 40)
            cycle(main, 60)
            world.dht_fail.add(2)
            cycle(main, 2000)                            # N 실패
            tel = tel_of(cycle(main, 4020))              # 다음 @@TEL 주기
            self.assertEqual(tel["t"]["N"], 2.0)         # 마지막 정상값 유지
            self.assertFalse(tel["ok"]["N"])
            tel = tel_of(cycle(main, 11000))             # 10초가 지나면 null
            self.assertIsNone(tel["t"]["N"])
            self.assertFalse(tel["ok"]["N"])


class MainWarnTest(unittest.TestCase):
    def test_led_and_buzzer_on_warn(self):
        with fake_pico() as (main, world):
            cycle(main, 0)                               # N 2.0°C/90% → 경고
            self.assertEqual(world.outputs[main.config.PIN_LED_R], 1)
            self.assertEqual(world.outputs[main.config.PIN_LED_G], 0)
            self.assertEqual(world.outputs[main.config.PIN_BUZZER], 1)
            cycle(main, 200)
            self.assertEqual(world.outputs[main.config.PIN_BUZZER], 0)   # BEEP_MS 뒤 꺼짐
            self.assertEqual(world.outputs[main.config.PIN_LED_R], 1)    # 경고는 유지

    def test_warn_off_after_three_false(self):
        with fake_pico() as (main, world):
            for arm in main.config.ARM_ORDER:
                main.bank.apply(arm, 2.0, 90, 0)
            world.adc[main.config.PIN_WET] = 60000       # 마름
            cycle(main, 0)
            self.assertEqual(world.outputs[main.config.PIN_LED_R], 1)
            for arm in main.config.ARM_ORDER:
                main.bank.apply(arm, 10.0, 50, 0)
            cycle(main, 10)
            self.assertEqual(world.outputs[main.config.PIN_LED_R], 1)    # 1회 거짓
            cycle(main, 20)
            self.assertEqual(world.outputs[main.config.PIN_LED_R], 1)    # 2회 거짓
            cycle(main, 30)
            self.assertEqual(world.outputs[main.config.PIN_LED_R], 0)    # 3회 → 꺼짐
            self.assertEqual(world.outputs[main.config.PIN_LED_G], 1)


class MainShowTest(unittest.TestCase):
    def test_show_drives_ring_then_stales_out(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_sensors.FakePoll()
            with usb_input('@@SHOW {"arms":{"E":"risk3"},"msg":"E 살포"}\n'):
                cycle(main, 0)
            self.assertEqual(main.show_state["msg"], "E 살포")
            self.assertEqual(world.pixels[2], (48, 0, 0))     # E = 3,4번째 픽셀
            self.assertEqual(world.pixels[3], (48, 0, 0))
            self.assertEqual(world.pixels[0], (0, 0, 0))      # N은 off
            with usb_input(""):
                cycle(main, 10001)                            # 10초 넘게 조용 → 링 끔
            for px in world.pixels:
                self.assertEqual(px, (0, 0, 0))

    def test_bad_show_is_ignored(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_sensors.FakePoll()
            with usb_input('@@SHOW {"arms":{"X":"risk3"}}\n@@SHOW {깨짐\n@@TEL {}\n'):
                cycle(main, 0)
            self.assertIsNone(main.show_state["arms"])
            for px in world.pixels:
                self.assertEqual(px, (0, 0, 0))

    def test_oled_shows_msg_then_title(self):
        with fake_pico() as (main, world):
            stub = FakeOled()
            main.oled = stub
            main.last_oled_ms = None
            main.usb_poll = fake_mpy_sensors.FakePoll()
            with usb_input('@@SHOW {"arms":{"N":"risk2"},"msg":"NORTH WARN"}\n'):
                cycle(main, 0)
            self.assertEqual(len(stub.lines), 4)
            self.assertEqual(stub.lines[0], "NORTH WARN")
            self.assertIn("N 2.0", stub.lines[1])
            for line in stub.lines:
                self.assertLessEqual(len(line), 16)
            with usb_input(""):
                cycle(main, 11000)                            # 메시지가 오래되면 제목으로 돌아간다
            self.assertEqual(stub.lines[0], "ICE-ZERO SENSOR")


class MainDockRefillTest(unittest.TestCase):
    def open_duty(self, main):
        return sensor_core.servo_duty(main.config.GATE_OPEN_DEG,
                                      main.config.GATE_DUTY_MIN, main.config.GATE_DUTY_MAX)

    def closed_duty(self, main):
        return sensor_core.servo_duty(main.config.GATE_CLOSED_DEG,
                                      main.config.GATE_DUTY_MIN, main.config.GATE_DUTY_MAX)

    def dock(self, main, world, start):
        """도킹 스위치를 누르고 디바운스가 끝난 시각을 돌려준다."""
        world.inputs[main.config.PIN_DOCK] = 0
        cycle(main, start)
        t = start + main.config.DOCK_DEBOUNCE_MS + 10
        cycle(main, t)
        self.assertTrue(main.docked)
        return t

    def test_auto_refill_opens_and_closes_once(self):
        with fake_pico() as (main, world):
            self.assertEqual(world.duties[main.config.PIN_GATE], self.closed_duty(main))
            t0 = self.dock(main, world, 0)
            cycle(main, t0 + main.config.DOCK_SETTLE_MS)       # 정착 → 자동 보충
            self.assertEqual(world.duties[main.config.PIN_GATE], self.open_duty(main))
            self.assertEqual(main.refill.count, 1)
            self.assertTrue(main.refill.refilling())
            cycle(main, t0 + main.config.DOCK_SETTLE_MS + main.config.REFILL_MS + 20)
            self.assertEqual(world.duties[main.config.PIN_GATE], self.closed_duty(main))
            self.assertFalse(main.refill.refilling())
            tel = tel_of(cycle(main, t0 + 3000))
            self.assertTrue(tel["dock"])
            self.assertEqual(tel["refills"], 1)
            self.assertFalse(tel["refilling"])
            cycle(main, t0 + 31000)                            # 같은 도킹에서는 다시 안 연다
            self.assertEqual(main.refill.count, 1)

    def test_manual_refill_requires_docking(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_sensors.FakePoll()
            with usb_input('@@REFILL {"ms":400}\n'):
                cycle(main, 0)                                 # 도킹 전 → 무시
            self.assertEqual(main.refill.count, 0)
            self.assertEqual(world.duties[main.config.PIN_GATE], self.closed_duty(main))
            t0 = self.dock(main, world, 100)
            with usb_input('@@REFILL {"ms":400}\n'):
                cycle(main, t0 + 10)
            self.assertEqual(main.refill.count, 1)
            self.assertEqual(world.duties[main.config.PIN_GATE], self.open_duty(main))
            cycle(main, t0 + 500)                               # 400ms 뒤 닫힌다
            self.assertEqual(world.duties[main.config.PIN_GATE], self.closed_duty(main))


class MainLcdTest(unittest.TestCase):
    def test_lcd_two_lines_with_msg_and_temps(self):
        with fake_pico() as (main, world):
            stub = FakeLcd()
            main.lcd = stub
            main.last_lcd_ms = None
            main.lcd_shown = None
            main.usb_poll = fake_mpy_sensors.FakePoll()
            with usb_input('@@SHOW {"arms":{},"msg":"BASE OK"}\n'):
                cycle(main, 0)
            self.assertEqual(len(stub.shown), 1)
            line1, line2 = stub.shown[0]
            self.assertEqual(line1, "BASE OK")
            self.assertEqual(line2, "N2 E-- S-- W--")
            for line in (line1, line2):
                self.assertLessEqual(len(line), 16)
                self.assertTrue(all(32 <= ord(c) <= 126 for c in line))

    def test_lcd_not_rewritten_when_unchanged(self):
        with fake_pico() as (main, world):
            stub = FakeLcd()
            main.lcd = stub
            main.last_lcd_ms = None
            main.lcd_shown = None
            for arm in main.config.ARM_ORDER:
                main.bank.apply(arm, 2.0, 70, 0)
            cycle(main, 0)
            before = len(stub.shown)
            cycle(main, 600)                                    # 같은 내용이면 다시 쓰지 않는다
            self.assertEqual(len(stub.shown), before)


class MainBeaconTest(unittest.TestCase):
    def test_beacon_spins_ring(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_sensors.FakePoll()
            with usb_input('@@SHOW {"arms":{"N":"risk1"},"beacon":true}\n'):
                cycle(main, 0)
            self.assertEqual(world.pixels[0], (48, 48, 48))     # 흰색 두 픽셀
            self.assertEqual(world.pixels[1], (48, 48, 48))
            self.assertEqual(world.pixels[2], (0, 0, 12))       # 파랑 바탕
            with usb_input(""):
                cycle(main, sensor_core.BEACON_STEP_MS)          # 한 칸 돈다
            self.assertEqual(world.pixels[1], (48, 48, 48))
            self.assertEqual(world.pixels[2], (48, 48, 48))
            self.assertEqual(world.pixels[0], (0, 0, 12))

    def test_beacon_false_shows_arms(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_sensors.FakePoll()
            with usb_input('@@SHOW {"arms":{"N":"risk3"},"beacon":false}\n'):
                cycle(main, 0)
            self.assertEqual(world.pixels[0], (48, 0, 0))       # 갈래 상태(빨강)
            self.assertEqual(world.pixels[2], (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
