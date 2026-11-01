# ICE-ZERO 사거리 모형(Pico #1) 하드웨어 점검 스크립트.
#   배선을 마친 뒤 REPL에서 이 파일을 실행하면 갈래 LED·서보 4개·센서를 차례로 시험한다.
#   (main.py와 달리 여기서는 일부러 기다린다. 사람이 눈으로 확인하는 시험이라서.)
#
# 실행: import hwtest   또는   mpremote run hwtest.py
import time

import ds18x20
import machine
import onewire

try:
    import neopixel
except ImportError:
    neopixel = None

import config
import cross_core

LED_TEST_MODES = ("risk1", "risk2", "risk3", "plan", "done", "off")   # 갈래 LED 색 순환


def sleep_ms(ms):
    time.sleep_ms(ms)


def make_servos():
    """서보 4개를 50Hz로 열고 닫힌 각도로 둔다."""
    servos = {}
    for i in range(len(cross_core.ARMS)):
        pwm = machine.PWM(machine.Pin(config.SERVO_PINS[i]))
        pwm.freq(config.SERVO_FREQ)
        pwm.duty_u16(cross_core.servo_duty(config.SERVO_CLOSED_DEG))
        servos[cross_core.ARMS[i]] = pwm
    return servos


def make_arm_led():
    """갈래 LED(neopixel 4픽셀 또는 gpio 4개)를 만든다."""
    if config.LED_MODE == "neopixel":
        if neopixel is None:
            print("neopixel 모듈이 없습니다: gpio 모드로 두고 다시 실행하세요")
            return None
        return neopixel.NeoPixel(machine.Pin(config.PIN_NEOPIXEL), len(cross_core.ARMS))
    leds = []
    for p in config.PIN_ARM_LEDS:
        leds.append(machine.Pin(p, machine.Pin.OUT))
    return leds


def write_led(arm_led, mode, now_ms):
    """갈래 LED 4개를 모두 같은 모드로 켠다."""
    if arm_led is None:
        return
    bright = 255 if config.LED_MODE != "neopixel" else config.LED_BRIGHT
    if config.LED_MODE == "neopixel":
        for i in range(len(cross_core.ARMS)):
            arm_led[i] = cross_core.led_rgb(mode, now_ms, bright)
        arm_led.write()
    else:
        rgb = cross_core.led_rgb(mode, now_ms, bright)
        on = 1 if max(rgb) > 0 else 0
        for i in range(len(cross_core.ARMS)):
            arm_led[i].value(on)


def test_leds(arm_led):
    """1) 갈래 LED 색 순환. 각 색을 0.6초씩(plan은 깜박임을 보려고 2초)."""
    print("== 갈래 LED 시험: %s ==" % ", ".join(LED_TEST_MODES))
    for mode in LED_TEST_MODES:
        print("  LED", mode)
        if mode == "plan":
            # 2Hz 깜박임을 눈으로 확인한다
            for _ in range(4):
                write_led(arm_led, "plan", time.ticks_ms())
                sleep_ms(250)
        else:
            write_led(arm_led, mode, 0)
            sleep_ms(600)
    write_led(arm_led, "off", 0)


def test_servos(servos):
    """2) 서보 4개를 N→E→S→W 순서로 하나씩 열고 닫는다. 한 번에 하나만 움직인다."""
    print("== 서보 시험: N, E, S, W 차례로 열기·닫기 ==")
    for arm in cross_core.ARMS:
        print("  살포기", arm, "열기", config.SERVO_OPEN_DEG, "도")
        servos[arm].duty_u16(cross_core.servo_duty(config.SERVO_OPEN_DEG))
        sleep_ms(800)
        print("  살포기", arm, "닫기", config.SERVO_CLOSED_DEG, "도")
        servos[arm].duty_u16(cross_core.servo_duty(config.SERVO_CLOSED_DEG))
        sleep_ms(300)


def read_sensors(ds, roms, wet_adc, index):
    """한 번 읽기: (t_bridge, t_air, wet_raw, wet). 85.0은 측정 실패로 본다."""
    t_bridge = None
    t_air = None
    if roms:
        ds.convert_temp()
        sleep_ms(config.DS_CONV_MS)
        bridge_rom, air_rom = cross_core.pick_roms(roms, index)
        vals = {}
        for rom in roms:
            try:
                vals[rom] = ds.read_temp(rom)
            except Exception:
                vals[rom] = None
        t_bridge = vals.get(bridge_rom)
        t_air = vals.get(air_rom)
        if t_bridge is not None and -0.01 < t_bridge - config.TEMP_BAD < 0.01:
            t_bridge = None
        if t_air is not None and -0.01 < t_air - config.TEMP_BAD < 0.01:
            t_air = None
    wet_raw = None
    if wet_adc is not None:
        total = 0
        for _ in range(4):
            total += wet_adc.read_u16()
        wet_raw = total // 4
    wet = cross_core.is_wet(wet_raw, config.WET_THRESHOLD, config.WET_WHEN_LOW)
    return (t_bridge, t_air, wet_raw, wet)


def test_sensors():
    """3) DS18B20 2개와 젖음센서를 5회 출력한다. 85.0이 보이면 배선·풀업을 확인한다."""
    print("== 센서 시험: 5회 ==")
    ds = ds18x20.DS18X20(onewire.OneWire(machine.Pin(config.PIN_DS)))
    roms = sorted(ds.scan())
    print("DS18B20 센서 %d개" % len(roms))
    for i in range(len(roms)):
        print("  [%d] %s" % (i, cross_core.rom_hex(roms[i])))
    bridge_rom, air_rom = cross_core.pick_roms(roms, config.PIECE_INDEX)
    print("시험편(PIECE_INDEX=%d) = %s" % (config.PIECE_INDEX, cross_core.rom_hex(bridge_rom)))
    print("공기 = %s" % cross_core.rom_hex(air_rom))
    wet_adc = machine.ADC(machine.Pin(config.PIN_WET))
    for i in range(5):
        t_bridge, t_air, wet_raw, wet = read_sensors(ds, roms, wet_adc, config.PIECE_INDEX)
        print("  [%d] 시험편=%s 공기=%s wet_raw=%s wet=%s" % (i + 1, t_bridge, t_air, wet_raw, wet))
        sleep_ms(400)


def main():
    print("ICE-ZERO 사거리 보드 하드웨어 점검")
    print("LED_MODE=%s PIECE_INDEX=%d WET_THRESHOLD=%d WET_WHEN_LOW=%s"
          % (config.LED_MODE, config.PIECE_INDEX, config.WET_THRESHOLD, config.WET_WHEN_LOW))
    warn_led = machine.Pin(config.PIN_WARN_LED, machine.Pin.OUT)
    for _ in range(2):          # 주의 LED가 살아 있는지 먼저 본다
        warn_led.value(1)
        sleep_ms(200)
        warn_led.value(0)
        sleep_ms(200)
    arm_led = make_arm_led()
    test_leds(arm_led)
    servos = make_servos()
    test_servos(servos)
    test_sensors()
    print("점검 끝. 서보는 모두 닫힌 상태로 두었습니다.")


main()
