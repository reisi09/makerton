# ICE-ZERO 기지 Pico #1의 순수 로직: 하드웨어 모듈을 import하지 않는다.
# main.py는 이 함수들을 호출만 하고, 시험(tests/test_sensors.py)은 이 파일을 CPython으로 그대로 돌린다.
# 규칙은 계약(CONTRACT.md 6절)을 따른다: 갈래 N·E·S·W, DHT11 2초 간격, 10초 유지,
# 로컬 경고 히스테리시스, 도킹 디바운스, 자동·수동 보충, 링 경광등.
import json

ARMS = ("N", "E", "S", "W")                                        # 갈래 ID. 링 픽셀 순서도 같다
LED_MODES = ("risk1", "risk2", "risk3", "plan", "done", "off")     # 링·OLED에 표시하는 갈래 상태

MSG_MAX = 16             # '@@SHOW' msg 최대 글자 수(OLED·LCD 한 줄)
OLED_COLS = 16           # OLED 한 줄 최대 글자 수(6x8 폰트). 넘치면 잘라 쓴다
OLED_ROWS = 4            # 128×32 → 8px 글자 4줄
LCD_COLS = 16            # 1602 LCD 한 줄 글자 수
LCD_ROWS = 2

WET_ARM = "W"            # 젖음 센서가 붙은 갈래(그늘이 가장 깊은 W 길가)
DHT_INTERVAL_MS = 2000   # config.DHT_INTERVAL_MS와 같은 기본값
DHT_HOLD_MS = 10000      # config.DHT_HOLD_MS와 같은 기본값
DHT_T_MIN = 0.0          # DHT11이 재는 온도 범위
DHT_T_MAX = 50.0
DHT_RH_MIN = 0.0
DHT_RH_MAX = 100.0

WARN_T = 3.0             # config.WARN_T와 같은 기본값
WARN_RH = 85
WARN_OFF_COUNT = 3
WET_THRESHOLD = 40000
WET_WHEN_LOW = True

SHOW_STALE_MS = 10000    # config.SHOW_STALE_MS와 같은 기본값
LED_BRIGHT = 48
BLINK_HZ = 2.0           # plan 모드 깜박임 주파수
BEACON_STEP_MS = 150     # 경광등이 한 픽셀씩 도는 간격(ms)

DOCK_DEBOUNCE_MS = 50    # 도킹 스위치 디바운스(ms). 이만큼 같은 값이 유지돼야 인정
DOCK_SETTLE_MS = 1000    # 도킹이 이만큼 이어져야 자동 보충
REFILL_MS = 800          # 게이트를 여는 기본 시간(ms)
REFILL_MS_MIN = 50       # 받아들이는 보충 시간 하한(ms)
REFILL_MS_MAX = 5000     # 받아들이는 보충 시간 상한(ms)
REFILL_COOLDOWN_MS = 20000
GATE_DUTY_MIN = 1638     # 0.5ms 펄스
GATE_DUTY_MAX = 8192     # 2.5ms 펄스

_TICKS_FULL = 0x40000000
_TICKS_HALF = 0x20000000

# 갈래 상태별 최대 밝기 색. 실제 출력은 밝기로 나눠 낮춘다.
_COLORS = {
    "risk1": (0, 255, 0),        # 초록: 위험 낮음
    "risk2": (255, 180, 0),      # 노랑: 관측 주의
    "risk3": (255, 0, 0),        # 빨강: 상대 우선순위 높음
    "plan": (0, 80, 255),        # 파랑: 계획에 포함(2Hz 깜박)
    "done": (255, 255, 255),     # 흰색: 이번 밤에 처리함
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


def _ascii(text, limit):
    """ASCII 16자 표시용 문자열. 한글·제어문자는 '?'로 바꾸고 limit자로 자른다.

    SSD1306·HD44780 기본 폰트는 ASCII만 그린다. 서버가 한글 msg를 보내도 화면에 깨진 글자가
    남지 않게 한다(계약 6절: msg는 ASCII 16자).
    """
    out = ""
    s = "" if text is None else str(text)
    for ch in s.strip():
        code = ord(ch)
        if code < 32 or code > 126:
            out = out + "?"
        else:
            out = out + ch
        if len(out) >= limit:
            break
    return out


def servo_duty(angle, duty_min=GATE_DUTY_MIN, duty_max=GATE_DUTY_MAX):
    """각도(0~180) → duty_u16. SG90 0.5~2.5ms 식(참고 pico_cross와 같은 식)."""
    if angle < 0:
        angle = 0
    if angle > 180:
        angle = 180
    return duty_min + (duty_max - duty_min) * angle // 180


def is_wet(raw, threshold=WET_THRESHOLD, when_low=WET_WHEN_LOW):
    """ADC raw → 젖음 여부. when_low=True면 raw가 임계값 이하일 때 젖은 것으로 본다."""
    if raw is None:
        return False
    if when_low:
        return raw <= threshold
    return raw >= threshold


def dht_valid(t, rh, t_min=DHT_T_MIN, t_max=DHT_T_MAX, rh_min=DHT_RH_MIN, rh_max=DHT_RH_MAX):
    """DHT11이 돌려준 값이 정상 범위인가. None이거나 범위 밖이면 False(측정 실패로 본다)."""
    if t is None or rh is None:
        return False
    if t < t_min or t > t_max:
        return False
    if rh < rh_min or rh > rh_max:
        return False
    return True


# ---------------------------------------------------------------- DHT11 순환 읽기·값 유지
class SensorBank:
    """DHT11 4개를 2초 이상 간격으로 돌아가며 읽고, 실패해도 마지막 정상값을 10초까지 유지한다.

    하드웨어는 모른다. main이 due()로 '지금 읽을 갈래'를 받아 실제 센서를 읽고 apply()로 알려준다.
    measured()는 텔레메트리용 (온도 dict, 습도 dict, 정상 dict)를 만든다.
    """

    def __init__(self, arms=ARMS, interval_ms=DHT_INTERVAL_MS, hold_ms=DHT_HOLD_MS):
        self.arms = tuple(arms)
        self.interval_ms = int(interval_ms)
        self.hold_ms = int(hold_ms)
        self.temp = {}        # 갈래 → 마지막 정상 온도
        self.hum = {}         # 갈래 → 마지막 정상 습도
        self.good_ms = {}     # 갈래 → 마지막 정상 읽기 시각
        self.try_ms = {}      # 갈래 → 마지막 시도 시각(성공·실패 모두)
        self.ok = {}          # 갈래 → 마지막 시도가 정상이었는가
        for arm in self.arms:
            self.temp[arm] = None
            self.hum[arm] = None
            self.good_ms[arm] = None
            self.try_ms[arm] = None
            self.ok[arm] = False

    def due(self, now):
        """지금 읽어야 할 갈래 ID. 아직 한 번도 안 읽었거나 간격이 지난 갈래 중 가장 오래된 것."""
        best = None
        best_age = -1
        for arm in self.arms:
            last = self.try_ms.get(arm)
            if last is None:
                return arm                      # 한 번도 안 읽은 갈래를 먼저 읽는다
            age = ticks_diff(now, last)
            if age >= self.interval_ms and age > best_age:
                best = arm
                best_age = age
        return best

    def apply(self, arm, t, rh, now):
        """DHT11 한 번의 결과를 반영한다. t·rh가 None이거나 범위 밖이면 실패로 기록한다."""
        if arm not in self.temp:
            return
        self.try_ms[arm] = now
        if not dht_valid(t, rh):
            self.ok[arm] = False                # 값은 지우지 않는다. 10초까지는 마지막 정상값을 쓴다
            return
        self.temp[arm] = round(float(t), 1)
        self.hum[arm] = int(rh)
        self.good_ms[arm] = now
        self.ok[arm] = True

    def _kept(self, arm, table, now):
        """마지막 정상값. 정상 읽기로부터 hold_ms가 지났으면 None(오래된 값을 쓰지 않는다)."""
        value = table.get(arm)
        when = self.good_ms.get(arm)
        if value is None or when is None:
            return None
        if ticks_diff(now, when) > self.hold_ms:
            return None
        return value

    def measured(self, now):
        """(온도 dict, 습도 dict, 정상 dict). 실패한 갈래는 ok=False이고 10초 뒤 값이 null이 된다."""
        t = {}
        rh = {}
        ok = {}
        for arm in self.arms:
            tv = self._kept(arm, self.temp, now)
            rv = self._kept(arm, self.hum, now)
            t[arm] = tv
            rh[arm] = rv
            ok[arm] = bool(self.ok.get(arm)) and tv is not None and rv is not None
        return (t, rh, ok)


# ---------------------------------------------------------------- 로컬 경고
def warn_condition(arms_t, arms_rh, wet, warn_t=WARN_T, warn_rh=WARN_RH, wet_arm=WET_ARM):
    """계약 6절의 켜짐 조건.

    어느 갈래든 (t ≤ WARN_T이고 rh ≥ WARN_RH)이거나, (젖었고 젖음 센서가 붙은 갈래 온도 ≤ WARN_T)다.
    온도를 못 읽은 갈래는 후보에서 뺀다(측정 실패로 경고를 켜지 않는다).
    """
    for arm in ARMS:
        t = arms_t.get(arm)
        rh = arms_rh.get(arm)
        if t is None or rh is None:
            continue
        if t <= warn_t and rh >= warn_rh:
            return True
    if wet:
        t_wet = arms_t.get(wet_arm)
        if t_wet is not None and t_wet <= warn_t:
            return True
    return False


def local_warn(on, state, off_count=WARN_OFF_COUNT):
    """로컬 경고 히스테리시스. state={"warn":bool,"off":int}를 받아 새 dict를 돌려준다(입력은 그대로).

    켜짐: 조건이 참이면 즉시 켜고 off를 0으로 되돌린다.
    꺼짐: 조건이 off_count(기본 3)회 연속 거짓일 때만 끈다. 한 번 참이면 다시 센다.
    """
    warn = bool(state.get("warn")) if state else False
    off = int(state.get("off", 0)) if state else 0
    if on:
        return {"warn": True, "off": 0}
    off = off + 1
    if off >= off_count:
        return {"warn": False, "off": off_count}
    return {"warn": warn, "off": off}


# ---------------------------------------------------------------- 도킹·보충
def _is_int(v):
    """JSON 정수인가(bool은 정수로 치지 않는다)."""
    return isinstance(v, int) and not isinstance(v, bool)


class Debouncer:
    """도킹 스위치 디바운스. 같은 입력이 stable_ms 동안 유지돼야 값이 바뀐 것으로 본다."""

    def __init__(self, stable_ms=DOCK_DEBOUNCE_MS, initial=False):
        self.stable_ms = int(stable_ms)
        self.value = bool(initial)
        self.since = None      # 지금 값과 다른 입력이 시작된 시각(None이면 같은 값이 이어짐)

    def update(self, raw, now):
        raw = bool(raw)
        if raw == self.value:
            self.since = None
            return self.value
        if self.since is None:
            self.since = now
            return self.value
        if ticks_diff(now, self.since) >= self.stable_ms:
            self.value = raw
            self.since = None
        return self.value


class RefillController:
    """보충 게이트 상태 기계. 서보는 main이 움직이고, 이 클래스는 '언제 열고 닫을지'만 계산한다.

    자동: 도킹이 settle_ms 이어지고, auto이고, 마지막 보충에서 cooldown_ms가 지났으면 한 번 연다.
    수동: request()는 도킹 중일 때만 받는다.
    한 도킹(도킹했다 떼기까지)에 한 번만 연다. 수동 보충도 한 번으로 센다.
    """

    def __init__(self, auto=True, ms=REFILL_MS, settle_ms=DOCK_SETTLE_MS,
                 cooldown_ms=REFILL_COOLDOWN_MS):
        self.auto = bool(auto)
        self.ms = int(ms)
        self.settle_ms = int(settle_ms)
        self.cooldown_ms = int(cooldown_ms)
        self.docked = False
        self.dock_ms = None       # 도킹이 시작된 시각
        self.done = False         # 이번 도킹에서 이미 열었는가
        self.last_ms = None       # 마지막으로 게이트를 연 시각
        self.open_until = None    # 게이트를 닫을 시각(None이면 닫혀 있다)
        self.count = 0            # 지금까지 연 횟수

    def refilling(self):
        return self.open_until is not None

    def update(self, docked, now):
        """도킹 상태를 반영한다. 자동 보충을 시작하면 여는 시간(ms), 아니면 None."""
        docked = bool(docked)
        if not docked:
            self.docked = False
            self.dock_ms = None
            self.done = False     # 다음 도킹에서는 다시 한 번 열 수 있다
            return None
        if not self.docked:
            self.docked = True
            self.dock_ms = now
            self.done = False
            return None           # 정착 시간을 기다린다
        if not self.auto or self.done:
            return None
        if ticks_diff(now, self.dock_ms) < self.settle_ms:
            return None
        if self.last_ms is not None and ticks_diff(now, self.last_ms) < self.cooldown_ms:
            return None
        return self._open(self.ms, now)

    def request(self, ms, now):
        """수동 보충. 도킹 중일 때만 연다. {"ok":bool,"ms":int,"reason":str}를 돌려준다."""
        if not self.docked:
            return {"ok": False, "ms": 0, "reason": "not_docked"}
        if ms is None or not _is_int(ms) or ms < REFILL_MS_MIN or ms > REFILL_MS_MAX:
            return {"ok": False, "ms": 0, "reason": "bad_ms"}
        return {"ok": True, "ms": self._open(int(ms), now), "reason": ""}

    def _open(self, ms, start):
        self.open_until = start + int(ms)
        self.last_ms = start
        self.done = True          # 한 도킹에 한 번(수동도 포함해 두 번 열지 않는다)
        self.count = self.count + 1
        return int(ms)

    def tick(self, now):
        """열린 시간이 끝났으면 True(게이트를 닫아라)를 돌려준다."""
        if self.open_until is None:
            return False
        if ticks_diff(now, self.open_until) >= 0:
            self.open_until = None
            return True
        return False


# ---------------------------------------------------------------- 링·OLED 표시
def is_stale(last_ms, now_ms, stale_ms=SHOW_STALE_MS):
    """맥 명령이 없었거나 stale_ms보다 오래됐는가."""
    if last_ms is None:
        return True
    return ticks_diff(now_ms, last_ms) > stale_ms


def show_view(modes, last_ms, now_ms, stale_ms=SHOW_STALE_MS):
    """지금 표시할 갈래 상태 4개. 명령이 없거나 오래됐으면(맥 끊김) 모두 off."""
    view = {}
    for arm in ARMS:
        view[arm] = "off"
    if modes is None or is_stale(last_ms, now_ms, stale_ms):
        return view
    for arm in ARMS:
        mode = modes.get(arm)
        if mode in LED_MODES:
            view[arm] = mode
    return view


def ring_rgb(mode, now_ms=0, brightness=LED_BRIGHT):
    """갈래 상태 → (r, g, b). plan은 2Hz로 깜박여 절반 주기 동안 (0,0,0)이다."""
    base = _COLORS.get(mode)
    if base is None:
        base = _COLORS["off"]
    b = int(brightness)
    if b < 0:
        b = 0
    if b > 255:
        b = 255
    if mode == "plan" and not blink_on(now_ms):
        return (0, 0, 0)
    return (base[0] * b // 255, base[1] * b // 255, base[2] * b // 255)


def blink_on(now_ms):
    """깜박임의 켜짐 구간인가(주기 1/BLINK_HZ초, 앞 절반이 켜짐)."""
    period_ms = int(1000.0 / BLINK_HZ)
    return (int(now_ms) % period_ms) * 2 < period_ms


def beacon_pixels(n_pixels=8, now_ms=0, brightness=LED_BRIGHT):
    """경광등(출동 중): 파랑 바탕 위로 흰색 두 픽셀이 링을 따라 돈다."""
    b = int(brightness)
    if b < 0:
        b = 0
    if b > 255:
        b = 255
    dim = b // 4
    pos = (int(now_ms) // BEACON_STEP_MS) % n_pixels
    out = []
    for i in range(n_pixels):
        if i == pos or i == (pos + 1) % n_pixels:
            out.append((b, b, b))          # 흰색
        else:
            out.append((0, 0, dim))        # 파랑
    return out


def ring_pixels(modes, n_pixels=8, now_ms=0, brightness=LED_BRIGHT, per_arm=2, beacon=False):
    """링에 쓸 색 목록.

    beacon이 참이면 갈래 상태 대신 경광등이 돈다(계약 6절: @@SHOW의 beacon).
    아니면 갈래 하나가 per_arm픽셀씩 차례로 붙는다(N=0,1 E=2,3 S=4,5 W=6,7).
    """
    if beacon:
        return beacon_pixels(n_pixels, now_ms, brightness)
    out = []
    for _ in range(n_pixels):
        out.append((0, 0, 0))
    for i in range(len(ARMS)):
        color = ring_rgb(modes.get(ARMS[i], "off"), now_ms, brightness)
        for k in range(per_arm):
            idx = i * per_arm + k
            if idx < n_pixels:
                out[idx] = color
    return out


def _temp_str(v):
    """OLED용 온도 문자열. 못 읽었으면 '--.-'."""
    if v is None:
        return "--.-"
    return "%.1f" % v


def _temp_int_str(v):
    """LCD용 온도 문자열. 1602 두 줄에 네 갈래를 넣으려고 정수로 줄인다. 못 읽었으면 '--'."""
    if v is None:
        return "--"
    return str(int(round(v)))


def oled_lines(arms_t, ok, wet, warn, msg="", up=0):
    """128×32 OLED에 넣을 줄 4개. 각 줄은 OLED_COLS(16)자를 넘지 않고 ASCII만 쓴다.

    line0: 맥이 준 msg(없으면 제목) · line1: N/E 온도 · line2: S/W 온도 · line3: 경고·젖음·가동시간.
    """
    lines = []
    head = _ascii(msg, OLED_COLS)
    if head:
        lines.append(head)
    else:
        lines.append("ICE-ZERO SENSOR")
    lines.append(("N " + _temp_str(arms_t.get("N")) + "  E " + _temp_str(arms_t.get("E")))[:OLED_COLS])
    lines.append(("S " + _temp_str(arms_t.get("S")) + "  W " + _temp_str(arms_t.get("W")))[:OLED_COLS])
    flag = "WARN" if warn else "ok"
    wet_s = "WET" if wet else "DRY"
    miss = ""
    for arm in ARMS:
        if not ok.get(arm):
            miss = " !"
            break
    line3 = flag + " " + wet_s + " " + str(int(up)) + "s" + miss
    lines.append(line3[:OLED_COLS])
    return lines


def lcd_lines(msg, arms_t):
    """1602 LCD 두 줄. 1줄은 msg(ASCII 16자), 2줄은 갈래 온도 예 'N12 E11 S12 W10'."""
    line1 = _ascii(msg, LCD_COLS)
    line2 = ""
    for arm in ARMS:
        line2 = line2 + arm + _temp_int_str(arms_t.get(arm))
        if arm != ARMS[-1]:
            line2 = line2 + " "
    return [line1, line2[:LCD_COLS]]


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
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def parse_show_line(line):
    """'@@SHOW {"arms":{...},"msg":"...","beacon":b}' 한 줄을 파싱한다. 형식이 틀리면 None.

    빠진 갈래는 off로 채운다. 갈래 ID·상태 이름·beacon 타입이 하나라도 이상하면 줄 전체를 버린다.
    """
    obj = _json_body(line, "@@SHOW")
    if obj is None:
        return None
    arms = obj.get("arms")
    if not isinstance(arms, dict):
        return None
    out = {}
    for arm in ARMS:
        out[arm] = "off"
    for key in arms:
        arm = str(key).strip().upper()
        if arm not in ARMS:
            return None
        mode = arms[key]
        if mode not in LED_MODES:
            return None
        out[arm] = mode
    msg = obj.get("msg", "")
    if msg is None:
        msg = ""
    if not isinstance(msg, str):
        return None
    msg = msg.strip()
    if len(msg) > MSG_MAX:
        msg = msg[:MSG_MAX]
    beacon = obj.get("beacon", False)
    if not isinstance(beacon, bool):
        return None
    return {"arms": out, "msg": msg, "beacon": beacon}


def parse_refill_line(line):
    """'@@REFILL {"ms":800}' 한 줄을 파싱한다. 쓸 수 있는 값이면 {"ms":n}, 아니면 None."""
    obj = _json_body(line, "@@REFILL")
    if obj is None:
        return None
    ms = obj.get("ms", REFILL_MS)
    if not _is_int(ms):
        return None
    if ms < REFILL_MS_MIN or ms > REFILL_MS_MAX:
        return None
    return {"ms": int(ms)}


def parse_line(line):
    """USB 한 줄 → ("show", dict) / ("refill", {"ms"}) / None(모르는 줄은 조용히 버린다)."""
    got = parse_show_line(line)
    if got is not None:
        return ("show", got)
    got = parse_refill_line(line)
    if got is not None:
        return ("refill", got)
    return None


# ---------------------------------------------------------------- 텔레메트리
def _round_t(v):
    if v is None:
        return None
    return round(float(v), 1)


def telemetry(arms_t, arms_rh, ok, wet_raw, wet, light_raw, warn, dock, refills, refilling, up):
    """계약 6절 텔레메트리 dict. 형식(키·타입)은 여기서만 만든다."""
    t = {}
    rh = {}
    okd = {}
    for arm in ARMS:
        t[arm] = _round_t(arms_t.get(arm))
        rv = arms_rh.get(arm)
        rh[arm] = None if rv is None else int(rv)
        okd[arm] = bool(ok.get(arm))
    if wet_raw is None:
        wet_i = 0
    else:
        wet_i = int(wet_raw)
    if light_raw is None:
        light_i = None
    else:
        light_i = int(light_raw)
    return {
        "t": t,
        "rh": rh,
        "ok": okd,
        "wet_raw": wet_i,
        "wet": bool(wet),
        "light_raw": light_i,
        "warn": bool(warn),
        "dock": bool(dock),
        "refills": int(refills),
        "refilling": bool(refilling),
        "up": int(up),
    }


def tel_line(tel):
    """USB로 내보낼 '@@TEL {json}' 한 줄."""
    return "@@TEL " + json.dumps(tel)
