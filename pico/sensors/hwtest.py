# 기지 Pico #1 하드웨어 점검. 부품을 하나씩 붙여 가며 이 순서로 확인한다.
# (DHT11 4 → 젖음·조도 → OLED → 3색 LED·부저 → 링 → 1602 LCD → 도킹 스위치·보충 게이트)
#   마이크로파이썬 REPL에서:  import hwtest  →  hwtest.main()
#   (업로드 뒤에는 파일을 main.py로 바꾸지 말고 파일명 hwtest.py 그대로 두고 부른다.)
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

DHT_ROUNDS = 5                   # 갈래마다 출력하는 횟수
DHT_GAP_MS = 2100                # DHT11 최소 간격(2초) + 여유


def sleep_ms(ms):
    time.sleep_ms(ms)


def make_dhts():
    """갈래 순서대로 dht.DHT11 객체를 만든다. 실패한 갈래는 None."""
    got = []
    for i in range(len(config.ARM_ORDER)):
        try:
            got.append(dht.DHT11(machine.Pin(config.DHT_PINS[i])))
        except Exception as e:
            print("DHT11 %s(GP%d) 초기화 실패: %s" % (config.ARM_ORDER[i], config.DHT_PINS[i], e))
            got.append(None)
    return got


def test_dht(dhts):
    """DHT11 4개를 5회씩 읽어 온도/습도를 표로 출력한다."""
    print("")
    print("== DHT11 갈래 온습도 (%d회, %.1f초 간격) ==" % (DHT_ROUNDS, DHT_GAP_MS / 1000.0))
    for r in range(DHT_ROUNDS):
        row = "회 %d:" % (r + 1)
        for i in range(len(config.ARM_ORDER)):
            arm = config.ARM_ORDER[i]
            sensor = dhts[i]
            if sensor is None:
                row = row + "  %s=없음" % arm
                continue
            try:
                sensor.measure()
                t = sensor.temperature()
                rh = sensor.humidity()
            except Exception as e:
                row = row + "  %s=실패(%s)" % (arm, e)
                continue
            if sensor_core.dht_valid(t, rh):
                row = row + "  %s=%.1fC/%d%%" % (arm, t, rh)
            else:
                row = row + "  %s=범위밖(%.1f/%d)" % (arm, t, rh)
        print(row)
        if r + 1 < DHT_ROUNDS:
            sleep_ms(DHT_GAP_MS)


def test_adc():
    """수위감지(젖음)·조도 raw를 5회 출력한다. config.WET_THRESHOLD를 정할 때 쓴다."""
    wet_adc = machine.ADC(machine.Pin(config.PIN_WET))
    light_adc = None
    if config.LIGHT_ENABLE:
        light_adc = machine.ADC(machine.Pin(config.PIN_LIGHT))
    print("")
    print("== ADC raw (0~65535) ==")
    for r in range(5):
        wet_raw = wet_adc.read_u16()
        wet = sensor_core.is_wet(wet_raw, config.WET_THRESHOLD, config.WET_WHEN_LOW)
        if light_adc is None:
            light_s = "없음"
        else:
            light_s = str(light_adc.read_u16())
        print("회 %d: wet_raw=%d (%s)  light_raw=%s" % (r + 1, wet_raw, "젖음" if wet else "마름", light_s))
        sleep_ms(500)
    print("판정: raw %s %d이면 젖음 (WET_WHEN_LOW=%s)"
          % ("<=" if config.WET_WHEN_LOW else ">=", config.WET_THRESHOLD, config.WET_WHEN_LOW))


def test_oled():
    """OLED에 4줄을 쓴다. 줄이 겹치거나 잘리면 배선(SDA GP0·SCL GP1)·주소(0x3C)를 본다."""
    print("")
    print("== OLED 128x32 ==")
    i2c = machine.I2C(config.I2C_ID, sda=machine.Pin(config.PIN_SDA),
                      scl=machine.Pin(config.PIN_SCL), freq=config.I2C_FREQ)
    found = i2c.scan()
    print("I2C 주소:", found)
    if config.OLED_ADDR not in found:
        print("0x%02X가 없습니다. SDA/SCL을 바꿔 보거나 전원을 확인하세요." % config.OLED_ADDR)
        return
    oled = ssd1306.SSD1306_I2C(config.OLED_W, config.OLED_H, i2c, config.OLED_ADDR)
    lines = ["ICE-ZERO SENSOR", "N 25.0  E 25.0", "S 25.0  W 25.0", "ok DRY 0s"]
    oled.fill(0)
    for i in range(len(lines)):
        oled.text(lines[i], 0, i * 8)
    oled.show()
    print("OLED에 4줄을 썼습니다:", lines)
    sleep_ms(1500)


def test_led_buzzer():
    """3색 LED를 R·G·B·끔 순서로, 부저를 두 번 울린다."""
    print("")
    print("== 3색 LED·부저 ==")
    pins = [machine.Pin(config.PIN_LED_R, machine.Pin.OUT),
            machine.Pin(config.PIN_LED_G, machine.Pin.OUT),
            machine.Pin(config.PIN_LED_B, machine.Pin.OUT)]
    buzzer = None
    if config.BUZZER:
        buzzer = machine.Pin(config.PIN_BUZZER, machine.Pin.OUT)
        buzzer.value(0)
    names = ("빨강", "초록", "파랑")
    for i in range(3):
        for j in range(3):
            pins[j].value(1 if i == j else 0)
        print("LED", names[i])
        sleep_ms(500)
    for j in range(3):
        pins[j].value(0)
    if buzzer is not None:
        for _ in range(2):
            buzzer.value(1)
            sleep_ms(150)
            buzzer.value(0)
            sleep_ms(250)
        print("부저 두 번 울림")
    else:
        print("부저 없음(config.BUZZER=False)")


def test_ring():
    """링 색을 갈래 상태 순서로 하나씩 켠다: risk1 → risk2 → risk3 → plan → done."""
    print("")
    print("== 네오픽셀 링 ==")
    if not config.RING:
        print("링 없음(config.RING=False)")
        return
    if neopixel is None:
        print("neopixel 모듈이 없습니다")
        return
    ring = neopixel.NeoPixel(machine.Pin(config.PIN_RING), config.RING_PIXELS)
    modes = ["risk1", "risk2", "risk3", "plan", "done", "off"]
    for mode in modes:
        arm_modes = {}
        for arm in config.ARM_ORDER:
            arm_modes[arm] = mode
        px = sensor_core.ring_pixels(arm_modes, config.RING_PIXELS, 0,
                                     config.RING_BRIGHT, config.RING_PER_ARM)
        for i in range(config.RING_PIXELS):
            ring[i] = px[i]
        ring.write()
        print("링", mode, "→", px[0])
        sleep_ms(600)
    for i in range(config.RING_PIXELS):
        ring[i] = (0, 0, 0)
    ring.write()


def test_lcd():
    """1602 LCD 두 줄. 안 보이면 주소(0x27/0x3F)와 백팩 가변저항(명암)을 본다."""
    print("")
    print("== 1602 LCD ==")
    if not config.LCD:
        print("LCD 없음(config.LCD=False)")
        return
    i2c = machine.I2C(config.I2C_ID, sda=machine.Pin(config.PIN_SDA),
                      scl=machine.Pin(config.PIN_SCL), freq=config.I2C_FREQ)
    found = i2c.scan()
    print("I2C 주소:", found)
    if config.LCD_ADDR not in found:
        print("0x%02X가 없습니다. 0x3F인 모듈도 있으니 확인하세요." % config.LCD_ADDR)
        return
    lcd = lcd1602.LCD1602(i2c, config.LCD_ADDR, config.LCD_COLS, config.LCD_ROWS)
    lcd.show("ICE-ZERO BASE", "N12 E11 S12 W10")
    print("LCD에 두 줄을 썼습니다: ICE-ZERO BASE / N12 E11 S12 W10")
    sleep_ms(1500)


def test_dock_gate():
    """도킹 스위치 raw를 읽고, 보충 게이트 SG90을 열었다 닫는다."""
    print("")
    print("== 도킹 스위치·보충 게이트 ==")
    dock = machine.Pin(config.PIN_DOCK, machine.Pin.IN, machine.Pin.PULL_UP)
    print("도킹 스위치 GP%d = %d (0=눌림, 1=안 눌림). 손으로 눌러 보세요." % (config.PIN_DOCK, dock.value()))
    for _ in range(5):
        sleep_ms(200)
        print("  raw", dock.value())
    pwm = machine.PWM(machine.Pin(config.PIN_GATE))
    pwm.freq(config.GATE_FREQ)
    closed = sensor_core.servo_duty(config.GATE_CLOSED_DEG, config.GATE_DUTY_MIN, config.GATE_DUTY_MAX)
    opened = sensor_core.servo_duty(config.GATE_OPEN_DEG, config.GATE_DUTY_MIN, config.GATE_DUTY_MAX)
    pwm.duty_u16(closed)
    print("게이트 닫힘(%d도)" % config.GATE_CLOSED_DEG)
    sleep_ms(600)
    pwm.duty_u16(opened)
    print("게이트 열림(%d도) — 사일로 출구를 확인하세요" % config.GATE_OPEN_DEG)
    sleep_ms(1200)
    pwm.duty_u16(closed)
    print("게이트 닫힘")


def main():
    print("ICE-ZERO 기지 Pico 하드웨어 점검")
    print("갈래 순서:", config.ARM_ORDER, " DHT11 핀:", config.DHT_PINS)
    dhts = make_dhts()
    test_dht(dhts)
    test_adc()
    test_oled()
    test_led_buzzer()
    test_ring()
    test_lcd()
    test_dock_gate()
    print("")
    print("점검 끝. 모두 정상이면 main.py를 실행하세요.")
