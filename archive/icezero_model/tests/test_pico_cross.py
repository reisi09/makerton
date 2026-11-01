# ICE-ZERO 사거리 보드(pico_cross) 시험. 하드웨어 없이 CPython으로 돈다.
#   - cross_core: 줄 파싱·검증, 살포 큐(순서·중복·STOP·최대), LED 색·stale, 경고 히스테리시스
#   - main: 가짜 모듈(machine/onewire/ds18x20/neopixel)로 한 사이클 — 서보 duty 변화와 '@@EVT' 형식
import contextlib
import importlib
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICO = os.path.join(ROOT, "pico_cross")
TESTS = os.path.dirname(os.path.abspath(__file__))
for _p in (TESTS, PICO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cross_core  # noqa: E402  (sys.path를 먼저 넣는다)
import fake_mpy_cross  # noqa: E402


# ---------------------------------------------------------------- 가짜 하드웨어 붙이기
@contextlib.contextmanager
def fake_pico():
    """가짜 모듈을 끼우고 main을 새로 import해 setup까지 부른다."""
    world, mods = fake_mpy_cross.build()
    names = ("machine", "onewire", "ds18x20", "neopixel", "main", "config")
    saved = {}
    for k in names:
        saved[k] = sys.modules.get(k)
    for k in ("main", "config"):
        sys.modules.pop(k, None)
    sys.modules.update(mods)
    try:
        main = importlib.import_module("main")
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


def lines_of(lines, prefix):
    return [l for l in lines if l.startswith(prefix)]


def tel_of(lines):
    tel = lines_of(lines, "@@TEL ")
    return json.loads(tel[0][6:]) if tel else None


def evts_of(lines):
    return [json.loads(l[6:]) for l in lines_of(lines, "@@EVT ")]


# ---------------------------------------------------------------- 순수 로직: 파싱
class ParseLedTest(unittest.TestCase):
    def test_valid_partial_fills_off(self):
        got = cross_core.parse_led_line('@@LED {"arms":{"E":"risk3"}}')
        self.assertEqual(got["E"], "risk3")
        for arm in ("N", "S", "W"):
            self.assertEqual(got[arm], "off")

    def test_full_and_newline(self):
        arms = {"N": "risk1", "E": "plan", "S": "done", "W": "off"}
        got = cross_core.parse_led_line("@@LED " + json.dumps({"arms": arms}) + "\n")
        self.assertEqual(got, arms)

    def test_lowercase_arm_accepted(self):
        self.assertEqual(cross_core.parse_led_line('@@LED {"arms":{"e":"risk2"}}')["E"], "risk2")

    def test_bad_arm_rejects_whole_line(self):
        self.assertIsNone(cross_core.parse_led_line('@@LED {"arms":{"X":"risk1"}}'))
        self.assertIsNone(cross_core.parse_led_line('@@LED {"arms":{"NE":"risk1"}}'))

    def test_bad_mode_rejects(self):
        self.assertIsNone(cross_core.parse_led_line('@@LED {"arms":{"N":"red"}}'))
        self.assertIsNone(cross_core.parse_led_line('@@LED {"arms":{"N":1}}'))

    def test_malformed(self):
        self.assertIsNone(cross_core.parse_led_line("@@LED {망가진 json"))
        self.assertIsNone(cross_core.parse_led_line("@@LED "))
        self.assertIsNone(cross_core.parse_led_line("@@LED [1,2]"))
        self.assertIsNone(cross_core.parse_led_line('@@LED {"cells":{}}'))
        self.assertIsNone(cross_core.parse_led_line("@@TEL {}"))
        self.assertIsNone(cross_core.parse_led_line("hello"))


class ParseSprayTest(unittest.TestCase):
    def test_valid(self):
        cmd = cross_core.parse_spray_line('@@SPRAY {"seq":7,"arm":"E","ms":600}')
        self.assertEqual(cmd, {"seq": 7, "arm": "E", "ms": 600})

    def test_ms_defaults(self):
        self.assertEqual(cross_core.parse_spray_line('@@SPRAY {"seq":1,"arm":"N"}')["ms"], 600)

    def test_arm_normalized(self):
        self.assertEqual(cross_core.parse_spray_line('@@SPRAY {"seq":1,"arm":" w "}')["arm"], "W")

    def test_bad_arm(self):
        for arm in ("X", "NE", "", "1"):
            self.assertIsNone(cross_core.parse_spray_line(
                '@@SPRAY {"seq":1,"arm":"%s"}' % arm))

    def test_bad_seq(self):
        self.assertIsNone(cross_core.parse_spray_line('@@SPRAY {"seq":"1","arm":"E"}'))
        self.assertIsNone(cross_core.parse_spray_line('@@SPRAY {"seq":-1,"arm":"E"}'))
        self.assertIsNone(cross_core.parse_spray_line('@@SPRAY {"seq":true,"arm":"E"}'))
        self.assertIsNone(cross_core.parse_spray_line('@@SPRAY {"arm":"E"}'))

    def test_ms_range(self):
        self.assertIsNone(cross_core.parse_spray_line('@@SPRAY {"seq":1,"arm":"E","ms":10}'))
        self.assertIsNone(cross_core.parse_spray_line('@@SPRAY {"seq":1,"arm":"E","ms":99999}'))
        self.assertIsNone(cross_core.parse_spray_line('@@SPRAY {"seq":1,"arm":"E","ms":"600"}'))
        self.assertIsNotNone(cross_core.parse_spray_line('@@SPRAY {"seq":1,"arm":"E","ms":50}'))


class ParseStopTest(unittest.TestCase):
    def test_forms(self):
        self.assertTrue(cross_core.parse_stop_line("@@STOP"))
        self.assertTrue(cross_core.parse_stop_line("@@STOP {}"))
        self.assertTrue(cross_core.parse_stop_line("  @@STOP  \n"))
        self.assertFalse(cross_core.parse_stop_line("@@STOPPED"))
        self.assertFalse(cross_core.parse_stop_line("@@SPRAY {}"))

    def test_parse_line_dispatch(self):
        self.assertEqual(cross_core.parse_line("@@STOP {}"), ("stop", None))
        self.assertEqual(cross_core.parse_line('@@SPRAY {"seq":2,"arm":"S"}')[0], "spray")
        self.assertEqual(cross_core.parse_line('@@LED {"arms":{"N":"off"}}')[0], "led")
        self.assertIsNone(cross_core.parse_line("@@TEL {}"))
        self.assertIsNone(cross_core.parse_line(""))


# ---------------------------------------------------------------- 순수 로직: 살포 큐
class QueueTest(unittest.TestCase):
    def test_one_at_a_time_and_order(self):
        q = cross_core.SprayQueue()
        q.submit(1, "E", 600, 0)
        q.submit(2, "W", 400, 0)
        q.submit(3, "N", 300, 0)
        self.assertEqual(q.tick(0), [{"e": "spray_start", "seq": 1, "arm": "E"}])
        self.assertTrue(q.busy())
        self.assertEqual(q.tick(300), [])                 # 아직 열려 있다
        self.assertEqual(q.tick(599), [])
        self.assertEqual(q.tick(600), [                        # 닫고 다음 것을 연다
            {"e": "spray_done", "seq": 1, "arm": "E"},
            {"e": "spray_start", "seq": 2, "arm": "W"},
        ])
        self.assertEqual(q.tick(1000), [
            {"e": "spray_done", "seq": 2, "arm": "W"},
            {"e": "spray_start", "seq": 3, "arm": "N"},
        ])
        self.assertEqual(q.tick(1300), [{"e": "spray_done", "seq": 3, "arm": "N"}])
        self.assertFalse(q.busy())
        self.assertEqual(q.tick(2000), [])

    def test_same_seq_runs_once(self):
        q = cross_core.SprayQueue()
        self.assertEqual(q.submit(5, "E", 600, 0)["status"], "queued")
        self.assertEqual(q.tick(0)[0]["e"], "spray_start")
        self.assertEqual(q.submit(5, "E", 600, 100)["status"], "dup")   # 실행 중 재전송
        self.assertEqual(q.tick(100), [])                               # 중복 시작 없음
        self.assertEqual(q.tick(600), [{"e": "spray_done", "seq": 5, "arm": "E"}])

    def test_finished_seq_answers_done_again(self):
        q = cross_core.SprayQueue()
        q.submit(9, "S", 100, 0)
        q.tick(0)
        q.tick(100)
        self.assertEqual(q.submit(9, "S", 100, 200)["status"], "done")
        self.assertEqual(q.tick(300), [])              # 다시 실행하지 않는다

    def test_queue_max(self):
        q = cross_core.SprayQueue(max_queue=4)
        q.submit(1, "N", 600, 0)
        q.tick(0)                                     # 1번이 실행 중
        for seq in (2, 3, 4, 5):
            self.assertEqual(q.submit(seq, "E", 600, 0)["status"], "queued")
        self.assertEqual(q.pending(), 4)
        self.assertEqual(q.submit(6, "W", 600, 0)["status"], "reject")

    def test_stop_closes_and_clears(self):
        q = cross_core.SprayQueue()
        q.submit(1, "E", 600, 0)
        q.submit(2, "W", 600, 0)
        q.tick(0)
        ev = q.stop()
        self.assertEqual(ev, {"e": "stopped", "seq": 1, "arm": "E"})
        self.assertFalse(q.busy())
        self.assertEqual(q.pending(), 0)
        self.assertEqual(q.tick(1000), [])             # 큐가 비었으니 아무것도 열지 않는다

    def test_stop_when_idle(self):
        q = cross_core.SprayQueue()
        self.assertEqual(q.stop()["e"], "stopped")
        self.assertEqual(q.stop()["seq"], 0)


# ---------------------------------------------------------------- 순수 로직: LED
class LedColorTest(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(cross_core.led_rgb("risk1"), (0, 48, 0))       # 초록
        self.assertEqual(cross_core.led_rgb("risk3"), (48, 0, 0))       # 빨강
        yellow = cross_core.led_rgb("risk2")
        self.assertTrue(yellow[0] > 0 and yellow[1] > 0 and yellow[2] == 0)
        white = cross_core.led_rgb("done")
        self.assertTrue(white[0] == white[1] == white[2] > 0)           # 흰색
        self.assertEqual(cross_core.led_rgb("off"), (0, 0, 0))
        self.assertEqual(cross_core.led_rgb("이상한값"), (0, 0, 0))

    def test_plan_blinks_2hz(self):
        self.assertEqual(cross_core.led_rgb("plan", 0), (0, 15, 48))
        self.assertEqual(cross_core.led_rgb("plan", 249), (0, 15, 48))  # 켜진 구간
        self.assertEqual(cross_core.led_rgb("plan", 300), (0, 0, 0))    # 꺼진 구간
        self.assertEqual(cross_core.led_rgb("plan", 500)[2], 48)        # 다음 주기

    def test_brightness(self):
        self.assertEqual(cross_core.led_rgb("done", 0, 255), (255, 255, 255))
        self.assertTrue(max(cross_core.led_rgb("done")) <= 64)

    def test_servo_duty_matches_starter(self):
        # 스타터 pico/main.py: duty_u16(1638 + (8192-1638) * angle // 180)
        self.assertEqual(cross_core.servo_duty(0), 1638)
        self.assertEqual(cross_core.servo_duty(60), 3822)
        self.assertEqual(cross_core.servo_duty(180), 8192)


class LedViewTest(unittest.TestCase):
    def test_recent(self):
        arms = {"N": "risk1", "E": "plan", "S": "done", "W": "risk3"}
        view = cross_core.led_view(arms, 1000, 2000)
        self.assertEqual(view, arms)

    def test_stale_is_off(self):
        arms = {"N": "risk1", "E": "risk2", "S": "risk3", "W": "plan"}
        self.assertEqual(set(cross_core.led_view(arms, 1000, 11000, 10000).values()), set(["off"]))

    def test_no_command_is_off(self):
        self.assertEqual(set(cross_core.led_view({}, None, 0).values()), set(["off"]))
        self.assertEqual(set(cross_core.led_view(None, 500, 600).values()), set(["off"]))

    def test_unknown_mode_falls_back(self):
        view = cross_core.led_view({"N": "파랑", "E": "risk2"}, 0, 10)
        self.assertEqual(view["N"], "off")
        self.assertEqual(view["E"], "risk2")


# ---------------------------------------------------------------- 순수 로직: 경고·젖음·텔레메트리
class WarnTest(unittest.TestCase):
    def test_three_false_turns_off(self):
        st = cross_core.local_warn(0.5, True, {"warn": False, "off": 0})
        self.assertTrue(st["warn"])                     # 1.0 이하 + 젖음 → 켜짐
        for _ in range(2):
            st = cross_core.local_warn(5.0, False, st)
            self.assertTrue(st["warn"])
        st = cross_core.local_warn(5.0, False, st)      # 3회 연속 거짓 → 꺼짐
        self.assertFalse(st["warn"])

    def test_on_conditions(self):
        self.assertTrue(cross_core.local_warn(1.0, True, {})["warn"])     # 경계 포함
        self.assertFalse(cross_core.local_warn(1.0, False, {})["warn"])   # 1.0인데 마름
        self.assertTrue(cross_core.local_warn(-2.0, False, {})["warn"])   # 어는점 이하
        self.assertFalse(cross_core.local_warn(0.5, False, {})["warn"])

    def test_none_temperature_holds(self):
        st = {"warn": True, "off": 0}
        for _ in range(5):
            st = cross_core.local_warn(None, True, st)
        self.assertTrue(st["warn"])                     # 센서 오류로 표시가 흔들리지 않는다
        self.assertFalse(cross_core.local_warn(None, True, {"warn": False, "off": 0})["warn"])

    def test_does_not_mutate_input(self):
        st = {"warn": True, "off": 0}
        cross_core.local_warn(5.0, False, st)
        self.assertEqual(st, {"warn": True, "off": 0})


class WetTest(unittest.TestCase):
    def test_when_low(self):
        self.assertTrue(cross_core.is_wet(100, 30000, True))
        self.assertTrue(cross_core.is_wet(30000, 30000, True))   # 경계
        self.assertFalse(cross_core.is_wet(60000, 30000, True))

    def test_when_high(self):
        self.assertTrue(cross_core.is_wet(60000, 30000, False))
        self.assertFalse(cross_core.is_wet(100, 30000, False))

    def test_none(self):
        self.assertFalse(cross_core.is_wet(None, 30000, True))


class TelemetryTest(unittest.TestCase):
    def test_shape(self):
        tel = cross_core.telemetry(0.0625, 21.5625, True, 12345, False, True, 7)
        self.assertEqual(set(tel.keys()),
                         set(["t_bridge", "t_air", "wet", "wet_raw", "warn", "busy", "up"]))
        self.assertEqual(tel["t_bridge"], 0.06)
        self.assertIs(tel["wet"], True)
        self.assertIs(tel["busy"], True)
        self.assertIsInstance(tel["up"], int)

    def test_nulls(self):
        tel = cross_core.telemetry(None, None, False, None, False, False, 0)
        self.assertIsNone(tel["t_bridge"])
        self.assertEqual(tel["wet_raw"], -1)
        line = cross_core.tel_line(tel)
        self.assertTrue(line.startswith("@@TEL "))
        self.assertIn("null", line)

    def test_event_line(self):
        line = cross_core.evt_line(cross_core.event("spray_done", 3, "W"))
        self.assertEqual(line, '@@EVT {"e": "spray_done", "seq": 3, "arm": "W"}')

    def test_pick_roms(self):
        self.assertEqual(cross_core.pick_roms([b"a", b"b"], 1), (b"b", b"a"))
        self.assertEqual(cross_core.pick_roms([b"a"], 5), (b"a", None))
        self.assertEqual(cross_core.pick_roms([], 0), (None, None))


# ---------------------------------------------------------------- main.py (가짜 하드웨어)
class MainSetupTest(unittest.TestCase):
    def test_boot_log_and_roms(self):
        with fake_pico() as (main, world):
            self.assertIn("DS18B20 센서 2개", main.boot_log)
            self.assertIn("시험편(config.PIECE_INDEX=0)", main.boot_log)
            self.assertIn("28:00:01", main.boot_log)
            self.assertEqual(main.bridge_rom, b"\x28\x00\x01")
            self.assertEqual(main.air_rom, b"\x28\x00\x02")
            # 서보 4개는 닫힌 각도로 시작한다
            for pin in (18, 19, 20, 21):
                self.assertEqual(world.duties[pin], cross_core.servo_duty(0))

    def test_telemetry_cycle(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            main.ds_tick(1000)          # 변환 시작
            main.ds_tick(1800)          # 750ms 지남 → 읽기
            with usb_input(""):
                lines = cycle(main, 1900)
            tel = tel_of(lines)
            self.assertEqual(tel["t_bridge"], 0.5)
            self.assertEqual(tel["t_air"], 21.56)
            self.assertIs(tel["wet"], True)          # raw 20000 ≤ 30000
            self.assertEqual(tel["wet_raw"], 20000)
            self.assertIs(tel["warn"], True)         # 0.5도 + 젖음 → 로컬 경고
            self.assertIs(tel["busy"], False)
            self.assertEqual(world.outputs[15], 1)   # 주의 LED 즉시 켜짐

    def test_85_degree_is_dropped(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            world.temps[b"\x28\x00\x01"] = 85.0
            main.ds_tick(1000)
            main.ds_tick(1800)
            with usb_input(""):
                tel = tel_of(cycle(main, 1900))
            self.assertIsNone(tel["t_bridge"])       # 85.0은 '측정 실패'
            self.assertIs(tel["warn"], False)

    def test_telemetry_once_per_second(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            with usb_input(""):
                a = cycle(main, 5000)
                b = cycle(main, 5500)
                c = cycle(main, 6000)
            self.assertEqual(len(lines_of(a, "@@TEL ")), 1)
            self.assertEqual(len(lines_of(b, "@@TEL ")), 0)
            self.assertEqual(len(lines_of(c, "@@TEL ")), 1)

    def test_led_command_and_stale_off(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            cmd = '@@LED {"arms":{"N":"risk2","E":"plan","S":"risk3","W":"done"}}'
            with usb_input(cmd + "\n"):
                cycle(main, 5000)
            self.assertEqual(main.arms_modes["E"], "plan")
            self.assertEqual(world.pixels[0], (48, 33, 0))    # N = risk2 노랑(밝기 48)
            self.assertEqual(world.pixels[1], (0, 15, 48))    # E = plan 파랑(켜진 구간)
            self.assertEqual(world.pixels[2], (48, 0, 0))     # S = risk3 빨강
            self.assertEqual(world.pixels[3], (48, 48, 48))   # W = done 흰색
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main.show_leds(16000)                          # 명령이 10초 넘게 없다
            self.assertEqual(set(world.pixels), set([(0, 0, 0)]))

    def test_spray_opens_then_closes(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            with usb_input('@@SPRAY {"seq":7,"arm":"E","ms":600}\n'):
                first = cycle(main, 1000)
            events = evts_of(first)
            self.assertEqual(events[0]["e"], "spray_start")
            self.assertEqual(events[0]["seq"], 7)
            self.assertEqual(events[0]["arm"], "E")
            self.assertEqual(world.duties[19], cross_core.servo_duty(60))   # E 서보 열림
            self.assertEqual(world.duties[18], cross_core.servo_duty(0))    # 다른 갈래는 닫힘
            self.assertEqual(world.outputs[17], 1)                          # 부저 짧게 울림
            self.assertIs(tel_of(first)["busy"], True)
            self.assertGreaterEqual(tel_of(first)["up"], 0)

            middle = cycle(main, 1300)                       # 아직 열려 있다
            self.assertEqual(evts_of(middle), [])
            self.assertEqual(world.duties[19], cross_core.servo_duty(60))

            last = cycle(main, 1600)                         # 600ms 지남 → 닫기
            events = evts_of(last)
            self.assertEqual(events[0]["e"], "spray_done")
            self.assertEqual(events[0]["seq"], 7)
            self.assertEqual(world.duties[19], cross_core.servo_duty(0))
            self.assertIs(main.queue.busy(), False)
            self.assertIs(tel_of(cycle(main, 2600))["busy"], False)
            self.assertEqual(world.outputs[17], 0)           # 부저는 루프에서 꺼진다

    def test_duplicate_seq_does_not_spray_twice(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            line = '@@SPRAY {"seq":7,"arm":"E","ms":600}\n'
            with usb_input(line + line):
                cycle(main, 1000)
            self.assertEqual(len(evts_of(cycle(main, 1000))), 0)
            done = evts_of(cycle(main, 1600))
            self.assertEqual([e["e"] for e in done], ["spray_done"])
            # 이미 끝난 seq를 다시 보내면 실행 없이 완료만 다시 알린다
            with usb_input(line):
                again = cycle(main, 2000)
            self.assertEqual([e["e"] for e in evts_of(again)], ["spray_done"])
            self.assertEqual(world.duties[19], cross_core.servo_duty(0))

    def test_bad_arm_is_rejected(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            with usb_input('@@SPRAY {"seq":3,"arm":"X","ms":600}\n'):
                lines = cycle(main, 1000)
            events = evts_of(lines)
            self.assertEqual(events[0]["e"], "spray_reject")
            self.assertEqual(events[0]["seq"], 3)     # seq는 최대한 살려서 알린다
            self.assertEqual(world.duties[18], cross_core.servo_duty(0))
            self.assertIs(main.queue.busy(), False)

    def test_malformed_spray_is_rejected(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            with usb_input('@@SPRAY {"seq":4,"arm":"E","ms":1}\n'):
                lines = cycle(main, 1000)
            events = evts_of(lines)
            self.assertEqual(events[0]["e"], "spray_reject")
            self.assertEqual(events[0]["seq"], 4)     # ms가 범위 밖이라 거절

    def test_stop_closes_everything(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            with usb_input('@@SPRAY {"seq":1,"arm":"S","ms":600}\n'):
                cycle(main, 1000)
            self.assertEqual(world.duties[20], cross_core.servo_duty(60))
            with usb_input("@@STOP {}\n"):
                lines = cycle(main, 1100)
            events = evts_of(lines)
            self.assertEqual(events[0]["e"], "stopped")
            self.assertEqual(events[0]["seq"], 1)
            self.assertEqual(events[0]["arm"], "S")
            for pin in (18, 19, 20, 21):
                self.assertEqual(world.duties[pin], cross_core.servo_duty(0))
            self.assertIs(main.queue.busy(), False)
            self.assertIs(tel_of(cycle(main, 2100))["busy"], False)
            # 큐가 비었으므로 시간이 지나도 아무 일도 없다
            self.assertEqual(evts_of(cycle(main, 2000)), [])

    def test_two_arms_take_turns(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            both = ('@@SPRAY {"seq":1,"arm":"N","ms":300}\n'
                    '@@SPRAY {"seq":2,"arm":"W","ms":300}\n')
            with usb_input(both):
                cycle(main, 0)
            self.assertEqual(world.duties[18], cross_core.servo_duty(60))   # N 먼저
            self.assertEqual(world.duties[21], cross_core.servo_duty(0))
            step = evts_of(cycle(main, 300))
            self.assertEqual([e["e"] for e in step], ["spray_done", "spray_start"])
            self.assertEqual(step[1]["arm"], "W")
            self.assertEqual(world.duties[18], cross_core.servo_duty(0))
            self.assertEqual(world.duties[21], cross_core.servo_duty(60))

    def test_local_warn_works_without_mac(self):
        with fake_pico() as (main, world):
            main.usb_poll = fake_mpy_cross.FakePoll()
            world.temps[b"\x28\x00\x01"] = -3.0
            world.adc_raw = 60000        # 마름
            main.ds_tick(100)
            main.ds_tick(900)
            with usb_input(""):
                lines = cycle(main, 950)     # 맥 명령이 하나도 없는 상태
            self.assertEqual(world.outputs[15], 1)       # 어는점 이하 → 주의 LED
            self.assertIs(tel_of(lines)["warn"], True)


if __name__ == "__main__":
    unittest.main()
