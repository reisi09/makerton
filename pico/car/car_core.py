# ICE-ZERO 제설차(Pico #2) 순수 로직.
# 하드웨어(machine·network·socket)를 import하지 않는다. 시험은 이 파일을 CPython으로 그대로 돌린다.
#
# 좌표: x는 동쪽, y는 남쪽(mm). 원점은 보드 왼쪽 위 모서리다.
# 교차로 중심은 (CENTER_X, CENTER_Y). 홈은 북동쪽 기지 차고 안 (BASE_X, BASE_Y)이고 서쪽 출입구를 본다.
# 방위는 시계 방향이다(N=0, E=90, S=180, W=270). 전진하면 x는 sin(h), y는 -cos(h)만큼 움직인다.
#
# 시간 인자는 전부 ms 정수다. MicroPython의 ticks_ms·ticks_us는 0x40000000에서 감싸므로
# ticks_diff·ticks_add로 계산한다. CPython 시험에서는 그냥 늘어나는 정수를 넣으면 된다.

import json
import math

import config

# ── 상태·구간 이름(계약 7절 tel·evt) ─────────────────────────────────
STATE_IDLE = "idle"
STATE_RUN = "run"
STATE_PAUSE = "pause"
STATE_STOPPED = "stopped"
STATE_ERROR = "error"

PHASE_IDLE = "idle"
PHASE_DEPART = "depart"
PHASE_TURN = "turn"
PHASE_OUT = "out"
PHASE_BACK = "back"
PHASE_HOME = "home"

EV_PLAN_START = "plan_start"
EV_ARM_START = "arm_start"
EV_SPRAY_ON = "spray_on"
EV_SPRAY_OFF = "spray_off"
EV_ARM_DONE = "arm_done"
EV_PLAN_DONE = "plan_done"
EV_STOPPED = "stopped"
EV_OBSTACLE = "obstacle"
EV_RESUMED = "resumed"
EV_ABORTED = "aborted"

# 하프스텝 8단계 시퀀스. ULN2003 IN1~IN4에 그대로 넣는다.
HALF_STEP = ((1, 0, 0, 0), (1, 1, 0, 0), (0, 1, 0, 0), (0, 1, 1, 0),
             (0, 0, 1, 0), (0, 0, 1, 1), (0, 0, 0, 1), (1, 0, 0, 1))

_TICKS_FULL = 0x40000000
_TICKS_HALF = 0x20000000


def ticks_diff(a, b):
    """MicroPython time.ticks_diff와 같은 부호 있는 차이(카운터 감싸기 고려)."""
    return ((a - b + _TICKS_HALF) % _TICKS_FULL) - _TICKS_HALF


def ticks_add(a, b):
    """MicroPython time.ticks_add. 0x40000000에서 감싼다."""
    return (a + b) % _TICKS_FULL


# ── 기준점 ──────────────────────────────────────────────────────────
DOCK_X = config.BASE_X
DOCK_Y = config.BASE_Y
DOCK_H = config.BASE_H
DOOR_MM = DOCK_X - config.CENTER_X          # 차고 → N 도로 가운데(서쪽)
DOOR_TO_CENTER_MM = config.CENTER_Y - DOCK_Y  # 출입구 높이 → 교차로 중심(남쪽)


# ── 기구 수치 ────────────────────────────────────────────────────────
MM_PER_STEP = math.pi * config.WHEEL_D_MM / config.STEPS_PER_REV
                                   # 1스텝에 바퀴가 굴러가는 거리(약 0.0499mm)
DEG_PER_STEP = 360.0 * config.WHEEL_D_MM / (config.TRACK_MM * config.STEPS_PER_REV)
                                   # 제자리 회전 1스텝의 각도(약 0.0544도)


def mm_to_steps(mm):
    """거리(mm) → 하프스텝 수. 반올림은 0.5 올림."""
    n = abs(mm) / MM_PER_STEP
    return int(n + 0.5)


def deg_to_steps(deg):
    """제자리 회전 각도(도) → 하프스텝 수."""
    n = abs(deg) / DEG_PER_STEP
    return int(n + 0.5)


def norm_deg(deg):
    """0 이상 360 미만으로 접는다."""
    d = deg % 360.0
    if d < 0:
        d += 360.0
    return d


def shortest_delta(target, current):
    """target까지 가장 짧게 도는 각도(-180~180). 음수면 반시계다."""
    return norm_deg(target - current + 180.0) - 180.0


def bearing_to(dx, dy):
    """보드 좌표 변화량 → 방위(도). 북이 0도, 시계 방향이다(y가 남쪽이다)."""
    return norm_deg(math.degrees(math.atan2(dx, -dy)))


# ── 자세(추측항법) ──────────────────────────────────────────────────
class Pose(object):
    """스텝을 밀 때마다 갱신하는 추측 위치·방위. 센서로 보정하지 않는다(추측항법)."""

    def __init__(self, x=None, y=None, h=None):
        self.x = DOCK_X if x is None else x
        self.y = DOCK_Y if y is None else y
        self.h = norm_deg(DOCK_H if h is None else h)

    def forward(self, mm):
        """방위 방향으로 mm만큼 굴러간 것으로 본다(음수면 후진). 남쪽이 y 증가다."""
        rad = math.radians(self.h)
        self.x += math.sin(rad) * mm
        self.y -= math.cos(rad) * mm

    def rotate(self, deg):
        self.h = norm_deg(self.h + deg)

    def dist_to_center(self):
        dx = config.CENTER_X - self.x
        dy = config.CENTER_Y - self.y
        return math.sqrt(dx * dx + dy * dy)

    def dock(self):
        """차고 안 도킹 위치·출입구 방향으로 다시 맞춘다."""
        self.x = DOCK_X
        self.y = DOCK_Y
        self.h = DOCK_H

    def as_dict(self):
        return {"x": self.x, "y": self.y, "h": self.h}


# ── 구간 만들기 ──────────────────────────────────────────────────────
def _turn_seg(deg, phase, arm):
    return {"kind": "turn", "deg": deg, "steps": deg_to_steps(deg),
            "dir": 1 if deg >= 0 else -1, "phase": phase, "arm": arm,
            "spray": False, "window": None, "mode": "dist"}


def _drive_seg(mm, phase, arm, spray=False, window=None, mode="dist", reverse=False):
    """mm는 거리(mm, 양수). reverse면 같은 거리를 후진한다.
    남은 거리 기준으로 살포하려면 mode="remain"을 쓴다."""
    return {"kind": "drive", "mm": mm, "steps": mm_to_steps(mm),
            "dir": -1 if reverse else 1, "phase": phase, "arm": arm,
            "spray": bool(spray), "window": window, "mode": mode}



def _depart_leg(heading):
    """1. 출발: 차고에서 서쪽으로 나와 N 도로 가운데에서 남쪽으로 돌아 교차로 중심까지."""
    return [_turn_seg(shortest_delta(DOCK_H, heading), PHASE_TURN, None),
            _drive_seg(DOOR_MM, PHASE_DEPART, None),
            _turn_seg(shortest_delta(180.0, DOCK_H), PHASE_TURN, None),
            _drive_seg(DOOR_TO_CENTER_MM, PHASE_DEPART, None)]


def _return_leg(heading):
    """3. 귀환: 북향으로 돌아 출입구 높이까지 간 뒤, 출입구 쪽(서쪽)을 보고 후진해 차고에 들어간다."""
    return [_turn_seg(shortest_delta(0.0, heading), PHASE_HOME, None),
            _drive_seg(DOOR_TO_CENTER_MM, PHASE_HOME, None),
            _turn_seg(shortest_delta(DOCK_H, 0.0), PHASE_HOME, None),
            _drive_seg(DOOR_MM, PHASE_HOME, None, reverse=True)]


def plan_for_order(order, pose=None):
    """갈래 순서 → 구간 목록. 차가 차고 안 도킹 위치에 있다고 본다.
    갈래마다 중심에서 그 방위로 돌아 끝까지 밀고(날이 눈을 보드 밖으로 민다) 같은 길을 후진으로 되짚는다."""
    if pose is None:
        pose = Pose()
    segs = _depart_leg(pose.h)
    heading = 180.0                     # 출발 구간을 지나면 남향이다
    for arm in order:
        bearing = config.ARM_BEARING[arm]
        dist = config.ARM_OUT_MM[arm]
        segs.append(_turn_seg(shortest_delta(bearing, heading), PHASE_TURN, arm))
        segs.append(_drive_seg(dist, PHASE_OUT, arm, True, config.SPRAY_WIN[arm], "dist"))
        # 같은 길을 후진으로 되짚는다. 갈 때 생긴 방향 오차가 돌아올 때 상쇄된다.
        segs.append(_drive_seg(dist, PHASE_BACK, arm, reverse=True))
        heading = float(bearing)
    segs.extend(_return_leg(heading))
    return _drop_empty(segs)


def plan_home(pose):
    """지금 추측 위치에서 차고로. 출입구 길(차고~N 도로)이면 바로 후진하고,
    도로 위면 도로를 따라 중심으로 간 뒤 귀환(3번)한다. 건물을 가로지르지 않는다."""
    tol = config.HOME_TOL_MM
    if abs(pose.x - DOCK_X) < tol and abs(pose.y - DOCK_Y) < tol:
        return []
    if abs(pose.y - DOCK_Y) < 20 and pose.x > config.CENTER_X + tol:
        return _drop_empty([_turn_seg(shortest_delta(DOCK_H, pose.h), PHASE_HOME, None),
                            _drive_seg(DOCK_X - pose.x, PHASE_HOME, None, reverse=True)])
    dx = config.CENTER_X - pose.x
    dy = config.CENTER_Y - pose.y
    dist = math.sqrt(dx * dx + dy * dy)
    heading = pose.h
    segs = []
    if dist >= config.HOME_TOL_MM:
        bearing = bearing_to(dx, dy)
        segs.append(_turn_seg(shortest_delta(bearing, heading), PHASE_HOME, None))
        segs.append(_drive_seg(dist, PHASE_HOME, None))
        heading = bearing
    segs.extend(_return_leg(heading))
    return _drop_empty(segs)


def _drop_empty(segs):
    """0스텝 구간(이미 그 방위다)은 뺀다."""
    out = []
    for seg in segs:
        if seg["steps"] > 0:
            out.append(seg)
    return out


def plan_steps(segs):
    total = 0
    for seg in segs:
        total += seg["steps"]
    return total


def ramp_us(done, left):
    """스텝 간격(µs). 정지에서 START_US로 출발해 RAMP_STEPS에 걸쳐 STEP_US까지 빨라지고 구간 끝에서 같은 길이로 느려진다.
    done = 이 구간(또는 다시 출발한 뒤) 이미 민 스텝, left = 이 스텝을 포함해 남은 스텝.
    2026-11-01 실차: 보드 위에서 0.6ms로 바로 출발하면 제자리에서 떨기만 하고, 1.2ms에서 가속하면 움직였다."""
    k = min(done, left - 1, config.RAMP_STEPS)
    return config.START_US - (config.START_US - config.STEP_US) * k // config.RAMP_STEPS


def _ramp_sum(n):
    """n스텝 구간에서 min(i, n-1-i, RAMP_STEPS)의 합(가감속으로 늘어나는 시간 계산용)."""
    r = config.RAMP_STEPS
    if (n - 1) // 2 <= r:
        p = n // 2
        return p * (p - 1) if n % 2 == 0 else p * p
    return r * (r - 1) + r * (n - 2 * r)


def plan_seconds(segs):
    """구간 목록을 가감속하며 밀 때 걸리는 시간(초). 구간마다 정지에서 출발해 정지로 끝난다."""
    slow = config.START_US - config.STEP_US
    total = 0.0
    for seg in segs:
        n = seg["steps"]
        total += n * config.START_US - slow * _ramp_sum(n) / float(config.RAMP_STEPS)
    return total / 1000000.0


def estimate_seconds(order):
    """도킹 위치에서 출발해 order를 돌고 기지로 돌아오는 예상 시간(초)."""
    return plan_seconds(plan_for_order(order, Pose()))


# ── 주행 계획 실행 ───────────────────────────────────────────────────
class Mission(object):
    """구간 목록을 스텝 단위로 소화한다. 자세는 Pose를 직접 고친다."""

    def __init__(self, segs, pose, dock_reset=True):
        self.segs = segs
        self.pose = pose
        self.dock_reset = dock_reset     # 계획이 끝나면 자세를 도킹 위치로 맞춘다
        self.i = 0
        self.done = not segs
        self.left = segs[0]["steps"] if segs else 0
        self.travel = 0.0                 # 지금 drive 구간에서 움직인 거리(mm, 부호 있음)
        self.spray = False
        self.steps_done = 0
        self.phase = segs[0]["phase"] if segs else PHASE_IDLE
        self.arm = segs[0]["arm"] if segs else None

    def begin(self):
        """계획을 시작할 때 낼 이벤트."""
        if self.done or self.arm is None:
            return []
        return [(EV_ARM_START, self.arm)]

    def ramp_pos(self):
        """다음 스텝의 (이 구간에서 이미 민 스텝, 이 스텝을 포함해 남은 스텝). ramp_us에 넘긴다."""
        if self.done:
            return 0, 1
        return self.segs[self.i]["steps"] - self.left, self.left

    def reversing(self):
        """지금 후진 중인가(귀환). 이때는 앞쪽 초음파를 무시한다."""
        if self.done:
            return False
        seg = self.segs[self.i]
        return seg["kind"] == "drive" and seg["dir"] < 0

    def step(self):
        """스텝 1회. (left, right, spray, events)를 돌려준다.
        left·right는 -1(뒤) · 0(정지) · 1(앞)이다. 구간이 끝나면 다음 구간으로 넘어간다."""
        if self.done:
            return (0, 0, False, [])
        seg = self.segs[self.i]
        events = []
        d = seg["dir"]
        if seg["kind"] == "turn":
            self.pose.rotate(d * DEG_PER_STEP)
            left = d
            right = -d
        else:
            self.pose.forward(d * MM_PER_STEP)
            self.travel += d * MM_PER_STEP
            left = d
            right = d
            if seg["spray"]:
                want = self._spray_now(seg)
                if want != self.spray:
                    self.spray = want
                    if want:
                        events.append((EV_SPRAY_ON, self.arm))
                    else:
                        events.append((EV_SPRAY_OFF, self.arm))
        self.left -= 1
        self.steps_done += 1
        if self.left <= 0:
            events.extend(self._advance())
        return (left, right, self.spray, events)

    def _spray_now(self, seg):
        """살포 구간 판정. dist는 중심에서 거리, remain은 구간 끝(중심)까지 남은 거리."""
        lo, hi = seg["window"]
        if seg["mode"] == "remain":
            dist = seg["mm"] - abs(self.travel)
        else:
            dist = abs(self.travel)
        return dist >= lo - 0.5 and dist <= hi + 0.5

    def _advance(self):
        events = []
        prev = self.segs[self.i]
        if self.spray:
            self.spray = False
            events.append((EV_SPRAY_OFF, prev["arm"]))
        self.i += 1
        nxt = self.segs[self.i] if self.i < len(self.segs) else None
        next_arm = nxt["arm"] if nxt is not None else None
        if prev["arm"] is not None and next_arm != prev["arm"]:
            events.append((EV_ARM_DONE, prev["arm"]))     # 그 갈래 일이 끝났다
        if nxt is None:
            self.done = True
            self.phase = PHASE_IDLE
            self.left = 0
            self.arm = None
            if self.dock_reset:
                self.pose.dock()
            events.append((EV_PLAN_DONE, None))
            return events
        self.left = nxt["steps"]
        self.travel = 0.0
        self.phase = nxt["phase"]
        if nxt["arm"] is not None and nxt["arm"] != prev["arm"]:
            self.arm = nxt["arm"]
            events.append((EV_ARM_START, nxt["arm"]))
        else:
            self.arm = nxt["arm"]
        return events


# ── 프로토콜 ────────────────────────────────────────────────────────
def valid_order(order):
    """서버가 보낸 갈래 순서를 검사한다. (ok, 갈래목록)."""
    if not isinstance(order, (list, tuple)):
        return (False, [])
    if len(order) == 0 or len(order) > 4:
        return (False, [])
    seen = []
    for arm in order:
        if arm not in config.ARM_BEARING:
            return (False, [])
        if arm in seen:                # 같은 갈래를 두 번 돌 이유가 없다
            return (False, [])
        seen.append(arm)
    return (True, list(order))


def make_hello(cfg=None):
    return {"t": "hello", "id": (cfg or config).CAR_ID}


def make_ack(seq, ok, reason=""):
    return {"t": "ack", "seq": seq, "ok": bool(ok), "reason": reason}


def make_evt(name, seq, arm=None):
    # 계약 예시와 같은 모양을 유지하려고 arm 키는 늘 넣는다(없으면 null).
    return {"t": "evt", "e": name, "seq": seq, "arm": arm}


def encode(obj):
    """한 데이터그램 = JSON 하나."""
    return json.dumps(obj).encode()


def parse(data):
    """받은 바이트/문자열 → dict. JSON이 아니면 None."""
    try:
        if isinstance(data, bytes):
            data = data.decode()
        obj = json.loads(data)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(obj, dict):
        return None
    return obj


# ── 차 상태기계 ──────────────────────────────────────────────────────
class CarCore(object):
    """계획·안전·통신 판단. 하드웨어는 main.py가 이 클래스의 지시만 따른다."""

    def __init__(self, cfg=None):
        self.cfg = cfg or config
        self.pose = Pose()
        self.state = STATE_IDLE
        self.phase = PHASE_IDLE
        self.seq = 0
        self.arm = None
        self.spray = False
        self.mission = None
        self.pause_reason = None       # None · "link" · "obstacle"
        self.blocked_since = None
        self.clear_since = None
        self.obst_cm = None
        self.last_rx = 0
        self.boot_ms = 0
        self.seen = []                 # 최근 seq(중복 실행 방지)
        self.out = []                  # 아직 안 보낸 메시지

    # ── 바깥에서 넣는 값 ──────────────────────────────────────────────
    def start(self, now_ms):
        """부팅 시각을 잡는다."""
        self.boot_ms = now_ms
        self.last_rx = now_ms

    def sonar(self, cm, now_ms):
        """초음파 측정값(cm). None이면 '비어 있음'이다."""
        self.obst_cm = cm
        if self.mission is not None and self.mission.reversing():
            return                     # 후진(귀환) 중에는 차고 벽을 장애물로 보지 않는다
        if cm is not None and cm < self.cfg.OBST_CM:
            if self.blocked_since is None:
                self.blocked_since = now_ms
                self.clear_since = None
                if self.state == STATE_RUN:
                    self._pause("obstacle", now_ms)
        elif self.blocked_since is not None:
            self.blocked_since = None
            self.clear_since = now_ms

    # ── 서버 패킷 ────────────────────────────────────────────────────
    def handle_packet(self, msg, now_ms):
        if not isinstance(msg, dict):
            return
        kind = msg.get("t")
        if not kind:
            return
        self.last_rx = now_ms
        seq = msg.get("seq")
        if seq is not None:
            if seq in self.seen:
                self._queue(make_ack(seq, False, "중복"))
                return
            self._remember(seq)
        if kind == "plan":
            self._take_plan(msg, now_ms)
        elif kind == "stop":
            self.stop(now_ms)
            if seq is not None:
                self._queue(make_ack(seq, True, ""))
        elif kind == "home":
            self._take_home(msg, now_ms)
        elif kind == "ping":
            if seq is not None:
                self._queue(make_ack(seq, True, ""))

    def _remember(self, seq):
        self.seen.append(seq)
        if len(self.seen) > 64:
            del self.seen[0]

    def _busy(self):
        if self.state in (STATE_RUN, STATE_PAUSE):
            return True
        return self.mission is not None and not self.mission.done

    def _take_plan(self, msg, now_ms):
        seq = msg.get("seq")
        if self._busy():
            self._queue(make_ack(seq, False, "실행 중"))
            return
        ok, order = valid_order(msg.get("order"))
        if not ok:
            self._queue(make_ack(seq, False, "갈래 오류"))
            return
        segs = plan_for_order(order, self.pose)
        if not segs:
            self._queue(make_ack(seq, False, "경로 없음"))
            return
        self._queue(make_ack(seq, True, ""))       # ack → plan_start → arm_start 순서
        self._start_mission(segs, seq, now_ms)

    def _take_home(self, msg, now_ms):
        seq = msg.get("seq")
        segs = plan_home(self.pose)
        if not segs:
            self._queue(make_ack(seq, True, "이미 홈"))
            return
        self._queue(make_ack(seq, True, ""))
        self._start_mission(segs, seq, now_ms)

    def _start_mission(self, segs, seq, now_ms):
        self.mission = Mission(segs, self.pose)
        self.seq = 0 if seq is None else seq
        self.state = STATE_RUN
        self.phase = self.mission.phase
        self.arm = self.mission.arm
        self.spray = False
        self.pause_reason = None
        self.blocked_since = None
        self.clear_since = None
        self.last_rx = now_ms
        self._queue(make_evt(EV_PLAN_START, self.seq, None))
        for name, arm in self.mission.begin():
            self._queue(make_evt(name, self.seq, arm))

    # ── 정지·재개 ────────────────────────────────────────────────────
    def stop(self, now_ms):
        """코일을 끄고 서보를 닫는다. 남은 구간은 기억해 두었다가 버튼으로 이어 간다."""
        if self.state == STATE_STOPPED:
            return False
        self._queue(make_evt(EV_STOPPED, self.seq, self.arm))
        self.state = STATE_STOPPED
        self.phase = PHASE_IDLE
        self.spray = False
        self.pause_reason = None
        self.blocked_since = None
        self.clear_since = None
        return True

    def resume(self, now_ms):
        if self.state != STATE_STOPPED:
            return False
        self.last_rx = now_ms          # 재개 직후 링크 타임아웃으로 바로 멈추지 않게 유예
        if self.mission is None or self.mission.done:
            self.state = STATE_IDLE
            return False
        self.state = STATE_RUN
        self.phase = self.mission.phase
        self.arm = self.mission.arm
        self._queue(make_evt(EV_RESUMED, self.seq, self.arm))
        return True

    def button(self, now_ms):
        """택트 스위치: 돌고 있으면 비상 정지, 멈춰 있으면 재개."""
        if self.state == STATE_STOPPED:
            return self.resume(now_ms)
        return self.stop(now_ms)

    def _pause(self, reason, now_ms):
        self.state = STATE_PAUSE
        self.pause_reason = reason
        self.phase = PHASE_IDLE
        self.spray = False
        if reason == "obstacle":
            self._queue(make_evt(EV_OBSTACLE, self.seq, self.arm))

    def _resume(self, now_ms):
        self.state = STATE_RUN
        self.pause_reason = None
        self.clear_since = None
        if self.mission is not None and not self.mission.done:
            self.phase = self.mission.phase
            self.arm = self.mission.arm
        self._queue(make_evt(EV_RESUMED, self.seq, self.arm))

    def _abort(self, now_ms):
        """10초 넘게 막혔다. 계획을 버리고 aborted를 알린다."""
        self._queue(make_evt(EV_ABORTED, self.seq, self.arm))
        self.mission = None
        self.state = STATE_ERROR
        self.phase = PHASE_IDLE
        self.arm = None
        self.spray = False
        self.pause_reason = None
        self.blocked_since = None
        self.clear_since = None

    # ── 매 루프 ──────────────────────────────────────────────────────
    def _gate(self, now_ms):
        """지금 움직이면 안 되는 이유. 없으면 None."""
        if self.blocked_since is not None:
            return "obstacle"
        if ticks_diff(now_ms, self.last_rx) >= self.cfg.LINK_TIMEOUT_MS:
            return "link"
        return None

    def tick(self, now_ms):
        """링크·장애물을 감시하고 상태를 맞춘다. 스텝은 step()이 민다."""
        if self.state not in (STATE_RUN, STATE_PAUSE):
            return
        if self.mission is None or self.mission.done:
            return
        if (self.blocked_since is not None and
                ticks_diff(now_ms, self.blocked_since) >= self.cfg.OBST_ABORT_MS):
            self._abort(now_ms)
            return
        want = self._gate(now_ms)
        if self.state == STATE_PAUSE:
            if want is None:
                if (self.clear_since is not None and
                        ticks_diff(now_ms, self.clear_since) < self.cfg.OBST_CLEAR_MS):
                    return          # 1초 동안 계속 비어 있어야 재개한다
                self._resume(now_ms)
            elif want != self.pause_reason:
                self.pause_reason = want
        elif want is not None:
            self._pause(want, now_ms)

    def can_step(self):
        return self.state == STATE_RUN and self.mission is not None and not self.mission.done

    def step(self):
        """스텝 1회. 실제로 움직이지 않으면 step=False를 돌려준다."""
        if not self.can_step():
            return {"step": False, "left": 0, "right": 0, "spray": False}
        left, right, spray, events = self.mission.step()
        self.spray = spray
        self.phase = self.mission.phase
        self.arm = self.mission.arm
        for name, arm in events:
            self._queue(make_evt(name, self.seq, arm))
        if self.mission.done:
            self.state = STATE_IDLE
            self.phase = PHASE_IDLE
            self.arm = None
            self.spray = False
        return {"step": True, "left": left, "right": right, "spray": spray}

    # ── 내보내기 ─────────────────────────────────────────────────────
    def tel(self, now_ms):
        obst = None
        if self.obst_cm is not None:
            obst = int(self.obst_cm * 10 + 0.5) / 10.0
        return {"t": "tel", "id": self.cfg.CAR_ID, "state": self.state,
                "seq": self.seq, "arm": self.arm, "phase": self.phase,
                "x": int(self.pose.x + 0.5), "y": int(self.pose.y + 0.5),
                "h": int(self.pose.h + 0.5) % 360, "spray": bool(self.spray),
                "obst_cm": obst, "up": int(ticks_diff(now_ms, self.boot_ms))}

    def _queue(self, msg):
        self.out.append(msg)

    def drain(self):
        """보낼 메시지를 꺼내고 큐를 비운다."""
        out = self.out
        self.out = []
        return out
