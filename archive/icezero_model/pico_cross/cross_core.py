# ICE-ZERO 사거리 모형(Pico #1) 순수 로직: 하드웨어 모듈을 import하지 않는다.
# main.py는 이 함수들을 호출만 하고, 시험(tests/test_pico_cross.py)은 이 파일만 CPython으로 돌린다.
# 규칙은 계약(CONTRACT_CROSS.md 5절)을 따른다: 갈래 N·E·S·W, 살포 1개씩, LED 6가지 모드.
import json

ARMS = ("N", "E", "S", "W")                                  # 갈래 ID. LED 체인 순서도 같다
LED_MODES = ("risk1", "risk2", "risk3", "plan", "done", "off")  # 갈래 LED 표시 모드

WARN_ON_C = 1.0          # config.WARN_ON_C와 같은 기본값
FREEZE_C = 0.0           # config.FREEZE_C와 같은 기본값
WARN_OFF_COUNT = 3       # 켜짐 조건이 이만큼 연속 거짓이면 끈다
WET_THRESHOLD = 30000    # config.WET_THRESHOLD와 같은 기본값
WET_WHEN_LOW = True
LED_BRIGHT = 48          # 0~255. 낮게
LED_STALE_MS = 10000     # 맥 LED 명령이 이보다 오래 없으면 갈래 LED를 끈다
BLINK_HZ = 2.0           # plan 모드 깜박임 주파수
QUEUE_MAX = 4            # 실행 중일 때 대기시킬 수 있는 살포 명령 수
SPRAY_MS = 600           # ms가 빠졌을 때 쓰는 기본 살포 시간
SPRAY_MS_MIN = 50        # 허용하는 살포 시간 하한
SPRAY_MS_MAX = 5000      # 허용하는 살포 시간 상한
DONE_KEEP = 16           # 끝난 seq를 기억하는 개수
SERVO_DUTY_MIN = 1638    # 0.5ms 펄스(스타터와 같은 식)
SERVO_DUTY_MAX = 8192    # 2.5ms 펄스

_TICKS_FULL = 0x40000000
_TICKS_HALF = 0x20000000

# 모드별 최대 밝기 색. 실제 출력은 밝기(brightness)로 나눠 낮춘다.
_COLORS = {
    "risk1": (0, 255, 0),        # 초록: 위험 낮음
    "risk2": (255, 180, 0),      # 노랑: 관측 주의
    "risk3": (255, 0, 0),        # 빨강: 상대 우선순위 높음
    "plan": (0, 80, 255),        # 파랑: 승인 계획에 포함, 아직 안 뿌림(2Hz 깜박)
    "done": (255, 255, 255),     # 흰색: 이번 밤에 살포함
    "off": (0, 0, 0),
}


def ticks_diff(a, b):
    """MicroPython time.ticks_diff와 같은 부호 있는 차이(카운터 래핑을 고려)."""
    return ((a - b + _TICKS_HALF) % _TICKS_FULL) - _TICKS_HALF


def arm_index(arm):
    """갈래 ID → 순서 인덱스(0~3). 모르는 ID면 None."""
    for i in range(len(ARMS)):
        if ARMS[i] == arm:
            return i
    return None


def servo_duty(angle):
    """각도(0~180) → duty_u16. 스타터 pico/main.py의 set_servo와 같은 식(0.5~2.5ms)."""
    if angle < 0:
        angle = 0
    if angle > 180:
        angle = 180
    return SERVO_DUTY_MIN + (SERVO_DUTY_MAX - SERVO_DUTY_MIN) * angle // 180


# ---------------------------------------------------------------- 살포 큐
class SprayQueue:
    """갈래 살포 명령 큐. 한 번에 하나만 열고, ms가 지나면 닫고 다음 것을 연다.

    서보를 직접 건드리지 않는다(하드웨어 import 금지). main.py가 tick()이 돌려준
    이벤트를 보고 서보를 열고 닫는다.
      - 같은 seq는 한 번만 실행한다(대기 중·실행 중이면 무시).
      - 이미 끝난 seq를 다시 받으면 spray_done을 다시 보낸다(status="done").
      - 대기 큐가 QUEUE_MAX를 넘으면 status="reject".
      - stop()은 모두 닫고 큐를 비운다(status는 main이 서보를 닫는 데 쓴다).
    """

    def __init__(self, max_queue=QUEUE_MAX, done_keep=DONE_KEEP):
        self.max_queue = max_queue
        self.done_keep = done_keep
        self.waiting = []      # [{"seq","arm","ms"}]
        self.active = None     # {"seq","arm","ms","started"}
        self.done = []         # 끝난 seq(최근 것만 남긴다)

    def busy(self):
        """지금 살포 중인가(실행 중). 대기만 있는 상태는 False다."""
        return self.active is not None

    def pending(self):
        """대기 중인 명령 수."""
        return len(self.waiting)

    def _known(self, seq):
        if self.active is not None and self.active["seq"] == seq:
            return True
        for job in self.waiting:
            if job["seq"] == seq:
                return True
        return False

    def _finished(self, seq):
        for s in self.done:
            if s == seq:
                return True
        return False

    def submit(self, seq, arm, ms, now):
        """명령 하나를 넣는다. 돌려주는 dict의 status: queued/dup/done/reject."""
        if self._finished(seq):
            return {"status": "done", "seq": seq, "arm": arm}
        if self._known(seq):
            return {"status": "dup", "seq": seq, "arm": arm}
        if len(self.waiting) >= self.max_queue:
            return {"status": "reject", "seq": seq, "arm": arm}
        self.waiting.append({"seq": seq, "arm": arm, "ms": ms})
        return {"status": "queued", "seq": seq, "arm": arm}

    def tick(self, now):
        """시간을 진행시켜 나온 이벤트 목록을 돌려준다(spray_start / spray_done)."""
        out = []
        while True:
            if self.active is not None:
                job = self.active
                if ticks_diff(now, job["started"]) < job["ms"]:
                    break                      # 아직 열려 있어야 한다
                self.active = None
                self.done.append(job["seq"])
                if len(self.done) > self.done_keep:
                    self.done = self.done[-self.done_keep:]
                out.append({"e": "spray_done", "seq": job["seq"], "arm": job["arm"]})
                continue                       # 닫았으니 다음 것을 바로 열 수 있다
            if not self.waiting:
                break
            job = self.waiting.pop(0)
            self.active = {"seq": job["seq"], "arm": job["arm"], "ms": job["ms"], "started": now}
            out.append({"e": "spray_start", "seq": job["seq"], "arm": job["arm"]})
            break                              # 시작은 한 번에 하나만
        return out

    def stop(self):
        """모든 살포를 멈추고 큐를 비운다. 돌려주는 dict는 그대로 '@@EVT' 한 줄이 된다."""
        seq = 0
        arm = ""
        if self.active is not None:
            seq = self.active["seq"]
            arm = self.active["arm"]
        self.active = None
        self.waiting = []
        return {"e": "stopped", "seq": seq, "arm": arm}


# ---------------------------------------------------------------- 로컬 경고·젖음
def warn_on(t_bridge, wet, warn_on_c=WARN_ON_C, freeze_c=FREEZE_C):
    """계약 5절의 켜짐 조건만 본다. 온도를 못 읽었으면(None) 절대 켜지 않는다."""
    if t_bridge is None:
        return False
    if t_bridge <= freeze_c:
        return True
    return t_bridge <= warn_on_c and bool(wet)


def local_warn(t_bridge, wet, state, warn_on_c=WARN_ON_C, freeze_c=FREEZE_C, off_count=WARN_OFF_COUNT):
    """교량 주의 LED 히스테리시스. state={"warn":bool,"off":int}를 받아 새 dict를 돌려준다(입력은 그대로).

    켜짐: 켜짐 조건이 참이면 즉시 켜고 off를 0으로 되돌린다.
    꺼짐: 켜짐 조건이 off_count(기본 3)회 연속 거짓일 때만 끈다.
    t_bridge가 None이면 젖음만으로는 켜지 않고 이전 상태를 유지한다(센서 오류로 표시가 흔들리지 않게).
    """
    warn = bool(state.get("warn")) if state else False
    off = int(state.get("off", 0)) if state else 0
    if t_bridge is None:
        return {"warn": warn, "off": off}
    if warn_on(t_bridge, wet, warn_on_c, freeze_c):
        return {"warn": True, "off": 0}
    off = off + 1
    if off >= off_count:
        return {"warn": False, "off": off_count}
    return {"warn": warn, "off": off}


def is_wet(raw, threshold=WET_THRESHOLD, when_low=WET_WHEN_LOW):
    """ADC raw → 젖음 여부. when_low=True면 raw가 임계값 이하일 때 젖은 것으로 본다."""
    if raw is None:
        return False
    if when_low:
        return raw <= threshold
    return raw >= threshold


# ---------------------------------------------------------------- 갈래 LED
def led_rgb(mode, now_ms=0, brightness=LED_BRIGHT):
    """LED 모드 → (r, g, b). plan은 2Hz로 깜박여 절반 주기 동안 (0,0,0)이다."""
    base = _COLORS.get(mode)
    if base is None:
        return (0, 0, 0)
    if mode == "plan":
        period = int(1000.0 / BLINK_HZ)
        if period > 0 and now_ms % period >= period // 2:
            return (0, 0, 0)
    b = brightness
    if b < 0:
        b = 0
    if b > 255:
        b = 255
    return (base[0] * b // 255, base[1] * b // 255, base[2] * b // 255)


def led_view(arms, last_ms, now_ms, stale_ms=LED_STALE_MS):
    """표시할 갈래 모드 4개 dict. 명령이 없거나 오래됐으면(끊김) 모두 off."""
    view = {}
    for arm in ARMS:
        view[arm] = "off"
    if not arms or last_ms is None:
        return view
    if ticks_diff(now_ms, last_ms) >= stale_ms:
        return view
    for arm in ARMS:
        mode = arms.get(arm)
        if mode in LED_MODES:
            view[arm] = mode
    return view


def check_led_cmd(obj):
    """맥이 보낸 {"arms":{...}}를 검증해 4갈래 dict로 만든다. 하나라도 이상하면 None(전체 무시)."""
    if not isinstance(obj, dict):
        return None
    src = obj.get("arms")
    if not isinstance(src, dict):
        return None
    out = {}
    for arm in ARMS:
        out[arm] = "off"
    for key in src:
        arm = str(key).strip().upper()
        if arm not in out:
            return None           # 계약에 없는 갈래 ID
        mode = src[key]
        if mode not in LED_MODES:
            return None           # 모르는 LED 모드
        out[arm] = mode
    return out


def check_spray_cmd(obj):
    """맥이 보낸 {"seq","arm","ms"}를 검증한다. 갈래가 N/E/S/W가 아니면 None."""
    if not isinstance(obj, dict):
        return None
    seq = obj.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int):
        return None
    if seq < 0:
        return None
    arm = obj.get("arm")
    if not isinstance(arm, str):
        return None
    arm = arm.strip().upper()
    if arm not in ARMS:
        return None               # 갈래는 N·E·S·W만 받는다
    ms = obj.get("ms", SPRAY_MS)
    if isinstance(ms, bool) or not isinstance(ms, int):
        return None
    if ms < SPRAY_MS_MIN or ms > SPRAY_MS_MAX:
        return None               # 너무 짧거나 긴 살포는 거절한다
    return {"seq": seq, "arm": arm, "ms": ms}


# ---------------------------------------------------------------- 줄 파싱
def _json_body(line, prefix):
    """'<prefix> {json}' 한 줄에서 JSON 부분만 꺼내 dict로 만든다. 형식이 틀리면 None."""
    if not isinstance(line, str):
        return None
    s = line.strip()
    if not s.startswith(prefix):
        return None
    body = s[len(prefix):].strip()
    if not body:
        return None
    try:
        obj = json.loads(body)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def parse_led_line(line):
    """'@@LED {json}' 한 줄을 파싱한다. 형식이 틀리면 None(그 줄은 버린다)."""
    obj = _json_body(line, "@@LED")
    if obj is None:
        return None
    return check_led_cmd(obj)


def parse_spray_line(line):
    """'@@SPRAY {json}' 한 줄을 파싱한다. 형식이 틀리면 None."""
    obj = _json_body(line, "@@SPRAY")
    if obj is None:
        return None
    return check_spray_cmd(obj)


def is_spray_line(line):
    """'@@SPRAY'로 시작하는 줄인가(형식이 틀려도 거절 이벤트를 보내기 위해 쓴다)."""
    if not isinstance(line, str):
        return False
    return line.strip().startswith("@@SPRAY")


def spray_hint(line):
    """형식이 틀린 '@@SPRAY' 줄에서 seq·arm만 최대한 꺼낸다(거절 이벤트용)."""
    obj = _json_body(line, "@@SPRAY")
    seq = 0
    arm = ""
    if isinstance(obj, dict):
        s = obj.get("seq")
        if isinstance(s, int) and not isinstance(s, bool) and s >= 0:
            seq = s
        a = obj.get("arm")
        if isinstance(a, str):
            arm = a.strip().upper()
    return {"seq": seq, "arm": arm}


def parse_stop_line(line):
    """'@@STOP' 한 줄인가. 뒤에 붙은 JSON은 무시한다(계약은 @@STOP {})."""
    if not isinstance(line, str):
        return False
    s = line.strip()
    return s == "@@STOP" or s.startswith("@@STOP ")


def parse_line(line):
    """USB 한 줄 → ("led", 4갈래 dict) / ("spray", 명령 dict) / ("stop", None) / None."""
    if parse_stop_line(line):
        return ("stop", None)
    led = parse_led_line(line)
    if led is not None:
        return ("led", led)
    spray = parse_spray_line(line)
    if spray is not None:
        return ("spray", spray)
    return None


# ---------------------------------------------------------------- 텔레메트리·이벤트
def _round2(v):
    if v is None:
        return None
    return round(v, 2)


def telemetry(t_bridge, t_air, wet, wet_raw, warn, busy, up):
    """계약 5절 텔레메트리 dict. 형식(키·타입)은 여기서만 만든다."""
    return {
        "t_bridge": _round2(t_bridge),
        "t_air": _round2(t_air),
        "wet": bool(wet),
        "wet_raw": -1 if wet_raw is None else int(wet_raw),
        "warn": bool(warn),
        "busy": bool(busy),
        "up": int(up),
    }


def tel_line(tel):
    """USB로 내보낼 '@@TEL {json}' 한 줄."""
    return "@@TEL " + json.dumps(tel)


def event(e, seq=0, arm=""):
    """'@@EVT'에 실을 이벤트 dict. 키 순서(e, seq, arm)를 고정한다."""
    return {"e": e, "seq": int(seq), "arm": arm}


def evt_line(ev):
    """USB로 내보낼 '@@EVT {json}' 한 줄."""
    return "@@EVT " + json.dumps(ev)


# ---------------------------------------------------------------- DS18B20 보조
def rom_hex(rom):
    """ROM bytes → '28:01:..' 문자열(부팅 로그용)."""
    if not rom:
        return ""
    return ":".join("%02X" % b for b in rom)


def pick_roms(roms, index):
    """정렬된 ROM 목록에서 (시험편, 공기)를 고른다. index가 범위를 벗어나면 0번을 시험편으로 쓴다."""
    roms = list(roms)
    if not roms:
        return (None, None)
    if index < 0 or index >= len(roms):
        index = 0
    bridge = roms[index]
    air = None
    for i in range(len(roms)):
        if i != index:
            air = roms[i]
            break
    return (bridge, air)
