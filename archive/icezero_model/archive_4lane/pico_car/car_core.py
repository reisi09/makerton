# ICE-ZERO 제설차(Pico #2) 순수 로직: 하드웨어·네트워크를 import하지 않는다.
# main.py는 이 클래스들을 호출만 하고, 시험(tests/test_car_core.py)은 이 파일만 CPython으로 돌린다.
#
# 시간은 전부 ms 정수로 인자로 받는다. MicroPython의 ticks_ms는 0x3FFFFFFF에서 감싸므로
# main.py는 time.ticks_diff를 주입한다. 기본값은 board_core와 같은 감싸기 고려 뺄셈이라
# CPython 시험에서는 그냥 증가하는 정수를 넣으면 된다.

# 칸 ID는 계약 2절의 루프(주행) 순서다.
LOOP = ("U1", "U2", "U3", "U4", "D4", "D3", "D2", "D1")

# 묶음 번호. 막대 개수로 정한다(계약 3절).
SEG = 1                  # 막대 1개 = 구간 경계
END = 2                  # 막대 2개 = 직선 시작·끝
HOME = 3                 # 막대 3개 이상 = 차고지

KIND_SEG = "seg"
KIND_END = "end"
KIND_HOME = "home"

_TICKS_FULL = 0x40000000
_TICKS_HALF = 0x20000000

# 조향 비율 기본값(계약 10절). config.py에서 같은 이름으로 바꾼다.
BASE_SPEED = 0.55        # 직진할 때의 좌·우 비율
SOFT_TURN = 0.18         # 한쪽 센서만 살짝 벗어났을 때의 차이
HARD_TURN = 0.42         # 선을 크게 놓쳤을 때의 차이

LOST_MS = 700            # 세 센서가 모두 흰색인 채로 이만큼 지나면 LOST
BAR_CONFIRM = 2          # 막대로 확정하려면 세 센서 모두 검정이 몇 번 연속이어야 하는지
GROUP_GAP_MS = 700       # 이보다 간격이 벌어지면 다른 묶음
SALT_MS = 600            # 살포통을 여는 시간


def ticks_diff(a, b):
    """MicroPython time.ticks_diff와 같은 부호 있는 차이(카운터 감싸기를 고려)."""
    return ((a - b + _TICKS_HALF) % _TICKS_FULL) - _TICKS_HALF


def kind_of(count):
    """막대 수 → 묶음 종류 문자열. 1=seg, 2=end, 3 이상=home."""
    if count >= HOME:
        return KIND_HOME
    if count == END:
        return KIND_END
    return KIND_SEG


def loop_index(cell):
    """칸 ID → 루프 순서 인덱스(0~7). 모르는 ID면 None."""
    for i in range(len(LOOP)):
        if LOOP[i] == cell:
            return i
    return None


# ── 조향 ────────────────────────────────────────────────────────────────
def steer(l, c, r, last_side, base=BASE_SPEED, soft=SOFT_TURN, hard=HARD_TURN):
    """센서 (L, C, R) → (좌 비율, 우 비율, 마지막으로 본 쪽).

    1 = 검정. 비율은 -1.0~1.0이고, 좌회전은 왼쪽이 느려진다(계약 10절 표 그대로).
    last_side는 마지막으로 방향을 알았던 쪽(-1 좌, 0 모름, 1 우)이다.
    """
    left = 1 if l else 0
    center = 1 if c else 0
    right = 1 if r else 0
    if left and right:                     # (1,1,1), (1,0,1): 막대를 지나는 중 → 직진
        return (base, base, last_side)
    if left and center:                    # (1,1,0): 약하게 좌회전
        return (base - soft, base + soft, -1)
    if right and center:                   # (0,1,1): 약하게 우회전(좌우 대칭)
        return (base + soft, base - soft, 1)
    if left:                               # (1,0,0): 강하게 좌회전
        return (base - hard, base + hard, -1)
    if right:                              # (0,0,1): 강하게 우회전
        return (base + hard, base - hard, 1)
    if center:                             # (0,1,0): 직진
        return (base, base, last_side)
    # (0,0,0): 마지막으로 본 쪽으로 강하게 꺾는다. 본 적이 없으면 직진하며 LOST를 기다린다.
    if last_side < 0:
        return (base - hard, base + hard, -1)
    if last_side > 0:
        return (base + hard, base - hard, 1)
    return (base, base, 0)


class Steering:
    """막대·회차에서 잠깐 선을 잃어도 마지막 방향을 기억하고, LOST_MS를 넘기면 정지 판정을 낸다."""

    def __init__(self, base=BASE_SPEED, soft=SOFT_TURN, hard=HARD_TURN, lost_ms=LOST_MS, diff=None):
        self.base = base
        self.soft = soft
        self.hard = hard
        self.lost_ms = lost_ms
        self.diff = diff or ticks_diff
        self.side = 0              # 마지막으로 본 쪽
        self.lost_since = None     # 세 센서가 모두 흰색이기 시작한 시각

    def reset(self, side=0):
        self.side = side
        self.lost_since = None

    def update(self, l, c, r, now):
        """(좌 비율, 우 비율, lost) 반환. lost가 True면 main은 모터를 세우고 LOST로 간다."""
        left, right, self.side = steer(l, c, r, self.side, self.base, self.soft, self.hard)
        if l or c or r:
            self.lost_since = None
            return (left, right, False)
        if self.lost_since is None:
            self.lost_since = now
        if self.diff(now, self.lost_since) >= self.lost_ms:
            return (0.0, 0.0, True)
        return (left, right, False)


# ── 막대 감지 ──────────────────────────────────────────────────────────
class BarDetector:
    """세 센서가 모두 검정인 상태가 confirm회 연속이면 막대 1개로 확정한다.

    셋 중 하나라도 흰색이 되기 전까지는 같은 막대로 보므로, 막대 위에 머무는 동안
    한 번만 True를 낸다.
    """

    def __init__(self, confirm=BAR_CONFIRM):
        self.confirm = confirm
        self.count = 0
        self.on_bar = False

    def reset(self):
        self.count = 0
        self.on_bar = False

    def update(self, l, c, r):
        """새 막대가 확정된 순간에만 True."""
        if not (l and c and r):
            self.count = 0
            self.on_bar = False
            return False
        if self.on_bar:
            return False
        self.count += 1
        if self.count >= self.confirm:
            self.on_bar = True
            return True
        return False


# ── 묶음 분류 ──────────────────────────────────────────────────────────
class GroupClassifier:
    """막대 사이 간격이 gap_ms 미만이면 같은 묶음이다.
    마지막 막대 뒤 gap_ms 동안 새 막대가 없으면 묶음을 확정한다(1=SEG, 2=END, 3 이상=HOME).
    """

    def __init__(self, gap_ms=GROUP_GAP_MS, diff=None):
        self.gap_ms = gap_ms
        self.diff = diff or ticks_diff
        self.count = 0
        self.last_bar = None
        self.open = False

    def reset(self):
        self.count = 0
        self.last_bar = None
        self.open = False

    def bar(self, now):
        """막대 1개 추가. tick을 빼먹어 앞 묶음의 간격이 이미 벌어졌으면 새 묶음으로 센다."""
        if self.open and self.last_bar is not None and self.diff(now, self.last_bar) >= self.gap_ms:
            self.count = 0
        self.open = True
        self.count += 1
        self.last_bar = now

    def tick(self, now):
        """묶음이 확정된 순간에만 막대 수(1, 2, 3 이상)를 돌려준다. 아니면 None."""
        if not self.open or self.last_bar is None:
            return None
        if self.diff(now, self.last_bar) < self.gap_ms:
            return None
        count = self.count
        self.open = False
        self.count = 0
        self.last_bar = None
        return count

    def pending(self):
        """지금까지 모인 막대 수(확정 전)."""
        return self.count


# ── 위치 ────────────────────────────────────────────────────────────────
class Position:
    """막대 묶음으로 지금 어느 칸에 있는지 센다(계약 3절).

    leg: 0=차고지(모름), 1=상행 직선, 2=동쪽 회차, 3=하행 직선, 4=서쪽 회차
    ends: 이번 바퀴에서 지난 END 수(1~4). END 묶음 번호 n이 곧 leg다.
    seg: 그 직선에서 지난 SEG 수(0~4)
    cell: 지금 칸 ID 또는 None(회차·차고지)
    """

    def __init__(self):
        self.reset()

    def reset(self, armed=True):
        self.leg = 0
        self.ends = 0
        self.seg = 0
        self.cell = None
        self.done = False
        self.armed = armed

    def start(self):
        """출발 준비. 막대 위에서 출발할 수 있으므로 첫 검정은 세지 않는다(arming)."""
        self.reset()
        self.armed = False

    def observe(self, l, c, r):
        """매 제어 루프에서 센서 값을 본다. 흰색을 한 번이라도 보면 무장된다."""
        if not self.armed and not (l and c and r):
            self.armed = True
        return self.armed

    def bar(self):
        """막대 1개를 셀지 결정한다. 무장 전(출발하면서 밟고 있던 막대)이면 False."""
        return self.armed

    def group(self, count):
        """확정된 묶음을 반영하고 (종류, 칸, 경고여부)를 돌려준다."""
        if not self.armed:
            return (None, self.cell, False)
        if count >= HOME:
            self.leg = 0
            self.ends = 0
            self.seg = 0
            self.cell = None
            self.done = True
            return (KIND_HOME, None, False)
        if count == END:
            # END는 어느 것이든 막대 2개다. 바퀴 안에서 몇 번째인지(n)가 다리를 정한다.
            self.ends += 1
            if self.ends > 4:
                self.ends = 1              # 서쪽 회차 END를 놓쳤다 → 다음 바퀴로 본다
            self.leg = self.ends
            self.seg = 0
            if self.leg == 1:              # 상행 직선 시작 → U1
                self.cell = "U1"
            elif self.leg == 3:            # 하행 직선 시작 → D4
                self.cell = "D4"
            else:                          # 회차 중(칸 없음)
                self.cell = None
            return (KIND_END, self.cell, False)
        # SEG: 직선 안에서 구간 번호를 하나 올린다(END에서 U1/D4로 들어왔으므로 한 칸씩 밀린다).
        self.seg += 1
        warn = False
        if self.leg == 1:
            if self.seg >= 4:
                self.seg = 4
                self.cell = "U4"
                warn = True
            else:
                self.cell = "U%d" % (self.seg + 1)
        elif self.leg == 3:
            if self.seg >= 4:
                self.seg = 4
                self.cell = "D1"
                warn = True
            else:
                self.cell = "D%d" % (4 - self.seg)
        else:
            self.cell = None               # 회차에서 본 SEG는 칸을 바꾸지 않는다
        return (KIND_SEG, self.cell, warn)

    def state(self):
        """hello 메시지의 pos 필드."""
        return {"leg": self.leg, "seg": self.seg, "cell": self.cell}


# ── 살포 ────────────────────────────────────────────────────────────────
class Salter:
    """계획에 있는 칸에 처음 들어갈 때 salt_ms 동안 열었다가 닫는다. 칸당 1회."""

    def __init__(self, salt_ms=SALT_MS, diff=None):
        self.salt_ms = salt_ms
        self.diff = diff or ticks_diff
        self.plan_id = None
        self.cells = []
        self.salted = []           # 이번 계획에서 이미 뿌린 칸(진입 순서)
        self.open_until = None     # 이 시각에 닫는다(열려 있지 않으면 None)

    def set_plan(self, plan_id, cells):
        """계획을 받는다. 계획 번호가 바뀌면 살포 이력을 새로 시작한다."""
        if plan_id != self.plan_id:
            self.salted = []
            self.open_until = None
        self.plan_id = plan_id
        self.cells = [c for c in (cells or [])]

    def enter(self, cell, now):
        """칸에 들어왔다. 지금 열어야 하면 True(그리고 닫을 시각을 기록한다)."""
        if not cell or cell in self.salted or cell not in self.cells:
            return False
        self.salted.append(cell)
        self.open_until = now + self.salt_ms
        return True

    def tick(self, now):
        """열어 둔 시간이 끝났으면 True(닫아라). 한 번만 True를 낸다."""
        if self.open_until is None:
            return False
        if self.diff(now, self.open_until) >= 0:
            self.open_until = None
            return True
        return False

    def is_open(self):
        return self.open_until is not None
