# ICE-ZERO 기지 Pico #1(Pico 2 W, USB 시리얼). 제설기지 관제실 안에 둔다.
#   갈래 DHT11 4개 + 젖음·조도 ADC + OLED 128×32 + 1602 LCD + 3색 LED·부저(로컬 경고)
#   + 네오픽셀 링(갈래 상태/경광등) + 도킹 스위치 + 보충 게이트 SG90 (계약 6·9절)
#
# 배선(계약 6절)
#   DHT11  N=GP2, E=GP3, S=GP4, W=GP5   (모듈 풀업, 3V3)
#   젖음 AO GP26(ADC0, W 길가) / 조도 AO GP27(ADC1, 선택)
#   OLED    SSD1306 128×32 I2C0: SDA GP0, SCL GP1, 0x3C
#   LCD     1602 PCF8574 I2C0, 0x27 (선택)
#   3색 LED R=GP10, G=GP11, B=GP12 / 능동 부저 GP13
#   도킹 스위치 GP14(풀업, 눌리면 0) / 보충 게이트 SG90 GP15 / 네오픽셀 링 DIN GP16
#
# 동작
#   - 2초마다 '@@TEL {json}' 한 줄을 print하고, 맥이 보내는 '@@SHOW'·'@@REFILL' 한 줄을 읽는다.
#   - USB 수신은 select.poll로 기다리지 않는다. 루프 주기는 LOOP_MS.
#   - 로컬 경고(3색 LED·부저)와 자동 보충은 맥과 무관하게 돈다. USB를 뽑아도 계속 동작한다.
#   - DHT11은 2초 이상 간격으로 한 갈래씩 돌아가며 읽는다. 실패해도 마지막 정상값을 10초까지 쓴다.
import select
import sys
import time

import dht
import machine

try:
    import neopixel
except ImportError:
    neopixel = None

import config
import lcd1602
import sensor_core
import ssd1306

# time.ticks_*는 MicroPython에만 있다. CPython 시험에서는 같은 의미로 대신한다.
if hasattr(time, "ticks_ms"):
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
    sleep_ms = time.sleep_ms
else:
    def ticks_ms():
        return int(time.time() * 1000) % 0x40000000

    def ticks_diff(a, b):
        return ((a - b + 0x20000000) % 0x40000000) - 0x20000000

    def sleep_ms(ms):
        time.sleep(ms / 1000.0)

bank = None                      # sensor_core.SensorBank
dhts = {}                        # 갈래 ID → dht.DHT11 또는 None
wet_adc = None                   # machine.ADC (GP26)
light_adc = None                 # machine.ADC (GP27) 또는 None
i2c = None                       # machine.I2C(0)
oled = None                      # ssd1306.SSD1306_I2C 또는 None
lcd = None                       # lcd1602.LCD1602 또는 None
lcd_shown = None                 # 마지막으로 LCD에 쓴 두 줄(중복 clear 방지)
leds = None                      # [R, G, B] machine.Pin 또는 None
buzzer = None                    # machine.Pin 또는 None
ring = None                      # neopixel.NeoPixel 또는 None
ring_shown = None                # 마지막으로 링에 쓴 색 목록(중복 write 방지)
wet_raw = None                   # 젖음 ADC raw(0~65535)
wet = False                      # 젖음 판정
light_raw = None                 # 조도 ADC raw 또는 None
warn_state = {"warn": False, "off": 0}
warn_prev = False                # 직전 주기의 경고 상태(부저 상승 에지용)
beep_until = None                # 부저를 끌 시각. None이면 울리지 않는다
dock_pin = None                  # machine.Pin (GP14, 풀업)
dock_db = None                   # sensor_core.Debouncer
refill = None                    # sensor_core.RefillController
gate = None                      # machine.PWM (GP15)
docked = False                   # 디바운스된 도킹 상태
show_state = {"arms": None, "msg": "", "beacon": False, "ms": None}   # 맥이 준 표시 상태
last_tel_ms = None
last_oled_ms = None
last_lcd_ms = None
boot_ms = 0
usb_poll = None
usb_buf = ""


def setup():
    """하드웨어 초기화. 부팅 때 한 번만 부른다."""
    global bank, dhts, wet_adc, light_adc, i2c, oled, lcd, leds, buzzer, ring
    global dock_pin, dock_db, refill, gate, usb_poll, usb_buf, boot_ms
    boot_ms = ticks_ms()
    bank = sensor_core.SensorBank(config.ARM_ORDER, config.DHT_INTERVAL_MS, config.DHT_HOLD_MS)

    for i in range(len(config.ARM_ORDER)):
        arm = config.ARM_ORDER[i]
        pin_no = config.DHT_PINS[i]
        try:
            dhts[arm] = dht.DHT11(machine.Pin(pin_no))
        except Exception as e:
            dhts[arm] = None
            print("DHT11 %s(GP%d) 초기화 실패: %s" % (arm, pin_no, e))
    print("DHT11 %d개 준비" % len(dhts))

    wet_adc = machine.ADC(machine.Pin(config.PIN_WET))
    if config.LIGHT_ENABLE:
        light_adc = machine.ADC(machine.Pin(config.PIN_LIGHT))
    else:
        light_adc = None

    try:
        i2c = machine.I2C(config.I2C_ID, sda=machine.Pin(config.PIN_SDA),
                          scl=machine.Pin(config.PIN_SCL), freq=config.I2C_FREQ)
    except Exception as e:
        i2c = None
        print("I2C 초기화 실패(화면 없이 계속):", e)
    if i2c is not None:
        try:
            oled = ssd1306.SSD1306_I2C(config.OLED_W, config.OLED_H, i2c, config.OLED_ADDR)
        except Exception as e:
            oled = None
            print("OLED 초기화 실패(화면 없이 계속):", e)
        if config.LCD:
            try:
                lcd = lcd1602.LCD1602(i2c, config.LCD_ADDR, config.LCD_COLS, config.LCD_ROWS)
            except Exception as e:
                lcd = None
                print("LCD 초기화 실패(화면 없이 계속):", e)
        else:
            lcd = None

    leds = [machine.Pin(config.PIN_LED_R, machine.Pin.OUT),
            machine.Pin(config.PIN_LED_G, machine.Pin.OUT),
            machine.Pin(config.PIN_LED_B, machine.Pin.OUT)]
    set_leds(False)

    if config.BUZZER:
        buzzer = machine.Pin(config.PIN_BUZZER, machine.Pin.OUT)
        buzzer.value(0)
    else:
        buzzer = None

    # 도킹 스위치(풀업)와 보충 게이트 서보. 게이트는 닫힌 각도로 시작한다.
    dock_pin = machine.Pin(config.PIN_DOCK, machine.Pin.IN, machine.Pin.PULL_UP)
    dock_db = sensor_core.Debouncer(config.DOCK_DEBOUNCE_MS)
    refill = sensor_core.RefillController(config.REFILL_AUTO, config.REFILL_MS,
                                          config.DOCK_SETTLE_MS, config.REFILL_COOLDOWN_MS)
    gate = machine.PWM(machine.Pin(config.PIN_GATE))
    gate.freq(config.GATE_FREQ)
    close_gate()

    if config.RING:
        if neopixel is None:
            print("neopixel 모듈이 없어 링을 켜지 않습니다")
            ring = None
        else:
            ring = neopixel.NeoPixel(machine.Pin(config.PIN_RING), config.RING_PIXELS)
            for i in range(config.RING_PIXELS):
                ring[i] = (0, 0, 0)
            ring.write()
    else:
        ring = None

    try:
        usb_poll = select.poll()
        usb_poll.register(sys.stdin, select.POLLIN)
        usb_buf = ""
    except Exception as e:
        usb_poll = None
        print("stdin 폴링을 쓸 수 없어 USB 수신을 끕니다:", e)


def uptime_s(now):
    up = ticks_diff(now, boot_ms) // 1000
    return 0 if up < 0 else up


# ---------------------------------------------------------------- 센서 읽기
def read_dht(arm, now):
    """갈래 하나를 읽어 SensorBank에 알린다. 실패는 ok=false로만 남기고 값은 유지한다."""
    sensor = dhts.get(arm)
    before = bool(bank.ok.get(arm))
    if sensor is None:
        bank.apply(arm, None, None, now)
    else:
        try:
            sensor.measure()
            t = sensor.temperature()
            rh = sensor.humidity()
        except Exception:
            t = None
            rh = None
        bank.apply(arm, t, rh, now)
    after = bool(bank.ok.get(arm))
    if before and not after:
        print("DHT11 %s 읽기 실패(마지막 값 유지)" % arm)
    elif not before and after:
        print("DHT11 %s 읽기 정상" % arm)


def read_wet_raw():
    """젖음센서 4회 평균(0~65535). 센서가 없거나 실패하면 None."""
    if wet_adc is None:
        return None
    total = 0
    for _ in range(4):
        try:
            total += wet_adc.read_u16()
        except Exception:
            return None
    return total // 4


def read_light_raw():
    """조도 raw(0~65535). 조도 센서를 쓰지 않으면 None."""
    if light_adc is None:
        return None
    try:
        return light_adc.read_u16()
    except Exception:
        return None


def read_dock():
    """도킹 스위치 raw. 풀업이라 눌리면 0 → True(도킹)로 뒤집는다."""
    if dock_pin is None:
        return False
    return dock_pin.value() == 0


# ---------------------------------------------------------------- 출력
def set_leds(on):
    """3색 LED: 경고면 빨강, 평상이면 초록."""
    if leds is None:
        return
    high = 1 if config.LED_ACTIVE_HIGH else 0
    low = 1 - high
    leds[0].value(high if on else low)
    leds[1].value(low if on else high)
    leds[2].value(low)


def set_buzzer(on):
    if buzzer is not None:
        buzzer.value(1 if on else 0)


def open_gate():
    """보충 게이트를 연다(SG90 열림 각도)."""
    if gate is not None:
        gate.duty_u16(sensor_core.servo_duty(config.GATE_OPEN_DEG,
                                             config.GATE_DUTY_MIN, config.GATE_DUTY_MAX))


def close_gate():
    """보충 게이트를 닫는다(SG90 닫힘 각도)."""
    if gate is not None:
        gate.duty_u16(sensor_core.servo_duty(config.GATE_CLOSED_DEG,
                                             config.GATE_DUTY_MIN, config.GATE_DUTY_MAX))


def show_ring(now):
    """맥이 준 갈래 상태(또는 경광등)를 링에 쓴다. 색이 그대로면 쓰지 않는다(10초 끊기면 끔)."""
    global ring_shown
    if ring is None:
        return
    stale = sensor_core.is_stale(show_state["ms"], now, config.SHOW_STALE_MS)
    view = sensor_core.show_view(show_state["arms"], show_state["ms"], now, config.SHOW_STALE_MS)
    beacon = bool(show_state["beacon"]) and not stale
    px = sensor_core.ring_pixels(view, config.RING_PIXELS, now, config.RING_BRIGHT,
                                 config.RING_PER_ARM, beacon)
    if px == ring_shown:
        return
    ring_shown = px
    for i in range(config.RING_PIXELS):
        ring[i] = px[i]
    ring.write()


def _show_msg(now):
    """지금 표시할 맥 메시지. 오래됐으면 빈 문자열."""
    if sensor_core.is_stale(show_state["ms"], now, config.SHOW_STALE_MS):
        return ""
    return show_state["msg"]


def draw_oled(now, t, ok):
    """갈래 온도·경고·맥 메시지를 OLED에 쓴다(OLED_MS 주기)."""
    global last_oled_ms
    if oled is None:
        return
    if last_oled_ms is not None and ticks_diff(now, last_oled_ms) < config.OLED_MS:
        return
    last_oled_ms = now
    lines = sensor_core.oled_lines(t, ok, wet, warn_state["warn"], _show_msg(now), uptime_s(now))
    oled.fill(0)
    for i in range(len(lines)):
        oled.text(lines[i], 0, i * 8)
    oled.show()


def draw_lcd(now, t):
    """1602 LCD 두 줄: 1줄 맥 메시지, 2줄 갈래 온도. 내용이 같으면 다시 쓰지 않는다(깜박임 방지)."""
    global last_lcd_ms, lcd_shown
    if lcd is None:
        return
    if last_lcd_ms is not None and ticks_diff(now, last_lcd_ms) < config.OLED_MS:
        return
    last_lcd_ms = now
    lines = sensor_core.lcd_lines(_show_msg(now), t)
    key = (lines[0], lines[1])
    if key == lcd_shown:
        return
    lcd_shown = key
    lcd.show(lines[0], lines[1])


# ---------------------------------------------------------------- USB 수신
def apply_show(data, now):
    """이미 검증된 '@@SHOW' 내용을 반영한다(링·OLED·LCD 메시지 갱신)."""
    show_state["arms"] = data["arms"]
    show_state["msg"] = data["msg"]
    show_state["beacon"] = data["beacon"]
    show_state["ms"] = now


def handle_line(line, now):
    """USB 한 줄을 해석해 반영한다. 모르는 줄·형식이 틀린 줄은 조용히 버린다."""
    parsed = sensor_core.parse_line(line)
    if parsed is None:
        return
    kind = parsed[0]
    if kind == "show":
        apply_show(parsed[1], now)
    elif kind == "refill":
        res = refill.request(parsed[1]["ms"], now)
        if res["ok"]:
            open_gate()
            print("수동 보충 %dms" % res["ms"])
        else:
            print("@@REFILL 무시(%s)" % res["reason"])


def receive_usb(now):
    """기다리지 않고 지금 도착한 글자만 읽어 완성된 줄을 처리한다."""
    global usb_buf
    if usb_poll is None:
        return
    try:
        ready = usb_poll.poll(0)
    except Exception:
        return
    while ready:
        try:
            ch = sys.stdin.read(1)
        except Exception:
            return
        if not ch:
            break                  # 더 읽을 것이 없다(시험용 stdin의 끝)
        if ch != "\n":
            if len(usb_buf) < config.CMD_MAX_LEN:
                usb_buf = usb_buf + ch
            else:
                usb_buf = ""       # 너무 긴 줄은 버린다(깨진 줄이 계속 쌓이지 않게)
        else:
            line, usb_buf = usb_buf.strip(), ""
            if line:
                handle_line(line, now)
        try:
            ready = usb_poll.poll(0)
        except Exception:
            return


# ---------------------------------------------------------------- 메인 루프
def tick_dock(now):
    """도킹 상태를 갱신하고, 자동 보충이 시작되면 게이트를 연다."""
    global docked
    was = docked
    docked = dock_db.update(read_dock(), now)
    if docked and not was:
        print("도킹 감지")
    elif was and not docked:
        print("도킹 해제")
    ms = refill.update(docked, now)
    if ms is not None:
        open_gate()
        print("자동 보충 %dms" % ms)


def loop_once(now):
    """한 주기: DHT 하나 → 젖음·조도 → 로컬 경고 → 도킹·보충 → USB → 링·OLED·LCD → 텔레메트리."""
    global wet_raw, wet, light_raw, warn_state, warn_prev, beep_until, last_tel_ms
    arm = bank.due(now)
    if arm is not None:
        read_dht(arm, now)

    wet_raw = read_wet_raw()
    wet = sensor_core.is_wet(wet_raw, config.WET_THRESHOLD, config.WET_WHEN_LOW)
    light_raw = read_light_raw()

    t, rh, ok = bank.measured(now)
    cond = sensor_core.warn_condition(t, rh, wet, config.WARN_T, config.WARN_RH)
    warn_state = sensor_core.local_warn(cond, warn_state, config.WARN_OFF_COUNT)
    if warn_state["warn"] and not warn_prev:
        set_buzzer(1)
        beep_until = now + config.BEEP_MS     # 시간을 보고 루프에서 끈다(막히지 않는다)
    warn_prev = warn_state["warn"]
    set_leds(warn_state["warn"])              # 맥과 무관하게 즉시 반영

    tick_dock(now)                            # 도킹 디바운스 + 자동 보충
    receive_usb(now)                          # @@SHOW·@@REFILL(수동 보충)
    if refill.tick(now):                      # 열린 시간이 끝났으면 게이트를 닫는다
        close_gate()

    if beep_until is not None and ticks_diff(now, beep_until) >= 0:
        set_buzzer(0)
        beep_until = None

    show_ring(now)
    draw_oled(now, t, ok)
    draw_lcd(now, t)

    due = last_tel_ms is None or ticks_diff(now, last_tel_ms) >= config.TELEMETRY_MS
    if due:
        tel = sensor_core.telemetry(t, rh, ok, wet_raw, wet, light_raw, warn_state["warn"],
                                    docked, refill.count, refill.refilling(), uptime_s(now))
        print(sensor_core.tel_line(tel))
        last_tel_ms = now


def run(max_loops=None):
    """메인 루프. max_loops는 시험용 반복 제한(None이면 끝없이)."""
    n = 0
    while max_loops is None or n < max_loops:
        n += 1
        loop_once(ticks_ms())
        sleep_ms(config.LOOP_MS)


def main():
    setup()
    run()


if __name__ == "__main__":
    main()
