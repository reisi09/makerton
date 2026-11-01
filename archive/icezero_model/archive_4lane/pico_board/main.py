# ICE-ZERO 보드(Pico #1): 교량 시험편 온도·젖음 관측 + 주의 LED(로컬 규칙) + 칸 LED 8개 + 텔레메트리.
#
# 배선(계약 9절)
#   DS18B20 2개  데이터=GP4, 4.7kΩ 풀업 → 3V3 (시험편·공기)
#   젖음센서 AO  GP26(ADC0), 모듈 전원 3V3
#   주의 LED     GP15(220Ω)
#   칸 LED       neopixel: WS2812 8개 DIN=GP16(330Ω), 5V / gpio: 단색 LED 8개 GP6~GP13
#
# 동작
#   - 로컬 경고는 서버와 무관하게 항상 돈다(연결이 끊겨도 주의 LED는 계속 동작).
#   - USB 모드(기본): 1초마다 '@@TEL {json}' 한 줄을 print하고, 서버가 쓰는 '@@LED {json}' 줄을 읽는다.
#   - Wi-Fi 모드: 1초마다 POST /api/board/telemetry, 응답의 cells를 칸 LED에 반영한다. 실패하면 로컬만 돈다.
#   - 서버 LED 명령이 LED_STALE_MS(10초) 넘게 없으면 칸 LED는 꺼진다(마지막 상태를 사실처럼 보이지 않게).
import json
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

try:
    import network
except ImportError:
    network = None

try:
    import urequests as requests
except ImportError:
    requests = None

import board_core
import config

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

ds = None                 # ds18x20.DS18X20
roms = []                 # 정렬된 ROM 목록(bytes)
piece_rom = None          # 시험편(교량 금속) 센서 ROM
air_rom = None            # 공기 센서 ROM
temps = {}                # ROM → 마지막 온도(섭씨) 또는 None
conv_ms = None            # 변환을 시작한 시각(None이면 변환 중이 아님)
wet_adc = None            # machine.ADC
warn_led = None           # machine.Pin
cell_led = None           # neopixel.NeoPixel 또는 Pin 목록
warn_state = {"warn": False, "off": 0}
cells = {}                # 서버가 준 8칸 모드
last_led_ms = None        # 마지막 LED 명령 시각
shown = None              # 마지막으로 실제 출력한 색(중복 write 방지)
last_tel_ms = None
boot_ms = 0
usb_poll = None
usb_buf = ""
wlan = None
last_wifi_ms = None


def setup():
    """하드웨어 초기화. 부팅 때 한 번만 부른다."""
    global ds, roms, piece_rom, air_rom, wet_adc, warn_led, cell_led
    global usb_poll, usb_buf, boot_ms
    boot_ms = ticks_ms()
    warn_led = machine.Pin(config.PIN_WARN_LED, machine.Pin.OUT)
    warn_led.value(0)

    ds = ds18x20.DS18X20(onewire.OneWire(machine.Pin(config.PIN_DS)))
    roms = sorted(ds.scan())
    print("DS18B20 센서 %d개" % len(roms))
    for i in range(len(roms)):
        print("  [%d] %s" % (i, board_core.rom_hex(roms[i])))
    piece_rom, air_rom = board_core.pick_roms(roms, config.PIECE_INDEX)
    if len(roms) == 0:
        print("DS18B20이 없습니다: 온도는 null로 보냅니다")
    else:
        # 시험편이 몇 번째 센서인지는 배선 순서에 달렸다. 이 두 줄을 보고 config.PIECE_INDEX를 고친다.
        print("시험편(config.PIECE_INDEX=%d) = %s" % (config.PIECE_INDEX, board_core.rom_hex(piece_rom)))
        print("공기 = %s" % board_core.rom_hex(air_rom))
        for rom in roms:
            temps[rom] = None

    wet_adc = machine.ADC(machine.Pin(config.PIN_WET))

    if config.LED_MODE == "neopixel":
        if neopixel is None:
            print("neopixel 모듈이 없어 칸 LED를 켜지 않습니다")
            cell_led = None
        else:
            cell_led = neopixel.NeoPixel(machine.Pin(config.PIN_NEOPIXEL), len(board_core.CELL_IDS))
    else:
        cell_led = []
        for p in config.PIN_CELL_LEDS:
            cell_led.append(machine.Pin(p, machine.Pin.OUT))

    if config.TRANSPORT == "usb":
        try:
            usb_poll = select.poll()
            usb_poll.register(sys.stdin, select.POLLIN)
            usb_buf = ""
        except Exception as e:
            usb_poll = None
            print("stdin 폴링을 쓸 수 없어 USB 수신을 끕니다:", e)
    else:
        wifi_ok()   # 기다리지 않고 연결만 걸어 둔다


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
        if t is not None and -0.01 < t - 85.0 < 0.01:
            t = None             # 전원 직후 85.0은 '측정 실패' 값이다
        temps[rom] = t


def current_temps():
    t_piece = temps.get(piece_rom) if piece_rom is not None else None
    t_air = temps.get(air_rom) if air_rom is not None else None
    return (t_piece, t_air)


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


def wifi_ok():
    """기다리지 않는다. 끊겨 있으면 WIFI_RETRY_MS마다 재연결을 시작만 한다."""
    global wlan, last_wifi_ms
    if network is None:
        return False
    if wlan is None:
        wlan = network.WLAN(network.STA_IF)
    try:
        if wlan.isconnected():
            return True
        now = ticks_ms()
        if last_wifi_ms is None or ticks_diff(now, last_wifi_ms) >= config.WIFI_RETRY_MS:
            wlan.active(True)
            wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
            last_wifi_ms = now
            print("Wi-Fi 재연결 시도(2.4GHz 핫스팟인지 확인)")
    except Exception as e:
        print("Wi-Fi 오류:", e)
        last_wifi_ms = ticks_ms()
    return False


def post_telemetry(tel):
    """Wi-Fi 모드: 텔레메트리를 POST하고 응답 dict를 돌려준다. 실패하면 None(로컬 동작 유지)."""
    if requests is None or not wifi_ok():
        return None
    headers = {"Content-Type": "application/json"}
    if config.TOKEN:
        headers["X-Token"] = config.TOKEN
    try:
        r = requests.post(config.SERVER_URL, data=json.dumps(tel), headers=headers, timeout=3)
        try:
            if r.status_code == 200:
                return r.json()
            print("서버 응답", r.status_code)
        finally:
            r.close()
    except Exception as e:
        print("서버 연결 실패:", e)
    return None


def apply_led_cmd(obj, now):
    """LED 명령 반영. 형식이 틀리면 무시하고 이전 표시를 유지한다."""
    global cells, last_led_ms
    cmd = board_core.check_led_cmd(obj)
    if cmd is None:
        return False
    cells = cmd
    last_led_ms = now
    return True


def receive_usb(now):
    """USB 모드(기본): 기다리지 않고 지금 도착한 글자만 읽어 '@@LED' 줄을 처리한다."""
    global usb_buf
    if usb_poll is None:
        return
    try:
        ready = usb_poll.poll(0)
    except Exception:
        return
    while ready:
        ch = sys.stdin.read(1)
        if not ch:
            break          # 더 읽을 것이 없다(시험용 stdin)
        if ch != "\n":
            if ch and len(usb_buf) < 600:
                usb_buf = usb_buf + ch
            else:
                usb_buf = ""
        else:
            line, usb_buf = usb_buf.strip(), ""
            cmd = board_core.parse_led_line(line)
            if cmd is not None:
                apply_led_dict(cmd, now)
        try:
            ready = usb_poll.poll(0)
        except Exception:
            return


def apply_led_dict(cmd, now):
    """이미 검증된 8칸 dict를 반영한다."""
    global cells, last_led_ms
    cells = cmd
    last_led_ms = now


def show_leds(now):
    """칸 LED 8개를 갱신한다. 색이 그대로면 쓰지 않는다."""
    global shown
    if cell_led is None:
        return
    view = board_core.led_view(cells, last_led_ms, now, config.LED_STALE_MS)
    bright = 255 if config.LED_MODE != "neopixel" else config.LED_BRIGHT
    colors = []
    for cid in board_core.CELL_IDS:
        colors.append(board_core.led_rgb(view[cid], now, bright))
    key = tuple(colors)
    if key == shown:
        return
    shown = key
    if config.LED_MODE == "neopixel":
        for i in range(len(colors)):
            cell_led[i] = colors[i]
        cell_led.write()
    else:
        for i in range(len(colors)):
            cell_led[i].value(1 if max(colors[i]) > 0 else 0)


def loop_once(now):
    """한 주기: 온도·젖음 → 로컬 경고 LED → 통신(텔레메트리·LED 명령) → 칸 LED."""
    global warn_state, last_tel_ms
    ds_tick(now)
    t_piece, t_air = current_temps()
    wet_raw = read_wet_raw()
    wet = board_core.is_wet(wet_raw, config.WET_THRESHOLD, config.WET_WHEN_LOW)
    warn_state = board_core.local_warn(t_piece, wet, warn_state,
                                       config.WARN_ON_C, config.FREEZE_C, config.WARN_OFF_COUNT)
    set_warn_led(warn_state["warn"])     # 서버와 무관하게 즉시 반영

    tel = board_core.telemetry(t_piece, t_air, wet, wet_raw, warn_state["warn"], uptime_s(now))
    due = last_tel_ms is None or ticks_diff(now, last_tel_ms) >= config.TELEMETRY_MS
    if config.TRANSPORT == "wifi":
        if due:
            out = post_telemetry(tel)
            last_tel_ms = now
            if out is not None:
                apply_led_cmd(out, now)
    else:
        receive_usb(now)
        if due:
            print(board_core.tel_line(tel))
            last_tel_ms = now
    show_leds(now)


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
