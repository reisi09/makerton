# ICE-ZERO 보드(Pico #1) 순수 로직: 하드웨어·네트워크 모듈을 import하지 않는다.
# main.py는 이 함수들을 호출만 하고, 시험(tests/test_board_core.py)은 이 파일만 CPython으로 돌린다.
import json

# 칸 ID는 계약 2절의 루프(주행) 순서다. 칸 LED 체인 순서도 이 순서를 따른다.
CELL_IDS = ("U1", "U2", "U3", "U4", "D4", "D3", "D2", "D1")
LED_MODES = ("risk1", "risk2", "risk3", "plan", "salted", "off")

WARN_ON_C = 1.0          # config.WARN_ON_C와 같은 기본값
FREEZE_C = 0.0
WARN_OFF_COUNT = 3       # 켜짐 조건이 이만큼 연속 거짓이면 끈다
WET_THRESHOLD = 30000    # config.WET_THRESHOLD와 같은 기본값
WET_WHEN_LOW = True
LED_BRIGHT = 48          # 0~255. 낮게
LED_STALE_MS = 10000     # 서버 LED 명령이 이보다 오래 없으면 칸 LED를 끈다
BLINK_HZ = 2.0           # plan 모드 깜박임 주파수

_TICKS_FULL = 0x40000000
_TICKS_HALF = 0x20000000

# 모드별 최대 밝기 색. 실제 출력은 밝기(brightness)로 나눠 낮춘다.
_COLORS = {
    "risk1": (0, 255, 0),        # 초록: 위험 없음
    "risk2": (255, 180, 0),      # 노랑: 관측 주의
    "risk3": (255, 0, 0),        # 빨강: 상대 우선순위 높음
    "plan": (0, 80, 255),        # 파랑: 승인 계획에 포함, 아직 안 뿌림(2Hz 깜박)
    "salted": (255, 255, 255),   # 흰색: 이번 밤에 살포함
    "off": (0, 0, 0),
}


def ticks_diff(a, b):
    """MicroPython time.ticks_diff와 같은 부호 있는 차이(카운터 래핑을 고려)."""
    return ((a - b + _TICKS_HALF) % _TICKS_FULL) - _TICKS_HALF


def loop_index(cell):
    """칸 ID → 루프 순서 인덱스(0~7). 모르는 ID면 None."""
    for i in range(len(CELL_IDS)):
        if CELL_IDS[i] == cell:
            return i
    return None


def warn_on(t_piece, wet, warn_on_c=WARN_ON_C, freeze_c=FREEZE_C):
    """계약 7절의 켜짐 조건만 본다. 온도를 못 읽었으면(None) 절대 켜지 않는다."""
    if t_piece is None:
        return False
    if t_piece <= freeze_c:
        return True
    return t_piece <= warn_on_c and bool(wet)


def local_warn(t_piece, wet, state, warn_on_c=WARN_ON_C, freeze_c=FREEZE_C, off_count=WARN_OFF_COUNT):
    """주의 LED 히스테리시스. state={"warn":bool,"off":int}를 받아 새 dict를 돌려준다(입력은 바꾸지 않는다).

    켜짐: 켜짐 조건이 참이면 즉시 켜고 off를 0으로 되돌린다.
    꺼짐: 켜짐 조건이 off_count(기본 3)회 연속 거짓일 때만 끈다.
    t_piece가 None이면 젖음만으로는 켜지 않고 이전 상태를 그대로 유지한다(센서 오류로 표시가 흔들리지 않게).
    """
    warn = bool(state.get("warn")) if state else False
    off = int(state.get("off", 0)) if state else 0
    if t_piece is None:
        return {"warn": warn, "off": off}
    if warn_on(t_piece, wet, warn_on_c, freeze_c):
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


def led_view(cells, last_ms, now_ms, stale_ms=LED_STALE_MS):
    """표시할 칸 모드 8개 dict. 명령이 없거나 오래됐으면(끊김) 모두 off."""
    view = dict((c, "off") for c in CELL_IDS)
    if not cells or last_ms is None:
        return view
    if ticks_diff(now_ms, last_ms) >= stale_ms:
        return view
    for c in CELL_IDS:
        m = cells.get(c)
        if m in LED_MODES:
            view[c] = m
    return view


def check_led_cmd(obj):
    """서버가 보낸 {"cells":{...}}를 검증해 8칸 dict로 만든다. 하나라도 이상하면 None(전체 무시)."""
    if not isinstance(obj, dict):
        return None
    src = obj.get("cells")
    if not isinstance(src, dict):
        return None
    out = dict((c, "off") for c in CELL_IDS)
    for key in src:
        cell = str(key).strip().upper()
        if cell not in out:
            return None      # 계약에 없는 칸 ID
        mode = src[key]
        if mode not in LED_MODES:
            return None      # 모르는 LED 모드
        out[cell] = mode
    return out


def parse_led_line(line):
    """'@@LED {json}' 한 줄을 파싱한다. 형식이 틀리면 None(그 줄은 버린다)."""
    if not isinstance(line, str):
        return None
    s = line.strip()
    if not s.startswith("@@LED"):
        return None
    body = s[5:].strip()
    if not body:
        return None
    try:
        obj = json.loads(body)
    except ValueError:
        return None
    return check_led_cmd(obj)


def _round2(v):
    if v is None:
        return None
    return round(v, 2)


def telemetry(t_piece, t_air, wet, wet_raw, warn, up):
    """계약 7절 텔레메트리 dict. 형식(키·타입)은 여기서만 만든다."""
    return {
        "t_piece": _round2(t_piece),
        "t_air": _round2(t_air),
        "wet": bool(wet),
        "wet_raw": -1 if wet_raw is None else int(wet_raw),
        "warn": bool(warn),
        "up": int(up),
    }


def tel_line(tel):
    """USB 모드에서 print로 내보낼 한 줄."""
    return "@@TEL " + json.dumps(tel)


def rom_hex(rom):
    """ROM bytes → '28:01:..' 문자열(로그용)."""
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
    piece = roms[index]
    air = None
    for i in range(len(roms)):
        if i != index:
            air = roms[i]
            break
    return (piece, air)
