# 피코 WH 공통 스타터 (MicroPython): 센서 → 노트북 중계 서버(Command Code AI) → LED·서보
# 예시 프로필은 access_space(보행로·교통약자 접근공간 점유 안내)다.
# 다른 아이디어는 read_state(), local_level(), actuate() 세 함수와 config.PROFILE만 바꾼다.
#
# 배선
#   HC-SR04  VCC=VBUS(5V), GND, TRIG=GP2, ECHO=GP3
#            ECHO는 5V가 나오므로 1kΩ(위)/2kΩ(아래) 분압으로 3.3V로 낮춘다. RP2040 핀은 5V를 견디지 못한다.
#            센서 맞은편에 반사판을 둔다(아무것도 없으면 '센서 오류'로 처리된다)
#   PIR(HC-SR501)  VCC=VBUS, OUT=GP15 (출력 3.3V)  ← 보행자·휠체어 대기 감지
#   RGB LED(공통 캐소드)  R=GP16, G=GP17, B=GP18 (각 220Ω)
#   능동 부저(선택)  GP19     서보 SG90  신호=GP20, 전원=VBUS(또는 별도 5V, GND 공통)
#
# 통신: config.TRANSPORT="usb"(기본)면 USB 케이블로 '@@REQ {json}' 줄을 보내고 노트북 serial_bridge.py가
#       '@@RES {json}'으로 답한다. "wifi"면 핫스팟으로 중계 서버에 HTTP POST.
import json
import select
import sys
import time

import network
import urequests as requests
from machine import PWM, Pin, time_pulse_us

import config

trig = Pin(2, Pin.OUT)
echo = Pin(3, Pin.IN)
pir = Pin(15, Pin.IN)
red, green, blue = Pin(16, Pin.OUT), Pin(17, Pin.OUT), Pin(18, Pin.OUT)
buzzer = Pin(19, Pin.OUT)
servo = PWM(Pin(20))
servo.freq(50)
vibro = Pin(config.VIBRO_PIN, Pin.OUT) if config.VIBRO_PIN is not None else None  # 진동모터(트랜지스터 경유)

wlan = network.WLAN(network.STA_IF)
last_connect = None
seq = 0


def wifi_ok():
    """기다리지 않는다. 끊겨 있으면 15초마다 다시 연결을 시작만 하고 이번 판단은 로컬 규칙에 맡긴다."""
    global last_connect
    if wlan.isconnected():
        return True
    if last_connect is None or time.ticks_diff(time.ticks_ms(), last_connect) > 15000:
        wlan.active(True)
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        last_connect = time.ticks_ms()
        print("wifi 연결 시도: 2.4GHz 핫스팟인지 확인")
    return False


def distance_cm():
    """HC-SR04 3회 측정의 중앙값. 반사가 없으면 None(센서 오류)."""
    vals = []
    for _ in range(3):
        trig.low()
        time.sleep_us(2)
        trig.high()
        time.sleep_us(10)
        trig.low()
        t = time_pulse_us(echo, 1, 30000)
        vals.append(None if t < 0 else t / 58.0)
        time.sleep_ms(30)
    ok = sorted(v for v in vals if v is not None)
    return round(ok[len(ok) // 2], 1) if len(ok) >= 2 else None


occupied_since = None


def read_state():
    """센서 → dict. 센서 오류면 None(점유 타이머도 초기화: 못 본 시간을 점유로 세지 않는다)."""
    global occupied_since
    d = distance_cm()
    if d is None:
        occupied_since = None
        return None
    now = time.ticks_ms()
    if d < config.OCCUPIED_CM:
        if occupied_since is None:
            occupied_since = now
    else:
        occupied_since = None
    occupied_s = 0 if occupied_since is None else time.ticks_diff(now, occupied_since) // 1000
    return {"distance_cm": d, "occupied_s": occupied_s, "waiting": pir.value() == 1}


def local_level(s):
    """네트워크가 안 될 때만 쓰는 규칙(AI 아님). 0 정상, 1 안내, 2 통행 확보, 3 관리자 확인."""
    if s["occupied_s"] < config.NOTICE_S:
        return 0
    if s["occupied_s"] < config.WARN_S:
        return 1
    return 3 if s["occupied_s"] >= config.STAFF_S and s["waiting"] else 2


def state_key(s, loc):
    """상황이 바뀌었는지 보는 키: 로컬 단계 + 참/거짓 센서값. 어느 프로필 state에도 그대로 쓸 수 있다.
    AI 응답은 요청할 때의 키와 지금 키가 같을 때만 적용한다."""
    return (loc,) + tuple(v for k, v in sorted(s.items()) if isinstance(v, bool))


def make_request(state, loc, key, poll=False):
    """poll=True면 AI 판단 없이 '승인된 에이전트 명령(cmd)'만 확인한다(API 비용 없음).
    k(상황 키)는 매 요청에 실어 중계 서버가 '제안 뒤 상황이 바뀌었는지'를 판단하게 한다."""
    global seq
    seq += 1
    req = {"device": config.DEVICE_ID, "profile": config.PROFILE, "state": state, "local_level": loc, "seq": seq,
           "pos": config.POS, "k": list(key)}
    if poll:
        req["poll"] = True
    return req


def take_cmd(out, cmd, now):
    """응답의 승인 명령을 반영해 새 cmd (단계, 받은 시각)를 돌려준다. 같은 cmd_id는 다시 적용하지 않고
    (유지시간 연장 없음), 새 명령은 아직 유효한 기존 명령보다 낮추지 않는다."""
    global last_cmd_id
    if "cmd" not in out or out.get("cmd_id") == last_cmd_id:
        return cmd
    last_cmd_id = out.get("cmd_id")
    level = out["cmd"]
    if cmd and time.ticks_diff(now, cmd[1]) < config.CMD_HOLD_S * 1000:
        level = max(level, cmd[0])
    return (level, now)


last_cmd_id = None


def ask_http(req):
    """Wi-Fi 모드(선택): 최대 5초 기다린다. 실패하면 None."""
    if not wifi_ok():
        return None
    try:
        r = requests.post(config.RELAY_URL, data=json.dumps(req).encode(), timeout=5,
                          headers={"Content-Type": "application/json", "X-Relay-Token": config.RELAY_TOKEN})
        try:
            if r.status_code == 200:
                return r.json()
            print("relay", r.status_code, r.text[:120])
        finally:
            r.close()
    except Exception as e:
        print("relay 연결 실패", e)
    return None


usb_poll = select.poll()
usb_poll.register(sys.stdin, select.POLLIN)
usb_buf = ""


def usb_receive():
    """USB 모드(기본): 기다리지 않고 지금 도착한 글자만 읽어 완성된 '@@RES' 줄을 돌려준다.
    줄바꿈이 없는 조각이나 깨진 JSON은 버린다."""
    global usb_buf
    done = []
    while usb_poll.poll(0):
        ch = sys.stdin.read(1)
        if ch != "\n":
            usb_buf = usb_buf + ch if len(usb_buf) < 600 else ""
            continue
        line, usb_buf = usb_buf.strip(), ""
        if line.startswith("@@RES "):
            try:
                done.append(json.loads(line[6:]))
            except ValueError:
                pass
    return done


def set_servo(angle):
    servo.duty_u16(1638 + (8192 - 1638) * angle // 180)  # 0.5ms~2.5ms 펄스


def actuate(level, offline=False, action=None):
    """0 초록, 1 노랑(안내·확인 필요), 2 빨강, 3 빨강+안내 깃발.
    offline=True면 파랑을 함께 켜서 'AI 없이 로컬 규칙으로 동작 중'임을 보인다. level=None은 센서 오류(파랑만).
    action은 jev가 고른 선택지 이름이다(로컬 규칙일 때 None). 경로 안내처럼 선택지마다 동작이 다른 아이디어는
    여기서 분기한다. 예: route_a면 set_servo(45), route_b면 set_servo(135)."""
    if level is None:
        red.value(0)
        green.value(0)
        blue.value(1)
        return
    red.value(level >= 1)
    green.value(level <= 1)
    blue.value(offline)
    set_servo(90 if level >= 3 else 0)
    if level >= 2 and (config.BUZZER or vibro):
        for _ in range(level - 1):  # 2단계 1번, 3단계 2번
            if config.BUZZER:
                buzzer.value(1)
            if vibro:
                vibro.value(1)
            time.sleep_ms(150)
            buzzer.value(0)
            if vibro:
                vibro.value(0)
            time.sleep_ms(100)


def main():
    if config.TRANSPORT == "wifi":
        wifi_ok()
    ai = None          # (단계, 요청 당시 키, 받은 시각): 지금 키와 같고 30초 안에 받은 것만 쓴다
    pending = None     # USB: (seq, 키, 보낸 시각). 기다리는 동안에도 센서·동작은 계속 돈다
    cmd = None         # (단계, 받은 시각): 에이전트가 다른 노드 상황 때문에 올린 단계
    last_ask, last_poll, last_key = time.ticks_ms(), time.ticks_ms(), None
    while True:
        state = read_state()
        if state is None:
            actuate(None)
            ai, last_key = None, None
            time.sleep(0.5)
            continue
        loc = local_level(state)
        key = state_key(state, loc)
        now = time.ticks_ms()
        if config.TRANSPORT == "usb":
            for out in usb_receive():
                if pending and out.get("seq") == pending[0]:
                    if "level" in out:
                        ai = (out["level"], pending[1], now, out.get("action"))
                        print("AI", out)
                    cmd = take_cmd(out, cmd, now)
                    pending = None
            if pending and time.ticks_diff(now, pending[2]) > 8000:
                pending = None  # 응답 없음: 다음에 다시 묻는다(그동안은 로컬 규칙)
        due = time.ticks_diff(now, last_ask) > config.ASK_INTERVAL_S * 1000
        poll = config.POLL_S and time.ticks_diff(now, last_poll) > config.POLL_S * 1000
        if pending is None and (key != last_key or due or poll):
            ask = key != last_key or due
            req = make_request(state, loc, key, poll=not ask)
            if config.TRANSPORT == "usb":
                print("@@REQ " + json.dumps(req))
                pending = (req["seq"], key, now)
            else:
                out = ask_http(req)
                if out and out.get("seq") == req["seq"]:
                    if "level" in out:
                        ai = (out["level"], key, now, out.get("action"))
                        print("AI", out)
                    cmd = take_cmd(out, cmd, now)
            last_poll = now
            if ask:
                last_ask, last_key = now, key
        use_ai = ai and ai[1] == key and time.ticks_diff(now, ai[2]) < 30000
        level = ai[0] if use_ai else loc
        if config.REFLEX:
            level = max(level, loc)
        if cmd and time.ticks_diff(now, cmd[1]) < config.CMD_HOLD_S * 1000:
            level = max(level, cmd[0])  # 에이전트 명령은 단계를 올리기만 한다
        # 파랑 = 지금 표시는 AI가 아니라 로컬 규칙(대기·끊김 포함)
        actuate(level, offline=not use_ai, action=ai[3] if use_ai else None)
        time.sleep(0.5)


main()
