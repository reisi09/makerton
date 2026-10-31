# ICE-ZERO 제설차(Pico 2 W) 하드웨어·통신. 판단은 car_core.py가 한다.
#
# 이 파일은 비차단 루프다. time.ticks_us()를 기준으로 STEP_US마다 하프스텝 하나를 밀고,
# 그 사이에 UDP·버튼·초음파·텔레메트리를 돌린다.
# 초음파는 SONAR_PERIOD_MS마다 한 번, 최대 SONAR_TIMEOUT_US(4ms)만 기다린다.
# 스텝 시각은 절대 시각(next_step_us)으로 잡으므로 측정 지연이 쌓이지 않는다.
# 밀린 시간이 2스텝을 넘으면 그만큼은 버리고 지금부터 다시 센다(몰아서 돌리면 모터가 헛돈다).
# 그래서 100ms마다 4ms를 재면 평균 4% 느려지고, 계획은 스텝 수로 끝나므로 자세는 틀어지지 않는다.
#
# run()은 Thonny에서 이 파일을 열고 실행(F5)한다. 배선만 볼 때는 hwtest.py를 쓴다.

import time

import machine
import network
import socket
from machine import PWM, Pin

import car_core
import config

if hasattr(time, "ticks_us"):
    ticks_us = time.ticks_us
    ticks_ms = time.ticks_ms
    sleep_us = time.sleep_us
    sleep_ms = time.sleep_ms
else:                                   # CPython에서 그냥 돌려 볼 때
    def ticks_us():
        return int(time.time() * 1000000) & 0x3FFFFFFF

    def ticks_ms():
        return int(time.time() * 1000) & 0x3FFFFFFF

    def sleep_us(n):
        time.sleep(n / 1000000.0)

    def sleep_ms(n):
        time.sleep(n / 1000.0)


# ── 모터 ────────────────────────────────────────────────────────────
class Motors(object):
    """ULN2003 두 개. 하프스텝 8단계를 순서대로 밀어낸다."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.left_pins = []
        self.right_pins = []
        for num in cfg.PIN_LEFT:
            self.left_pins.append(Pin(num, Pin.OUT))
        for num in cfg.PIN_RIGHT:
            self.right_pins.append(Pin(num, Pin.OUT))
        self.left_idx = 0
        self.right_idx = 0
        self.energized = False
        self.off()

    def _write(self, pins, index):
        pattern = car_core.HALF_STEP[index % 8]
        for i in range(4):
            pins[i].value(pattern[i])

    def _clear(self, pins):
        for i in range(4):
            pins[i].value(0)

    def step(self, left, right):
        """스텝 1회. 0이면 그쪽 코일을 끈다(발열·소음 방지)."""
        left = -left if self.cfg.LEFT_INVERT else left
        right = -right if self.cfg.RIGHT_INVERT else right
        if left:
            self.left_idx = (self.left_idx + (1 if left > 0 else -1)) % 8
            self._write(self.left_pins, self.left_idx)
        else:
            self._clear(self.left_pins)
        if right:
            self.right_idx = (self.right_idx + (1 if right > 0 else -1)) % 8
            self._write(self.right_pins, self.right_idx)
        else:
            self._clear(self.right_pins)
        self.energized = bool(left or right)

    def off(self):
        self._clear(self.left_pins)
        self._clear(self.right_pins)
        self.energized = False


# ── 서보 ────────────────────────────────────────────────────────────
class Servo(object):
    """SG90. 각도가 바뀔 때만 duty를 다시 쓴다(떨림 방지)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.pwm = PWM(Pin(cfg.PIN_SERVO))
        self.pwm.freq(cfg.SERVO_HZ)
        self.angle = None
        self.period_us = 1000000.0 / cfg.SERVO_HZ

    def set(self, deg):
        if deg == self.angle:
            return
        us = self.cfg.SERVO_MIN_US + (self.cfg.SERVO_MAX_US - self.cfg.SERVO_MIN_US) * deg / 180.0
        self.pwm.duty_u16(int(us * 65535.0 / self.period_us))
        self.angle = deg


# ── 표시 ────────────────────────────────────────────────────────────
class Led(object):
    """3색 LED 모듈로 상태를 보여 준다."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.r = Pin(cfg.PIN_LED_R, Pin.OUT)
        self.g = Pin(cfg.PIN_LED_G, Pin.OUT)
        self.b = Pin(cfg.PIN_LED_B, Pin.OUT)
        self.set(False, False, False)

    def set(self, r, g, b):
        on = 1 if self.cfg.LED_ACTIVE_HIGH else 0
        off = 1 - on
        self.r.value(on if r else off)
        self.g.value(on if g else off)
        self.b.value(on if b else off)

    def show(self, state, online, now_ms):
        blink = (now_ms // 500) % 2 == 0
        if not online:
            self.set(False, False, blink)              # 연결 전: 파랑 깜빡
        elif state == car_core.STATE_RUN:
            self.set(False, False, True)               # 주행: 파랑
        elif state == car_core.STATE_PAUSE:
            self.set(True, True, False)                # 일시정지: 노랑
        elif state == car_core.STATE_STOPPED:
            self.set(True, False, False)               # 비상 정지: 빨강
        elif state == car_core.STATE_ERROR:
            self.set(blink, False, False)              # 오류(aborted): 빨강 깜빡
        else:
            self.set(False, True, False)               # 대기: 초록


class Buzzer(object):
    """능동 부저. 소리를 내는 동안만 HIGH로 두고 루프에서 끈다."""

    def __init__(self, cfg):
        self.pin = Pin(cfg.PIN_BUZZER, Pin.OUT)
        self.pin.value(0)
        self.until = None

    def beep(self, ms, now_ms):
        self.pin.value(1)
        self.until = car_core.ticks_add(now_ms, ms)

    def update(self, now_ms):
        if self.until is not None and car_core.ticks_diff(now_ms, self.until) >= 0:
            self.pin.value(0)
            self.until = None


class Button(object):
    """택트 스위치(풀업, 누르면 0). 디바운스는 루프를 막지 않는다."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.pin = Pin(cfg.PIN_BUTTON, Pin.IN, Pin.PULL_UP)
        self.raw = 1
        self.changed = 0
        self.reported = False

    def pressed(self, now_ms):
        """새로 눌린 순간에만 True."""
        v = self.pin.value()
        if v != self.raw:
            self.raw = v
            self.changed = now_ms
            return False
        if car_core.ticks_diff(now_ms, self.changed) < self.cfg.BUTTON_DEBOUNCE_MS:
            return False
        if self.raw == 0:
            if not self.reported:
                self.reported = True
                return True
            return False
        self.reported = False
        return False


# ── 초음파 ──────────────────────────────────────────────────────────
class Sonar(object):
    """SR-04. SONAR_ENABLED가 False면 항상 None(장애물 정지 없음)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.trig = None
        self.echo = None
        if cfg.SONAR_ENABLED:
            self.trig = Pin(cfg.PIN_SONAR_TRIG, Pin.OUT)
            self.echo = Pin(cfg.PIN_SONAR_ECHO, Pin.IN)
            self.trig.value(0)

    def read_cm(self):
        if self.trig is None:
            return None
        self.trig.value(1)
        sleep_us(10)
        self.trig.value(0)
        us = machine.time_pulse_us(self.echo, 1, self.cfg.SONAR_TIMEOUT_US)
        if us < 0:                     # 왕복 시간 초과 = 앞이 비었다
            return None
        return us / 58.0


# ── Wi-Fi·UDP ───────────────────────────────────────────────────────
class Wifi(object):
    """기다리지 않는 Wi-Fi. WIFI_RETRY_MS마다 연결을 '시작만' 한다."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.wlan = None
        self.last_try = None
        self.told = False
        try:
            self.wlan = network.WLAN(network.STA_IF)
            self.wlan.active(True)
        except Exception as e:         # 네트워크가 없는 보드에서도 돌아가게 둔다
            print("Wi-Fi 초기화 실패:", e)

    def ensure(self, now_ms):
        if self.wlan is None:
            return False
        try:
            if self.wlan.isconnected():
                return True
        except Exception:
            return False
        if not self.cfg.WIFI_SSID:
            return False               # SSID를 아직 안 채웠다. 업로드 전에 config를 고친다
        if (self.last_try is None or
                car_core.ticks_diff(now_ms, self.last_try) >= self.cfg.WIFI_RETRY_MS):
            self.last_try = now_ms
            try:
                self.wlan.connect(self.cfg.WIFI_SSID, self.cfg.WIFI_PASS)
            except Exception as e:
                print("Wi-Fi 연결 실패:", e)
            if not self.told:
                self.told = True
                print("Wi-Fi 연결 시도 중: 2.4GHz 핫스팟만 된다(5GHz는 안 붙는다)")
        return False


class Link(object):
    """UDP 한 데이터그램 = JSON 하나."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.sock = None
        self.up = False                  # Wi-Fi가 붙었을 때만 보낸다(안 붙으면 EHOSTUNREACH가 쏟아진다)
        if cfg.SERVER_IP:
            self.addr = (cfg.SERVER_IP, cfg.SERVER_PORT)
        else:
            self.addr = ("255.255.255.255", cfg.SERVER_PORT)
        self.open()

    def open(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("0.0.0.0", self.cfg.UDP_PORT))
            self.sock.setblocking(False)
        except OSError as e:
            self.sock = None
            print("UDP 소켓 열기 실패:", e)

    def send(self, obj):
        if self.sock is None or not self.up:
            return False
        data = car_core.encode(obj)
        try:
            self.sock.sendto(data, self.addr)
            return True
        except OSError as e:
            print("UDP 송신 실패:", e)
            return False

    def recv(self):
        """받은 (dict, 주소) 목록. 없으면 빈 목록."""
        out = []
        if self.sock is None:
            return out
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
            except OSError:            # 자료 없음(EAGAIN)도 여기로 온다
                break
            msg = car_core.parse(data)
            if msg is not None:
                out.append((msg, addr))
        return out


# ── 차 전체 ─────────────────────────────────────────────────────────
class CarDevice(object):
    def __init__(self, cfg=None):
        self.cfg = cfg or config
        self.core = car_core.CarCore(self.cfg)
        self.motors = Motors(self.cfg)
        self.servo = Servo(self.cfg)
        self.led = Led(self.cfg)
        self.buzzer = Buzzer(self.cfg)
        self.button = Button(self.cfg)
        self.sonar = Sonar(self.cfg)
        self.wifi = Wifi(self.cfg)
        self.link = Link(self.cfg)
        self.started = False
        self.online = False
        self.server_seen = False
        self.next_step_us = 0
        self.next_tel_ms = 0
        self.next_sonar_ms = 0
        self.next_hello_ms = 0
        self.servo.set(self.cfg.SERVO_CLOSED_DEG)

    # ── 부팅 ────────────────────────────────────────────────────────
    def summary(self):
        cfg = self.cfg
        print("ICE-ZERO 제설차 %s 시작 (기지 도킹 위치 %.0f,%.0f 북향)" %
              (cfg.CAR_ID, car_core.DOCK_X, car_core.DOCK_Y))
        print("바퀴 %.0fmm / 윤거 %.0fmm / 1회전 %d스텝 / 스텝 %dus" %
              (cfg.WHEEL_D_MM, cfg.TRACK_MM, cfg.STEPS_PER_REV, cfg.STEP_US))
        print("1mm = %.2f스텝, 1도 회전 = %.1f스텝" %
              (1.0 / car_core.MM_PER_STEP, 1.0 / car_core.DEG_PER_STEP))
        print("중심 %.0f,%.0f / 기지까지 %.0fmm / 후진 여유 %.0fmm" %
              (cfg.CENTER_X, cfg.CENTER_Y, cfg.BASE_DIST_MM, cfg.DOCK_OVERDRIVE_MM))
        print("갈래 거리 %s" % (cfg.ARM_OUT_MM,))
        print("살포 창 %s (S는 중심까지 남은 거리)" % (cfg.SPRAY_WIN,))
        print("서보 닫힘 %d도 / 열림 %d도" %
              (cfg.SERVO_CLOSED_DEG, cfg.SERVO_OPEN_DEG))
        print("서버 %s:%d → 차 %d, Wi-Fi %s" %
              (cfg.SERVER_IP or "브로드캐스트", cfg.SERVER_PORT, cfg.UDP_PORT,
               cfg.WIFI_SSID or "안 씀(오프라인)"))
        if not cfg.SONAR_ENABLED:
            print("초음파 없음: 장애물 정지도 없다")
        if not cfg.WIFI_SSID:
            print("WIFI_SSID가 비어 있다. 서버와 붙이려면 업로드 전에 config.py를 채운다.")

    # ── 한 바퀴 ────────────────────────────────────────────────────
    def tick(self):
        now_us = ticks_us()
        now_ms = ticks_ms()
        if not self.started:
            self.started = True
            self.core.start(now_ms)
            self.next_step_us = now_us
            self.next_tel_ms = now_ms
            self.next_sonar_ms = now_ms
            self.next_hello_ms = now_ms
        self.link.up = self.wifi.ensure(now_ms)
        self.online = self.link.up or not self.cfg.WIFI_SSID
        self.read_sonar(now_ms)
        self.poll_input(now_ms)
        self.core.tick(now_ms)
        self.pump_steps(now_us)
        self.send_hello(now_ms)
        self.send_tel(now_ms)
        self.flush(now_ms)
        self.led.show(self.core.state, self.online, now_ms)
        self.buzzer.update(now_ms)

    def read_sonar(self, now_ms):
        if not self.cfg.SONAR_ENABLED:
            return
        if car_core.ticks_diff(now_ms, self.next_sonar_ms) < 0:
            return
        self.next_sonar_ms = car_core.ticks_add(now_ms, self.cfg.SONAR_PERIOD_MS)
        self.core.sonar(self.sonar.read_cm(), now_ms)

    def poll_input(self, now_ms):
        for msg, addr in self.link.recv():
            self.link.addr = addr      # 서버 주소를 배운다(브로드캐스트로 시작했을 때)
            self.server_seen = True
            self.core.handle_packet(msg, now_ms)
        if self.button.pressed(now_ms):
            self.core.button(now_ms)

    def pump_steps(self, now_us):
        if self.core.state != car_core.STATE_RUN:
            if self.motors.energized:
                self.motors.off()
            self.servo.set(self.cfg.SERVO_CLOSED_DEG)
            # 놀거나 멈춘 동안 쌓인 시간은 물려받지 않는다
            self.next_step_us = now_us
            return
        if car_core.ticks_diff(now_us, self.next_step_us) < 0:
            return
        late = car_core.ticks_diff(now_us, self.next_step_us)
        act = self.core.step()
        if not act["step"]:
            return
        self.motors.step(act["left"], act["right"])
        self.servo.set(self.cfg.SERVO_OPEN_DEG if act["spray"] else self.cfg.SERVO_CLOSED_DEG)
        if late > self.cfg.STEP_US * 2:
            # 초음파·소켓 때문에 밀렸다. 몰아서 돌리지 않고 지금부터 다시 센다
            self.next_step_us = car_core.ticks_add(now_us, self.cfg.STEP_US)
        else:
            self.next_step_us = car_core.ticks_add(self.next_step_us, self.cfg.STEP_US)
        if self.core.state != car_core.STATE_RUN:      # 마지막 스텝이었다
            self.motors.off()
            self.servo.set(self.cfg.SERVO_CLOSED_DEG)

    def send_tel(self, now_ms):
        if car_core.ticks_diff(now_ms, self.next_tel_ms) < 0:
            return
        self.next_tel_ms = car_core.ticks_add(now_ms, self.cfg.TEL_MS)
        self.link.send(self.core.tel(now_ms))

    def send_hello(self, now_ms):
        if self.server_seen:
            return
        if car_core.ticks_diff(now_ms, self.next_hello_ms) < 0:
            return
        self.next_hello_ms = car_core.ticks_add(now_ms, self.cfg.HELLO_MS)
        self.link.send(car_core.make_hello(self.cfg))

    def flush(self, now_ms):
        for msg in self.core.drain():
            self.link.send(msg)
            name = msg.get("e")
            if name is not None:
                self.on_event(name, now_ms)

    def on_event(self, name, now_ms):
        if self.cfg.LOG_EVENTS:
            print("evt %s seq=%s arm=%s" % (name, self.core.seq, self.core.arm))
        if name == car_core.EV_PLAN_START or name == car_core.EV_ARM_START:
            self.buzzer.beep(self.cfg.BEEP_MS, now_ms)
        elif name == car_core.EV_PLAN_DONE:
            self.buzzer.beep(self.cfg.BEEP_MS * 2, now_ms)
        elif name == car_core.EV_STOPPED or name == car_core.EV_ABORTED:
            self.buzzer.beep(self.cfg.BEEP_MS * 3, now_ms)

    # ── 루프 ────────────────────────────────────────────────────────
    def run(self):
        self.summary()
        try:
            while True:
                self.tick()
                sleep_us(self.sleep_hint())
        except KeyboardInterrupt:
            self.motors.off()
            self.servo.set(self.cfg.SERVO_CLOSED_DEG)
            self.led.set(False, False, False)
            print("멈춤")

    def sleep_hint(self):
        """다음 스텝까지 남은 시간만큼만 잔다(최대 LOOP_MAX_US)."""
        if self.core.state != car_core.STATE_RUN:
            return self.cfg.LOOP_IDLE_US
        left = car_core.ticks_diff(self.next_step_us, ticks_us())
        if left <= 0:
            return 0
        if left > self.cfg.LOOP_MAX_US:
            return self.cfg.LOOP_MAX_US
        return left


def main():
    CarDevice().run()


if __name__ == "__main__":
    main()
