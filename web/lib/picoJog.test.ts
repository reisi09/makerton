import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { ARROW_JOG, DEAD_MAN_MS, IDLE_RESET_MS, JOG, JOG_PROGRAM, JOG_REPEAT_MS, KEEPALIVE, KEEPALIVE_MS, lastErrorLine } from "./picoJog.ts";

const PYTHON = "/usr/bin/python3";
const LETTERS = [JOG.forward, JOG.back, JOG.left, JOG.right];

// 맥의 CPython에서 조작 프로그램을 가짜 machine·select·time으로 돌린다. 시계는 가상이라 실제로 기다리지 않고,
// 모든 코일 핀의 상태가 바뀔 때마다 (시각 us, 핀 8개) 를 기록한다. 마지막에 가짜 poll이 KeyboardInterrupt를 올려 끝낸다.
// machine.reset()은 그때의 시각·핀을 남기고 프로그램을 끝낸다. Ctrl-C(chr 3)는 MicroPython처럼 받은 글자를 비우고
// KeyboardInterrupt를 예약하는데, 최악의 경우를 흉내 내 그 뒤 글자 하나를 읽을 틈을 준 다음 poll·sleep에서 올린다.
const HARNESS = `
import sys, json, types
src = sys.stdin.read()
events = json.loads(sys.argv[1])
END = int(sys.argv[2])
clock = 0
pending = []
snaps = []
pins = {}
resets = []
interrupt = False
class Reset(BaseException):
    pass
def reset():
    resets.append([clock, [pins[n].v for n in (6, 7, 8, 9, 2, 3, 4, 5)]])
    raise Reset
class Pin:
    OUT = 1
    def __init__(self, n, mode=None, value=0):
        self.v = value
        pins[n] = self
    def value(self, v=None):
        if v is None:
            return self.v
        self.v = int(v)
def snapshot():
    st = [pins[n].v for n in (6, 7, 8, 9, 2, 3, 4, 5)]
    if not snaps or snaps[-1][1] != st:
        snaps.append([clock, st])
class Poll:
    def register(self, f, m):
        pass
    def poll(self, timeout):
        global clock, interrupt
        if interrupt:
            raise KeyboardInterrupt
        clock += 40
        snapshot()
        while events and events[0][0] <= clock:
            for ch in events.pop(0)[1]:
                if ch == chr(3):
                    pending.clear()
                    interrupt = True
                else:
                    pending.append(ch)
        if clock >= END:
            raise KeyboardInterrupt
        return [1] if pending else []
class Stdin:
    def read(self, n):
        return pending.pop(0)
def sleep_ms(n):
    global clock
    if interrupt:
        raise KeyboardInterrupt
    clock += n * 1000
t = types.ModuleType("time")
t.ticks_us = lambda: clock
t.ticks_ms = lambda: clock // 1000
t.ticks_diff = lambda a, b: a - b
t.ticks_add = lambda a, b: a + b
t.sleep_ms = sleep_ms
m = types.ModuleType("machine")
m.Pin = Pin
m.reset = reset
s = types.ModuleType("select")
s.poll = Poll
s.POLLIN = 1
sys.modules.update(time=t, machine=m, select=s)
sys.stdin = Stdin()
try:
    exec(compile(src, "jog", "exec"), {})
except Reset:
    pass
snapshot()
print(json.dumps({"snaps": snaps, "resets": resets}))
`;

const FULL = [[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1], [1, 0, 0, 1]];     // 2상 풀스텝: 코일 두 개가 늘 켜져 있다
const idx = (bits: number[]) => {
  const i = FULL.findIndex((row) => row.join() === bits.join());
  assert.ok(i >= 0, `2상 풀스텝 표에 없는 코일 상태: ${bits}`);
  return i;
};
const constant = (name: string) => Number(new RegExp(`^${name} = (\\d+)$`, "m").exec(JOG_PROGRAM)![1]);
const SLOW = constant("SLOW_US");
const FAST = constant("FAST_US");
const RAMP = constant("RAMP_STEPS");
/** 출발(또는 방향 전환) 뒤 k번째 걸음 다음의 간격. 프로그램과 같은 식이다. */
const gapAt = (k: number) => SLOW - Math.floor(((SLOW - FAST) * Math.min(k, RAMP)) / RAMP);
let rampUs = 0;
for (let k = 0; k < RAMP; k++) rampUs += gapAt(k);
/** 가속을 다 마치고 조금 더 달리는 데 필요한, 누르고 있는 시간(ms, 글자 반복 간격 단위) */
const PAST_RAMP_MS = Math.ceil(rampUs / 1000 / JOG_REPEAT_MS) * JOG_REPEAT_MS + 200;
const OFF = [0, 0, 0, 0, 0, 0, 0, 0];

interface Step { t: number; left: number; right: number }
/** 조작 글자를 [시각 us, 글자들] 목록으로 넣어 돌리고, 걸음 목록·코일이 꺼진 시각·reset() 기록을 돌려준다. */
function simulate(events: [number, string][], endUs: number) {
  const r = spawnSync(PYTHON, ["-c", HARNESS, JSON.stringify(events), String(endUs)], { input: JOG_PROGRAM, encoding: "utf8" });
  assert.equal(r.status, 0, `프로그램이 KeyboardInterrupt나 reset()으로 깔끔히 끝나야 한다\n${r.stderr}`);
  const { snaps, resets }: { snaps: [number, number[]][]; resets: [number, number[]][] } = JSON.parse(r.stdout);
  const steps: Step[] = [];
  let offAt: number | null = null;
  for (const [t, bits] of snaps) {
    if (bits.some(Boolean)) { steps.push({ t, left: idx(bits.slice(0, 4)), right: idx(bits.slice(4)) }); offAt = null; }
    else if (offAt === null && steps.length) offAt = t;
  }
  assert.deepEqual(snaps[snaps.length - 1][1], OFF, "끝나면 코일은 모두 꺼져 있어야 한다");
  return { steps, offAt, resets };
}
const held = (letter: string, fromMs: number, toMs: number, everyMs = JOG_REPEAT_MS): [number, string][] => {
  const out: [number, string][] = [];
  for (let ms = fromMs; ms <= toMs; ms += everyMs) out.push([ms * 1000, letter]);
  return out;
};
// 걸음마다 (왼쪽, 오른쪽) 바늘이 얼마나 움직였는지. 첫 걸음은 바늘 0(표의 첫 줄)에서 시작한 것으로 본다.
const deltas = (steps: Step[]) => steps.map((s, i) => {
  const p = i ? steps[i - 1] : { left: 0, right: 0 };
  const d = (a: number, b: number) => { const x = (a - b + 4) % 4; return x === 1 ? 1 : x === 3 ? -1 : NaN; };
  return [d(s.left, p.left), d(s.right, p.right)];
});

test("조작 프로그램은 파이썬으로 컴파일된다", () => {
  const r = spawnSync(PYTHON, ["-c", "import sys; compile(sys.stdin.read(), 'jog', 'exec')"], { input: JOG_PROGRAM, encoding: "utf8" });
  assert.equal(r.status, 0, r.stderr);
});

test("프로그램은 ASCII 글자와 줄바꿈만 쓴다(Ctrl-D 같은 제어 문자가 끼면 올리다 실행돼 버린다)", () => {
  assert.match(JOG_PROGRAM, /^[\x20-\x7e\n]+$/);
});

test("프로그램의 조작 글자·데드맨·유휴 리셋 시간이 웹 상수와 같다", () => {
  const moves = /MOVES = \{(.*)\}/.exec(JOG_PROGRAM)![1];
  assert.deepEqual([...moves.matchAll(/"(.)":/g)].map((m) => m[1]), LETTERS);
  assert.ok(JOG_PROGRAM.includes(`c == "${JOG.stop}"`));
  assert.equal(constant("DEAD_MS"), DEAD_MAN_MS);
  assert.ok(JOG_REPEAT_MS * 2 <= DEAD_MAN_MS, "글자 한 번이 늦어도 차가 멈추지 않아야 한다");
  assert.deepEqual(Object.values(ARROW_JOG).sort(), [...LETTERS].sort());
  assert.equal(constant("IDLE_MS"), IDLE_RESET_MS);
  assert.ok(KEEPALIVE_MS * 3 <= IDLE_RESET_MS, "유지 글자가 두 번 늦어도 Pico가 다시 켜지지 않아야 한다");
  assert.ok(![...LETTERS, JOG.stop].includes(KEEPALIVE as never), "유지 글자는 조작 글자와 달라야 한다");
});

test("글자마다 두 바퀴가 맞는 방향으로 한 걸음씩 돈다(오른쪽은 배선상 반전), 모르는 글자는 무시한다", () => {
  const want: Record<string, number[]> = { [JOG.forward]: [1, -1], [JOG.back]: [-1, 1], [JOG.left]: [-1, -1], [JOG.right]: [1, 1] };
  const atLeast = Math.floor(((200 + DEAD_MAN_MS) * 1000) / SLOW);     // 누른 200ms + 데드맨 동안 가장 느린 간격으로 걸어도 이만큼
  for (const letter of LETTERS) {
    const { steps } = simulate(held(letter, 0, 200), 1_000_000);
    assert.ok(steps.length >= atLeast, `${letter}: 걸음이 너무 적다 ${steps.length} < ${atLeast}`);
    for (const d of deltas(steps)) assert.deepEqual(d, want[letter], `${letter}: 바퀴 회전 방향`);
  }
  const { steps } = simulate([[0, "X"], [100_000, "f"], [200_000, "\r"]], 1_000_000);
  assert.equal(steps.length, 0);
});

test("출발 간격은 SLOW_US에서 RAMP_STEPS 걸음 동안 FAST_US까지 줄어들고, 조작 글자가 끊기면 데드맨 시간 뒤 코일이 꺼진다", () => {
  assert.ok(FAST >= 4000 && SLOW > FAST, "힘을 최대로: 28BYJ-48은 느리게 밀수록 토크가 크다");
  const lastLetterMs = PAST_RAMP_MS;
  const { steps, offAt } = simulate(held(JOG.forward, 0, lastLetterMs), (lastLetterMs + 1000) * 1000);
  const gaps = steps.slice(1).map((s, i) => s.t - steps[i].t);
  assert.ok(gaps.length > RAMP + 10, `가속을 다 볼 만큼 걸어야 한다 ${gaps.length}`);
  // 가짜 poll은 한 번에 40us씩 시계를 돌리고 글자가 온 루프에서는 두 번 불리므로 잰 간격은 최대 80us 어긋난다
  gaps.forEach((g, k) => assert.ok(Math.abs(g - gapAt(k)) <= 100, `${k}번째 간격 ${g}, 기대 ${gapAt(k)}`));
  assert.equal(gapAt(RAMP), FAST);
  const lastLetterUs = lastLetterMs * 1000;
  assert.ok(offAt !== null && offAt >= lastLetterUs + DEAD_MAN_MS * 1000 - 20_000 && offAt <= lastLetterUs + DEAD_MAN_MS * 1000 + 100_000, `꺼진 시각 ${offAt}`);
  assert.ok(steps[steps.length - 1].t < offAt!, "꺼진 뒤에는 걸음이 없다");
});

test("S는 즉시 서고, 방향이 바뀌면 간격이 다시 SLOW_US에서 시작한다", () => {
  const stopped = simulate([...held(JOG.forward, 0, 200), [300_000, JOG.stop]], 1_500_000);
  assert.ok(stopped.offAt !== null && stopped.offAt < 330_000, `S 뒤 꺼진 시각 ${stopped.offAt}`);

  const { steps } = simulate([...held(JOG.forward, 0, PAST_RAMP_MS), ...held(JOG.back, PAST_RAMP_MS + 100, PAST_RAMP_MS + 300)],
    (PAST_RAMP_MS + 1500) * 1000);
  const d = deltas(steps);
  const k = d.findIndex((x) => x[0] === -1);                    // 후진 첫 걸음
  assert.ok(k > 0);
  assert.ok(steps[k - 1].t - steps[k - 2].t <= FAST + 100, "전진이 FAST_US까지 빨라진 뒤여야 시험이 의미 있다");
  assert.ok(Math.abs(steps[k + 1].t - steps[k].t - SLOW) <= 100, "방향이 바뀐 뒤 첫 간격");
});

test("유지 글자 K는 바퀴를 움직이지 않고 데드맨도 늘리지 않으며, 계속 오면 Pico를 다시 켜지 않는다", () => {
  const alone = simulate(held(KEEPALIVE, 0, 1000, 50), 1_200_000);
  assert.equal(alone.steps.length, 0);
  const endMs = IDLE_RESET_MS + 3 * KEEPALIVE_MS;
  const { steps, offAt, resets } = simulate([...held(JOG.forward, 0, 200), [250_000, KEEPALIVE], [400_000, KEEPALIVE],
    ...held(KEEPALIVE, KEEPALIVE_MS, endMs, KEEPALIVE_MS)], endMs * 1000 + 500_000);
  assert.ok(offAt !== null && offAt <= (200 + DEAD_MAN_MS) * 1000 + 20_000, `K가 와도 데드맨대로 서야 한다: 꺼진 시각 ${offAt}`);
  assert.ok(steps[steps.length - 1].t < offAt!);
  assert.deepEqual(resets, [], "유지 글자가 오는 동안에는 다시 켜지 않는다");
});

test("글자가 IDLE_MS 동안 하나도 없으면(탭을 닫음·새로 고침) 코일을 끈 뒤 Pico를 다시 켠다", () => {
  const { resets } = simulate(held(JOG.forward, 0, 200), (IDLE_RESET_MS + 5000) * 1000);
  assert.equal(resets.length, 1);
  const [at, pins] = resets[0];
  assert.ok(at > (200 + IDLE_RESET_MS) * 1000 && at <= (200 + IDLE_RESET_MS) * 1000 + 5_000, `다시 켠 시각 ${at}`);
  assert.deepEqual(pins, OFF, "다시 켜기 전에 코일을 끈다");
});

test("닫히는 탭이 한 번에 보낸 Ctrl-C·B·D에서 Ctrl-B를 먹으면 Pico를 다시 켜고, 따로 온 Ctrl-C로는 조용히 끝난다", () => {
  const race = simulate([...held(JOG.forward, 0, 200), [250_000, "\x03\x02\x04"]], 2_000_000);
  assert.equal(race.resets.length, 1, "남은 Ctrl-D는 raw REPL에서 소프트 리셋만 해 main.py가 안 돈다");
  assert.deepEqual(race.resets[0][1], OFF);
  const normal = simulate([...held(JOG.forward, 0, 200), [250_000, "\x03"], [350_000, "\x02"], [450_000, "\x04"]], 2_000_000);
  assert.deepEqual(normal.resets, [], "연결 해제(Ctrl 문자 사이 간격)는 raw REPL이 Ctrl-B·D를 받아 main.py로 돌아간다");
  assert.ok(normal.offAt !== null && normal.offAt < 260_000, `Ctrl-C 뒤 꺼진 시각 ${normal.offAt}`);
});

test("lastErrorLine은 마지막 Traceback의 오류 줄만 뽑는다", () => {
  const raw = "OK\x04Traceback (most recent call last):\r\n  File \"<stdin>\", line 5, in <module>\r\nNameError: name 'x' isn't defined\r\n\x04>";
  assert.equal(lastErrorLine(raw), "NameError: name 'x' isn't defined");
  assert.equal(lastErrorLine("raw REPL; CTRL-B to exit\r\n>"), null);
  assert.equal(lastErrorLine("Traceback (most recent call last):\r\nKeyboardInterrupt: \r\nTraceback (most recent call last):\r\nOSError: [Errno 19] ENODEV\r\n"), "OSError: [Errno 19] ENODEV");
});
