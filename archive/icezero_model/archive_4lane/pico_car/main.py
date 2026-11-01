# ICE-ZERO 제설차(Pico #2): 라인트레이서 + 막대 세기 + 승인 칸 살포 + UDP 상태기계.
#
# 배선(계약 9절)
#   모터 TB6612FNG(기본)  AIN1=GP10 AIN2=GP11 PWMA=GP12(왼) / BIN1=GP13 BIN2=GP14 PWMB=GP15(오른) / STBY=GP9
#   L9110S·DRV8833(DRIVER="pwm2")  왼 IN1=GP10 IN2=GP11 / 오른 IN1=GP13 IN2=GP14 (모두 PWM)
#   라인센서  L=GP18 C=GP19 R=GP20 (검정이 BLACK_LEVEL)
#   HC-SR04   VCC=VBUS(5V), TRIG=GP2, ECHO=GP3
#             ECHO는 5V가 나오므로 1kΩ(위)/2kΩ(아래) 분압으로 3.3V로 낮춘다. RP2040 핀은 5V를 견디지 못한다.
#   살포 서보  신호=GP16(50Hz), 전원=VBUS 5V + 470µF 권장
#   경광 LED   GP17(220Ω)   버튼 GP21 ↔ GND(내부 풀업)
#
# 원칙
#   - 한 바퀴(loop_once)는 수 ms 안에 끝난다. 네트워크 대기·긴 sleep이 없다(초음파만 최대 6ms).
#   - 안전 정지(초음파, 버튼, 길 잃음)는 서버와 무관하게 차 안에서 결정한다.
#   - 서버가 끊겨도 버튼 출발로 계속 돈다. Wi-Fi 재연결은 '시작만' 하고 기다리지 않는다.
import json
import select
import sys
import time

import network
import socket
from machine import PWM, Pin, time_pulse_us

import car_core
import config

# time.ticks_*는 MicroPython에만 있다. CPython 시험에서는 같은 의미로 대신한다.
if hasattr(time, "ticks_ms"):
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
    sleep_ms = time.sleep_ms
    sleep_us = time.sleep_us
else:
    def ticks_ms():
        return int(time.monotonic() * 1000) % 0x40000000

    def ticks_diff(a, b):
        return ((a - b + 0x20000000) % 0x40000000) - 0x20000000

    def sleep_ms(ms):
        time.sleep(ms / 1000.0)

    def sleep_us(us):
        time.sleep(us / 1000000.0)

SERVO_DUTY_MIN = 1638       # 0.5ms 펄스(50Hz, duty_u16 16비트)
SERVO_DUTY_MAX = 8192       # 2.5ms 펄스


def servo_duty(angle):
    """계약 9절의 서보 duty 식. SG90 0~180도."""
    return SERVO_DUTY_MIN + (SERVO_DUTY_MAX - SERVO_DUTY_MIN) * angle // 180


class Motors:
    """모터 드라이버 추상화. 비율(-1.0~1.0)을 duty로 바꾼다. 양수 = 앞으로."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.flip_l = -1.0 if cfg.LEFT_INVERT else 1.0
        self.flip_r = -1.0 if cfg.RIGHT_INVERT else 1.0
        if cfg.DRIVER == "pwm2":
            self.in_l1 = PWM(Pin(cfg.PIN_AIN1))
            self.in_l2 = PWM(Pin(cfg.PIN_AIN2))
            self.in_r1 = PWM(Pin(cfg.PIN_BIN1))
            self.in_r2 = PWM(Pin(cfg.PIN_BIN2))
            for pwm in (self.in_l1, self.in_l2, self.in_r1, self.in_r2):
                pwm.freq(cfg.MOTOR_PWM_HZ)
                pwm.duty_u16(0)
            self.pwma = None
            self.pwmb = None
            self.stby = None
        else:                                   # tb6612
            self.ain1 = Pin(cfg.PIN_AIN1, Pin.OUT)
            self.ain2 = Pin(cfg.PIN_AIN2, Pin.OUT)
            self.bin1 = Pin(cfg.PIN_BIN1, Pin.OUT)
            self.bin2 = Pin(cfg.PIN_BIN2, Pin.OUT)
            self.pwma = PWM(Pin(cfg.PIN_PWMA))
            self.pwmb = PWM(Pin(cfg.PIN_PWMB))
            self.pwma.freq(cfg.MOTOR_PWM_HZ)
            self.pwmb.freq(cfg.MOTOR_PWM_HZ)
            self.pwma.duty_u16(0)
            self.pwmb.duty_u16(0)
            self.stby = Pin(cfg.PIN_STBY, Pin.OUT)
            self.stby.value(1)

    def _duty(self, ratio):
        if ratio > 1.0:
            ratio = 1.0
        elif ratio < -1.0:
            ratio = -1.0
        return int((ratio if ratio > 0 else -ratio) * 65535)

    def _left(self, ratio):
        duty = self._duty(ratio)
        if self.pwma is None:                   # pwm2: IN1 앞으로, IN2 뒤로
            if ratio >= 0:
                self.in_l1.duty_u16(duty)
                self.in_l2.duty_u16(0)
            else:
                self.in_l1.duty_u16(0)
                self.in_l2.duty_u16(duty)
            return
        self.ain1.value(1 if ratio >= 0 else 0)
        self.ain2.value(0 if ratio >= 0 else 1)
        self.pwma.duty_u16(duty)

    def _right(self, ratio):
        duty = self._duty(ratio)
        if self.pwmb is None:
            if ratio >= 0:
                self.in_r1.duty_u16(duty)
                self.in_r2.duty_u16(0)
            else:
                self.in_r1.duty_u16(0)
                self.in_r2.duty_u16(duty)
            return
        self.bin1.value(1 if ratio >= 0 else 0)
        self.bin2.value(0 if ratio >= 0 else 1)
        self.pwmb.duty_u16(duty)

    def set(self, left, right):
        self._left(left * self.flip_l)
        self._right(right * self.flip_r)

    def stop(self):
        self.set(0.0, 0.0)


class Car:
    """제설차 한 대. loop_once(now)를 계속 부르면 상태기계가 돈다(한 번에 수 ms)."""

    def __init__(self, cfg=config, stdin=None):
        self.cfg = cfg
        self.diff = ticks_diff
        self.manual = bool(cfg.MANUAL_PUSH)     # 손으로 미는 모드: 모터를 아예 쓰지 않는다

        # 하드웨어
        self.motors = Motors(cfg)
        self.servo = PWM(Pin(cfg.PIN_SERVO))
        self.servo.freq(50)
        self.set_servo(cfg.SERVO_CLOSED_DEG)         # 부팅 중에도 통은 닫아 둔다
        self.led = Pin(cfg.PIN_LED, Pin.OUT)
        try:
            self.led_board = Pin("LED", Pin.OUT)     # 피코 W 내장 LED
        except Exception:
            self.led_board = None
        self.line_l = Pin(cfg.PIN_LINE_L, Pin.IN)
        self.line_c = Pin(cfg.PIN_LINE_C, Pin.IN)
        self.line_r = Pin(cfg.PIN_LINE_R, Pin.IN)
        self.trig = Pin(cfg.PIN_TRIG, Pin.OUT)
        self.echo = Pin(cfg.PIN_ECHO, Pin.IN)
        self.button = Pin(cfg.PIN_BUTTON, Pin.IN, Pin.PULL_UP)

        # 순수 로직
        self.pos = car_core.Position()
        self.steer = car_core.Steering(cfg.BASE_SPEED, cfg.SOFT_TURN, cfg.HARD_TURN, cfg.LOST_MS)
        self.bars = car_core.BarDetector(cfg.BAR_CONFIRM)
        self.groups = car_core.GroupClassifier(cfg.GROUP_GAP_MS)
        self.salter = car_core.Salter(cfg.SALT_MS)

        # 상태
        self.state = "IDLE"          # IDLE RUN HOLD_OBS HOLD_CMD LOST DONE
        self.plan_id = None
        self.cells = []
        self.test_run = False        # 계획 없이 버튼으로 도는 시험 주행(살포 없음)
        self.dist = None             # cm 또는 None(시간 초과 = 멀리 있음)
        self.servo_open = False
        self.seen_seq = []           # 이미 실행한 seq(최근 것만)
        self.led_state = 0
        self.far_since = None        # RESUME_CM 이상이기 시작한 시각
        self.button_raw = None
        self.button_since = 0
        self.button_down = False
        self.last_hello = None
        self.last_us = None
        self.last_bar_ms = None      # 직전 막대 시각(막대 간격 로그)
        self.last_diag = None        # 진단 모드 출력 주기
        self.last_wifi = None
        self.wifi_tried = False

        # USB(stdin) 계획 입력. CPython 시험은 파이프를 넣어 준다.
        self.stdin = stdin or sys.stdin
        self.usb_buf = ""
        try:
            self.usb = select.poll()
            self.usb.register(self.stdin, select.POLLIN)
        except (AttributeError, OSError, ValueError):
            self.usb = None

        # UDP. 서버 주소는 config로 알고 시작하고, 받은 패킷의 주소로 갱신한다.
        self.sock = None
        self.server = (cfg.SERVER_IP, cfg.SERVER_PORT)
        try:
            self.wlan = network.WLAN(network.STA_IF)
        except Exception:
            self.wlan = None
        self.open_udp()

    # ── 부팅 ────────────────────────────────────────────────────────
    def boot(self):
        """서보를 닫고 plan.json을 읽는다. 설정 요약을 한국어로 출력한다."""
        self.set_servo(self.cfg.SERVO_CLOSED_DEG)
        self.load_plan()
        self.summary()

    def summary(self):
        cfg = self.cfg
        print("ICE-ZERO 제설차 %s 시작" % cfg.CAR_ID)
        print("드라이버 %s / 검정=%d / 기준속도 %.2f (약 %.2f, 강 %.2f)" %
              (cfg.DRIVER, cfg.BLACK_LEVEL, cfg.BASE_SPEED, cfg.SOFT_TURN, cfg.HARD_TURN))
        print("서보 열기 %.0f도 / 닫기 %.0f도 / 살포 %dms" %
              (cfg.SERVO_OPEN_DEG, cfg.SERVO_CLOSED_DEG, cfg.SALT_MS))
        print("서버 %s:%d → 차 %d, Wi-Fi %s, 비밀 토큰 %s" %
              (cfg.SERVER_IP, cfg.SERVER_PORT, cfg.UDP_PORT, cfg.WIFI_SSID,
               "사용" if cfg.TOKEN else "없음"))
        if self.manual:
            print("손으로 미는 모드: 모터를 쓰지 않는다(조향·LOST·초음파 정지 없음)")
        print("계획 %s %s" % (self.plan_id, self.cells))
        print("라인센서 값 확인: 검정 테이프 위에서 L=GP%d C=GP%d R=GP%d 가 모두 %d," %
              (cfg.PIN_LINE_L, cfg.PIN_LINE_C, cfg.PIN_LINE_R, cfg.BLACK_LEVEL))
        print("  흰 바닥에서 %d이면 정상이다. 반대면 config.BLACK_LEVEL을 바꾼다." %
              (0 if cfg.BLACK_LEVEL else 1))
        if self.manual:
            print("  손으로 가려 막대 세기가 되는지, 버튼으로 출발·정지가 되는지 확인한다.")
        else:
            print("  센서를 손으로 가려 버튼을 눌러 모터가 도는지, 초음파 12cm에서 멈추는지 확인한다.")

    def open_udp(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("0.0.0.0", self.cfg.UDP_PORT))
            self.sock.setblocking(False)
        except OSError as e:
            self.sock = None
            print("UDP 소켓 열기 실패:", e)

    def connect_wifi(self, now):
        """기다리지 않는 Wi-Fi. 붙으면 True. 끊기면 WIFI_RETRY_MS마다 연결을 '시작만' 한다."""
        if self.wlan is None:
            return False
        try:
            if self.wlan.isconnected():
                return True
            if self.last_wifi is None or self.diff(now, self.last_wifi) >= self.cfg.WIFI_RETRY_MS:
                self.wlan.active(True)
                self.wlan.connect(self.cfg.WIFI_SSID, self.cfg.WIFI_PASSWORD)
                self.last_wifi = now
                if not self.wifi_tried:
                    self.wifi_tried = True
                    print("Wi-Fi 연결 시도: 2.4GHz 핫스팟인지 확인 (기다리지 않고 계속 동작)")
        except Exception as e:
            print("Wi-Fi 오류:", e)
        return False

    # ── 계획 저장·로드 ──────────────────────────────────────────────
    def apply_plan(self, plan_id, cells, source):
        """검증한 계획을 상태에 넣고 plan.json에 남긴다."""
        clean = []
        for c in cells or []:
            if c in car_core.LOOP and c not in clean:
                clean.append(c)
        self.plan_id = plan_id or "P?"
        self.cells = clean
        self.salter.set_plan(self.plan_id, clean)
        self.pos.reset()
        self.save_plan()
        print("계획 받음(%s): %s %s" % (source, self.plan_id, self.cells))

    def save_plan(self):
        try:
            with open(self.cfg.PLAN_PATH, "w") as f:
                json.dump({"plan_id": self.plan_id, "cells": self.cells}, f)
        except OSError as e:
            print("plan.json 저장 실패:", e)

    def load_plan(self):
        try:
            with open(self.cfg.PLAN_PATH) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        if not data:
            return False
        self.plan_id = data.get("plan_id")
        self.cells = [c for c in (data.get("cells") or []) if c in car_core.LOOP]
        self.salter.set_plan(self.plan_id, self.cells)
        return True

    # ── 상태 전이 ──────────────────────────────────────────────────
    def start_run(self, now, test=False):
        self.pos.start()
        self.steer.reset()
        self.bars.reset()
        self.groups.reset()
        self.salter.open_until = None
        self.servo_open = False
        self.set_servo(self.cfg.SERVO_CLOSED_DEG)
        self.far_since = None
        self.last_bar_ms = None
        self.test_run = test
        self.state = "RUN"
        self.send_event("start", now)
        if test:
            print("시험 주행 시작: 계획이 없어 살포 없이 한 바퀴만 돈다")

    def hold_obstacle(self, now):
        if self.state == "RUN":
            self.state = "HOLD_OBS"
            self.far_since = None
            self.motors_stop()
            self.send_event("obstacle", now)

    def hold_command(self, now):
        """UDP stop·버튼 비상정지: 언제나 즉시 정지하고 HOLD_CMD로 간다(계약 8절)."""
        if self.state == "HOLD_CMD":
            return False
        self.state = "HOLD_CMD"
        self.far_since = None
        self.motors_stop()
        self.send_event("estop", now)
        return True

    def resume(self, now, from_lost=False):
        """HOLD_CMD에서 재개. 버튼은 LOST에서도 재개할 수 있다(사람이 선 위에 올려놓는다)."""
        if self.state == "HOLD_CMD" or (from_lost and self.state == "LOST"):
            self.state = "RUN"
            self.steer.reset()
            self.far_since = None
            self.send_event("resume", now)
            return True
        return False

    def abort(self, now):
        self.motors_stop()
        self.servo_open = False
        self.salter.open_until = None
        self.set_servo(self.cfg.SERVO_CLOSED_DEG)
        self.pos.reset()
        self.steer.reset()
        self.bars.reset()
        self.groups.reset()
        self.state = "IDLE"
        self.test_run = False
        self.send_event("warn", now)
        print("중단: 사람이 차를 차고지로 옮긴다")

    def finish(self, now):
        self.motors_stop()
        self.steer.reset()
        self.state = "DONE"
        self.send_event("done", now)
        print("차고지 도착: 정지(DONE)")

    # ── 루프 ────────────────────────────────────────────────────────
    def loop_once(self, now):
        if self.cfg.DIAG:
            self.diag(now)
            return
        self.connect_wifi(now)
        self.poll_udp(now)
        self.poll_usb(now)
        self.poll_button(now)
        self.measure_distance(now)
        self.check_obstacle(now)
        if self.state == "RUN":
            self.drive(now)
        else:
            self.motors_stop()
        self.update_servo(now)
        self.update_led(now)
        self.send_hello(now)

    def drive(self, now):
        l, c, r = self.read_line()
        self.pos.observe(l, c, r)
        if self.manual:
            # 손으로 미는 모드: 조향·LOST 없이 표식만 센다(밀다 멈춰도 LOST가 되지 않는다)
            self.track_markers(l, c, r, now)
            return
        left, right, lost = self.steer.update(l, c, r, now)
        if lost:
            self.motors_stop()
            self.state = "LOST"
            self.send_event("lost", now)
            print("길 잃음(LOST): 라인 위에 올려놓고 버튼을 누른다")
            return
        self.motors_set(left, right)
        self.track_markers(l, c, r, now)

    def track_markers(self, l, c, r, now):
        """막대 → 묶음 → 칸·살포. 모터와 무관하게 항상 같은 규칙이다."""
        if self.bars.update(l, c, r):
            if self.cfg.LOG_MARKERS:
                if self.last_bar_ms is None:
                    print("막대 감지: 첫 막대")
                else:
                    print("막대 감지: 이전 막대에서 %d ms (GROUP_GAP_MS=%d)" %
                          (self.diff(now, self.last_bar_ms), self.cfg.GROUP_GAP_MS))
            self.last_bar_ms = now
            if self.pos.bar():
                self.groups.bar(now)
        count = self.groups.tick(now)
        if count:
            self.apply_group(count, now)

    def read_line(self):
        level = self.cfg.BLACK_LEVEL
        return (1 if self.line_l.value() == level else 0,
                1 if self.line_c.value() == level else 0,
                1 if self.line_r.value() == level else 0)

    def apply_group(self, count, now):
        before = self.pos.cell
        kind, cell, warn = self.pos.group(count)
        if self.cfg.LOG_MARKERS:
            print("묶음 확정: 막대 %d개 → %s, 칸 %s (leg %d seg %d)" %
                  (count, kind, cell, self.pos.leg, self.pos.seg))
        self.send_event("marker", now, cell=cell, grp=count)
        if warn:
            self.send_event("warn", now, cell=cell, grp=count)
            print("경고: 막대가 예상보다 많다(칸을 마지막 칸에 고정)")
        if kind == car_core.KIND_HOME:
            self.finish(now)
            return
        if cell and cell != before and self.salter.enter(cell, now):
            self.set_servo(self.cfg.SERVO_OPEN_DEG)
            self.servo_open = True
            self.send_event("salt", now, cell=cell)
            print("살포 시작: %s (%.0f도)" % (cell, self.cfg.SERVO_OPEN_DEG))

    def update_servo(self, now):
        if self.salter.tick(now):                  # 열어 둔 시간이 끝났다(Car가 직접 연 경우)
            self.set_servo(self.cfg.SERVO_CLOSED_DEG)
            self.servo_open = False

    def set_servo(self, angle):
        self.servo.duty_u16(servo_duty(angle))

    def motors_set(self, left, right):
        """손으로 미는 모드에서는 모터를 건드리지 않는다(드라이버 set 호출 없음)."""
        if not self.manual:
            self.motors.set(left, right)

    def motors_stop(self):
        if not self.manual:
            self.motors.stop()

    # ── 진단(보정) 모드 ─────────────────────────────────────────────
    def diag(self, now):
        """config.DIAG=True일 때: 주행하지 않고 센서 값만 200ms마다 출력한다."""
        self.motors_stop()
        self.measure_distance(now)
        if self.last_diag is not None and self.diff(now, self.last_diag) < 200:
            return
        self.last_diag = now
        l, c, r = self.read_line()
        print("진단 L=%d C=%d R=%d | 거리=%s | 버튼=%d" % (
            l, c, r,
            "없음" if self.dist is None else "%.1fcm" % self.dist,
            self.button.value()))

    # ── 초음파 ──────────────────────────────────────────────────────
    def measure_distance(self, now):
        if self.last_us is not None and self.diff(now, self.last_us) < self.cfg.US_PERIOD_MS:
            return
        self.last_us = now
        self.trig.value(0)
        sleep_us(2)
        self.trig.value(1)
        sleep_us(10)
        self.trig.value(0)
        t = time_pulse_us(self.echo, 1, self.cfg.US_TIMEOUT_US)
        if t < 0:
            self.dist = None                      # 시간 초과 = 멀리 있음
        else:
            cm = t / 58.0
            self.dist = int(cm * 10 + 0.5) / 10.0

    def check_obstacle(self, now):
        if self.manual:                # 손으로 미는 모드: 거리는 보고만 하고 세우지 않는다
            return
        if self.state in ("IDLE", "DONE", "HOLD_CMD"):
            return
        if self.dist is not None and self.dist <= self.cfg.STOP_CM:
            if self.state == "RUN":
                self.hold_obstacle(now)
            self.far_since = None
            return
        if self.state == "HOLD_OBS":
            if self.dist is None or self.dist >= self.cfg.RESUME_CM:
                if self.far_since is None:
                    self.far_since = now
                elif self.diff(now, self.far_since) >= self.cfg.RESUME_MS:
                    self.state = "RUN"
                    self.far_since = None
                    self.send_event("clear", now)
            else:
                self.far_since = None

    # ── 버튼 ────────────────────────────────────────────────────────
    def poll_button(self, now):
        raw = self.button.value()                  # 0 = 눌림(내부 풀업)
        if raw != self.button_raw:
            self.button_raw = raw
            self.button_since = now
            return
        if self.diff(now, self.button_since) < self.cfg.BUTTON_DEBOUNCE_MS:
            return
        if raw == 0:
            if not self.button_down:
                self.button_down = True
                self.on_button(now)
        else:
            self.button_down = False

    def on_button(self, now):
        if self.state in ("IDLE", "DONE"):
            if self.cells:
                self.start_run(now)
            else:
                self.start_run(now, test=True)      # 계획이 없으면 시험 주행
        elif self.state == "RUN":
            self.hold_command(now)
        elif self.state == "HOLD_CMD":
            self.resume(now)
        elif self.state == "LOST":
            self.resume(now, from_lost=True)
        elif self.state == "HOLD_OBS":
            self.hold_command(now)

    # ── UDP ─────────────────────────────────────────────────────────
    def poll_udp(self, now):
        if self.sock is None:
            return
        while True:
            try:
                data, addr = self.sock.recvfrom(512)
            except OSError:                        # 자료 없음(EAGAIN)도 여기로 온다
                return
            self.server = addr
            try:
                msg = json.loads(data.decode())
            except (ValueError, UnicodeError):
                continue
            if isinstance(msg, dict):
                self.handle_msg(msg, now)

    def handle_msg(self, msg, now):
        kind = msg.get("t")
        seq = msg.get("seq")
        if self.cfg.TOKEN and msg.get("tok") != self.cfg.TOKEN:
            self.warn(now, "토큰 불일치")
            self.send_ack(seq)
            return
        if seq is not None:
            if seq in self.seen_seq:               # 같은 seq는 한 번만 실행한다
                self.send_ack(seq)
                return
            self.remember_seq(seq)
        if kind == "plan":
            self.take_plan(msg, now)
        elif kind == "go":
            self.take_go(msg, now)
        elif kind == "stop":
            self.hold_command(now)
        elif kind == "resume":
            self.resume(now)                       # HOLD_CMD에서만
        elif kind == "abort":
            self.abort(now)
        self.send_ack(seq)

    def take_plan(self, msg, now):
        if self.state not in ("IDLE", "DONE"):
            self.warn(now, "계획 거절: 주행 중")
            return
        self.apply_plan(msg.get("plan_id"), msg.get("cells"), "UDP")

    def take_go(self, msg, now):
        if self.state not in ("IDLE", "DONE"):
            self.warn(now, "출발 거절: 상태 %s" % self.state)
            return
        if not self.plan_id or not self.cells:
            self.warn(now, "출발 거절: 계획 없음")
            return
        if msg.get("plan_id") != self.plan_id:
            self.warn(now, "출발 거절: 계획 번호가 다르다")
            return
        self.start_run(now)

    def remember_seq(self, seq):
        self.seen_seq.append(seq)
        if len(self.seen_seq) > 64:
            del self.seen_seq[0]

    def send_ack(self, seq):
        if seq is None:
            return
        self.send({"t": "ack", "seq": seq})

    def send_event(self, event, now, cell=None, grp=None):
        self.send({"t": "evt", "id": self.cfg.CAR_ID, "e": event,
                   "cell": cell if cell is not None else self.pos.cell,
                   "grp": grp, "plan": self.plan_id, "pos": self.pos.state()})

    def warn(self, now, text):
        print("경고:", text)
        self.send_event("warn", now)

    def send_hello(self, now):
        if self.last_hello is not None and self.diff(now, self.last_hello) < self.cfg.HELLO_MS:
            return
        self.last_hello = now
        self.send({"t": "hello", "id": self.cfg.CAR_ID, "st": self.state,
                   "plan": self.plan_id, "cells": list(self.cells),
                   "salted": list(self.salter.salted), "pos": self.pos.state(),
                   "dist": self.dist})

    def send(self, msg):
        if self.sock is None:
            return False
        if self.cfg.TOKEN:
            msg["tok"] = self.cfg.TOKEN
        try:
            self.sock.sendto(json.dumps(msg).encode(), self.server)
            return True
        except OSError:
            return False

    # ── USB 계획 입력 ───────────────────────────────────────────────
    def poll_usb(self, now):
        if self.usb is None:
            return
        while self.usb.poll(0):
            ch = self.stdin.read(1)
            if not ch:
                return
            if ch != "\n":
                if len(self.usb_buf) < 600:
                    self.usb_buf += ch
                else:
                    self.usb_buf = ""
                continue
            line, self.usb_buf = self.usb_buf.strip(), ""
            if line.startswith("@@PLAN "):
                self.take_usb_plan(line[7:], now)

    def take_usb_plan(self, text, now):
        if self.state not in ("IDLE", "DONE"):
            print("USB 계획 거절: 지금 상태 %s" % self.state)
            return
        try:
            msg = json.loads(text)
        except ValueError:
            print("USB 계획 형식 오류: @@PLAN {json} 한 줄이어야 한다")
            return
        if not isinstance(msg, dict):
            print("USB 계획 형식 오류: JSON 객체가 아니다")
            return
        self.apply_plan(msg.get("plan_id"), msg.get("cells"), "USB")

    # ── 경광 LED ────────────────────────────────────────────────────
    def update_led(self, now):
        state = self.state
        if state == "RUN":
            on = 1
        elif state in ("HOLD_CMD", "LOST"):
            on = 1 if (now // 150) % 2 == 0 else 0
        elif state == "HOLD_OBS":
            on = 1 if (now // 300) % 2 == 0 else 0
        elif state == "DONE":
            on = 1 if now % 2000 < 120 else 0
        else:                                       # IDLE
            on = 1 if now % 1200 < 100 else 0
        if on != self.led_state:
            self.led_state = on
            self.led.value(on)
            if self.led_board is not None:
                self.led_board.value(on)


def main():
    car = Car()
    car.boot()
    while True:
        try:
            car.loop_once(ticks_ms())
        except Exception as e:                      # 한 번의 예외로 차가 멈추지 않게
            print("루프 오류:", e)
            car.motors_stop()
            sleep_ms(200)
        sleep_ms(config.LOOP_MS)


if __name__ == "__main__":
    main()
