# ICE-ZERO 사거리 모형(Pico #1, Pico 2 W / MicroPython)
#   갈래 LED 4개 표시 + 서보 살포기 4개 순차 작동 + 교량 시험편 온도·젖음 관측 + 교량 주의 LED(로컬 규칙).
#
# 배선(계약 5절)
#   서보 살포기 SG90 ×4  N=GP18, E=GP19, S=GP20, W=GP21 (신호선만. 전원은 별도 5V, GND 공통)
#   갈래 LED             neopixel: WS2812 4픽셀 DIN=GP16(N,E,S,W) / gpio: GP6, GP7, GP8, GP9
#   DS18B20 ×2           데이터=GP4, 4.7kΩ 풀업 → 3V3 (교량 시험편·공기)
#   젖음센서 AO          GP26(ADC0)
#   교량 주의 LED        GP15(220Ω)
#   부저(선택)           GP17
#
# 동작
#   - 로컬 경고는 맥과 무관하게 항상 돈다(USB를 뽑아도 주의 LED는 계속 동작).
#   - 1초마다 '@@TEL {json}' 한 줄을 print하고, 맥이 쓰는 '@@LED'·'@@SPRAY'·'@@STOP' 줄을 읽는다.
#   - 살포는 한 번에 하나. 열린 시간은 time.ticks_ms()로 재므로 루프가 멈추지 않는다.
#   - 살포 상태가 바뀔 때마다 '@@EVT {json}' 한 줄을 보낸다(spray_start/spray_done/stopped/spray_reject).
import select
import sys
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

servos = {}               # 갈래 ID → machine.PWM
arm_led = None            # neopixel.NeoPixel 또는 Pin 4개 목록
ds = None                 # ds18x20.DS18X20
roms = []                 # 정렬된 ROM 목록(bytes)
bridge_rom = None         # 교량 시험편 센서 ROM
air_rom = None            # 공기 센서 ROM
temps = {}                # ROM → 마지막 온도(섭씨) 또는 None
conv_ms = None            # 변환을 시작한 시각(None이면 변환 중이 아님)
wet_adc = None            # machine.ADC
warn_led = None           # machine.Pin
buzzer = None             # machine.Pin 또는 None
beep_until = None         # 부저를 끌 시각(ticks). None이면 울리지 않는다
warn_state = {"warn": False, "off": 0}
arms_modes = {}           # 맥이 준 4갈래 모드
last_led_ms = None        # 마지막 LED 명령 시각
shown = None              # 마지막으로 실제 출력한 색(중복 write 방지)
last_tel_ms = None
boot_ms = 0
usb_poll = None
usb_buf = ""
queue = None              # cross_core.SprayQueue


def setup():
    """하드웨어 초기화. 부팅 때 한 번만 부른다."""
    global arm_led, ds, roms, bridge_rom, air_rom, wet_adc, warn_led, buzzer
    global usb_poll, usb_buf, boot_ms, queue
    boot_ms = ticks_ms()
    queue = cross_core.SprayQueue(config.QUEUE_MAX, config.DONE_KEEP)

    # 서보는 모두 닫힌 각도로 시작한다(전원 인가 직후 오작동 방지)
    for i in range(len(cross_core.ARMS)):
        arm = cross_core.ARMS[i]
        pwm = machine.PWM(machine.Pin(config.SERVO_PINS[i]))
        pwm.freq(config.SERVO_FREQ)
        pwm.duty_u16(cross_core.servo_duty(config.SERVO_CLOSED_DEG))
        servos[arm] = pwm

    warn_led = machine.Pin(config.PIN_WARN_LED, machine.Pin.OUT)
    warn_led.value(0)
    if config.BUZZER:
        buzzer = machine.Pin(config.PIN_BUZZER, machine.Pin.OUT)
        buzzer.value(0)

    ds = ds18x20.DS18X20(onewire.OneWire(machine.Pin(config.PIN_DS)))
    roms = sorted(ds.scan())
    print("DS18B20 센서 %d개" % len(roms))
    for i in range(len(roms)):
        print("  [%d] %s" % (i, cross_core.rom_hex(roms[i])))
    bridge_rom, air_rom = cross_core.pick_roms(roms, config.PIECE_INDEX)
    if len(roms) == 0:
        print("DS18B20이 없습니다: 온도는 null로 보냅니다")
    else:
        # 시험편이 몇 번째 센서인지는 배선 순서에 달렸다. 이 두 줄을 보고 config.PIECE_INDEX를 고친다.
        print("시험편(config.PIECE_INDEX=%d) = %s" % (config.PIECE_INDEX, cross_core.rom_hex(bridge_rom)))
        print("공기 = %s" % cross_core.rom_hex(air_rom))
        for rom in roms:
            temps[rom] = None

    wet_adc = machine.ADC(machine.Pin(config.PIN_WET))

    if config.LED_MODE == "neopixel":
        if neopixel is None:
            print("neopixel 모듈이 없어 갈래 LED를 켜지 않습니다")
            arm_led = None
        else:
            arm_led = neopixel.NeoPixel(machine.Pin(config.PIN_NEOPIXEL), len(cross_core.ARMS))
    else:
        arm_led = []
        for p in config.PIN_ARM_LEDS:
            arm_led.append(machine.Pin(p, machine.Pin.OUT))

    try:
        usb_poll = select.poll()
        usb_poll.register(sys.stdin, select.POLLIN)
        usb_buf = ""
    except Exception as e:
        usb_poll = None
        print("stdin 폴링을 쓸 수 없어 USB 수신을 끕니다:", e)


def ds_tick(now):
    """비차단 온도 읽기: 변환을 걸고 DS_CONV_MS 뒤에 읽는다. 그 사이 루프는 계속 돈다."""
    global conv_ms
    if ds is None or not roms:
        return
    if conv_ms is None:
        try:
            ds.convert_temp()
        except Exception as e:
            print("DS18B20 변환 실패:", e)
            conv_ms = now        # 잠시 뒤 다시 시도한다
            return
        conv_ms = now
        return
    if ticks_diff(now, conv_ms) < config.DS_CONV_MS:
        return
    conv_ms = None
    for rom in roms:
        try:
            t = ds.read_temp(rom)
        except Exception:
            t = None
        if t is not None and -0.01 < t - config.TEMP_BAD < 0.01:
            t = None             # 전원 직후 85.0은 '측정 실패' 값이다
        temps[rom] = t


def current_temps():
    t_bridge = temps.get(bridge_rom) if bridge_rom is not None else None
    t_air = temps.get(air_rom) if air_rom is not None else None
    return (t_bridge, t_air)


def read_wet_raw():
    """젖음센서 4회 평균(0~65535). 센서가 없으면 None."""
    if wet_adc is None:
        return None
    total = 0
    for _ in range(4):
        total += wet_adc.read_u16()
    return total // 4


def uptime_s(now):
    up = ticks_diff(now, boot_ms) // 1000
    return 0 if up < 0 else up


def set_warn_led(on):
    if warn_led is not None:
        warn_led.value(1 if on else 0)


def set_buzzer(on):
    if buzzer is not None:
        buzzer.value(1 if on else 0)


def close_all_servos():
    """네 갈래 서보를 모두 닫는다(STOP·정지 시)."""
    closed = cross_core.servo_duty(config.SERVO_CLOSED_DEG)
    for arm in cross_core.ARMS:
        servos[arm].duty_u16(closed)


def open_servo(arm):
    if arm in servos:
        servos[arm].duty_u16(cross_core.servo_duty(config.SERVO_OPEN_DEG))


def apply_spray_event(ev, now):
    """큐 이벤트 하나를 서보·부저에 반영하고 '@@EVT' 한 줄로 맥에 알린다."""
    global beep_until
    e = ev.get("e")
    if e == "spray_start":
        open_servo(ev.get("arm"))
        set_buzzer(1)
        beep_until = now + config.BEEP_MS     # 루프에서 시간을 보고 끈다(막히지 않는다)
    elif e == "spray_done":
        arm = ev.get("arm")
        if arm in servos:
            servos[arm].duty_u16(cross_core.servo_duty(config.SERVO_CLOSED_DEG))
    elif e == "stopped":
        close_all_servos()
        set_buzzer(0)
        beep_until = None
    print(cross_core.evt_line(ev))


def apply_led_dict(cmd, now):
    """이미 검증된 4갈래 모드 dict를 반영한다."""
    global arms_modes, last_led_ms
    arms_modes = cmd
    last_led_ms = now


def handle_spray_cmd(cmd, now):
    """'@@SPRAY' 명령을 큐에 넣고, 필요하면 거절/완료 이벤트를 보낸다."""
    res = queue.submit(cmd["seq"], cmd["arm"], cmd["ms"], now)
    status = res["status"]
    if status == "reject":
        print(cross_core.evt_line(cross_core.event("spray_reject", res["seq"], res["arm"])))
    elif status == "done":
        # 이미 끝난 seq의 재전송 요청: 실행하지 않고 완료만 다시 알린다
        print(cross_core.evt_line(cross_core.event("spray_done", res["seq"], res["arm"])))


def handle_line(line, now):
    """USB 한 줄을 해석해 반영한다. 모르는 줄은 조용히 버린다."""
    parsed = cross_core.parse_line(line)
    if parsed is None:
        if cross_core.is_spray_line(line):
            # 형식이 틀린 살포 명령도 조용히 버리지 않고 거절을 알린다(서버가 4초 기다리지 않게)
            hint = cross_core.spray_hint(line)
            print(cross_core.evt_line(cross_core.event("spray_reject", hint["seq"], hint["arm"])))
        return
    kind = parsed[0]
    if kind == "led":
        apply_led_dict(parsed[1], now)
    elif kind == "spray":
        handle_spray_cmd(parsed[1], now)
    elif kind == "stop":
        ev = queue.stop()
        apply_spray_event(ev, now)


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
            break              # 더 읽을 것이 없다(시험용 stdin의 끝)
        if ch != "\n":
            if len(usb_buf) < config.CMD_MAX_LEN:
                usb_buf = usb_buf + ch
            else:
                usb_buf = ""   # 너무 긴 줄은 버린다(깨진 데이터가 계속 쌓이지 않게)
        else:
            line, usb_buf = usb_buf.strip(), ""
            if line:
                handle_line(line, now)
        try:
            ready = usb_poll.poll(0)
        except Exception:
            return


def show_leds(now):
    """갈래 LED 4개를 갱신한다. 색이 그대로면 쓰지 않는다."""
    global shown
    if arm_led is None:
        return
    view = cross_core.led_view(arms_modes, last_led_ms, now, config.LED_STALE_MS)
    bright = 255 if config.LED_MODE != "neopixel" else config.LED_BRIGHT
    colors = []
    for arm in cross_core.ARMS:
        colors.append(cross_core.led_rgb(view[arm], now, bright))
    key = tuple(colors)
    if key == shown:
        return
    shown = key
    if config.LED_MODE == "neopixel":
        for i in range(len(colors)):
            arm_led[i] = colors[i]
        arm_led.write()
    else:
        for i in range(len(colors)):
            arm_led[i].value(1 if max(colors[i]) > 0 else 0)


def loop_once(now):
    """한 주기: 온도·젖음 → 로컬 경고 → USB 수신 → 살포 큐 → 통신 → 갈래 LED."""
    global warn_state, last_tel_ms, beep_until
    ds_tick(now)
    t_bridge, t_air = current_temps()
    wet_raw = read_wet_raw()
    wet = cross_core.is_wet(wet_raw, config.WET_THRESHOLD, config.WET_WHEN_LOW)
    warn_state = cross_core.local_warn(t_bridge, wet, warn_state,
                                       config.WARN_ON_C, config.FREEZE_C, config.WARN_OFF_COUNT)
    set_warn_led(warn_state["warn"])      # 맥과 무관하게 즉시 반영

    receive_usb(now)

    events = queue.tick(now)
    for i in range(len(events)):
        apply_spray_event(events[i], now)

    if beep_until is not None and ticks_diff(now, beep_until) >= 0:
        set_buzzer(0)
        beep_until = None

    show_leds(now)

    due = last_tel_ms is None or ticks_diff(now, last_tel_ms) >= config.TELEMETRY_MS
    if due:
        tel = cross_core.telemetry(t_bridge, t_air, wet, wet_raw,
                                   warn_state["warn"], queue.busy(), uptime_s(now))
        print(cross_core.tel_line(tel))
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
