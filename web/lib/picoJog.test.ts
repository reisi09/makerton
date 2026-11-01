import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { ARROW_JOG, DEAD_MAN_MS, JOG, JOG_PROGRAM, JOG_REPEAT_MS, lastErrorLine } from "./picoJog.ts";

const PYTHON = "/usr/bin/python3";
const LETTERS = [JOG.forward, JOG.back, JOG.left, JOG.right];

// 맥의 CPython에서 조작 프로그램을 가짜 machine·select·time으로 돌린다. 시계는 가상이라 실제로 기다리지 않고,
// 모든 코일 핀의 상태가 바뀔 때마다 (시각 us, 핀 8개) 를 기록한다. 마지막에 가짜 poll이 KeyboardInterrupt를 올려 끝낸다.
const HARNESS = `
import sys, json, types
src = sys.stdin.read()
events = json.loads(sys.argv[1])
END = int(sys.argv[2])
clock = 0
pending = []
snaps = []
pins = {}
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
        global clock
        clock += 40
        snapshot()
        while events and events[0][0] <= clock:
            pending.append(events.pop(0)[1])
        if clock >= END:
            raise KeyboardInterrupt
        return [1] if pending else []
class Stdin:
    def read(self, n):
        return pending.pop(0)
def sleep_ms(n):
    global clock
    clock += n * 1000
t = types.ModuleType("time")
t.ticks_us = lambda: clock
t.ticks_ms = lambda: clock // 1000
t.ticks_diff = lambda a, b: a - b
t.ticks_add = lambda a, b: a + b
t.sleep_ms = sleep_ms
m = types.ModuleType("machine")
m.Pin = Pin
s = types.ModuleType("select")
s.poll = Poll
s.POLLIN = 1
sys.modules.update(time=t, machine=m, select=s)
sys.stdin = Stdin()
exec(compile(src, "jog", "exec"), {})
snapshot()
print(json.dumps(snaps))
`;

const FULL = [[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1], [1, 0, 0, 1]];     // 2상 풀스텝: 코일 두 개가 늘 켜져 있다
const idx = (bits: number[]) => {
  const i = FULL.findIndex((row) => row.join() === bits.join());
  assert.ok(i >= 0, `2상 풀스텝 표에 없는 코일 상태: ${bits}`);
  return i;
};
const SLOW = Number(/SLOW_US = (\d+)/.exec(JOG_PROGRAM)![1]);
const FAST = Number(/FAST_US = (\d+)/.exec(JOG_PROGRAM)![1]);

interface Step { t: number; left: number; right: number }
/** 조작 글자를 [시각 us, 글자] 목록으로 넣어 돌리고, 걸음 목록과 코일이 꺼진 시각을 돌려준다. */
function simulate(events: [number, string][], endUs: number) {
  const r = spawnSync(PYTHON, ["-c", HARNESS, JSON.stringify(events), String(endUs)], { input: JOG_PROGRAM, encoding: "utf8" });
  assert.equal(r.status, 0, `프로그램이 KeyboardInterrupt로 깔끔히 끝나야 한다\n${r.stderr}`);
  const snaps: [number, number[]][] = JSON.parse(r.stdout);
  const steps: Step[] = [];
  let offAt: number | null = null;
  for (const [t, bits] of snaps) {
    if (bits.some(Boolean)) { steps.push({ t, left: idx(bits.slice(0, 4)), right: idx(bits.slice(4)) }); offAt = null; }
    else if (offAt === null && steps.length) offAt = t;
  }
  assert.deepEqual(snaps[snaps.length - 1][1], [0, 0, 0, 0, 0, 0, 0, 0], "끝나면 코일은 모두 꺼져 있어야 한다");
  return { steps, offAt };
}
const held = (letter: string, fromMs: number, toMs: number): [number, string][] => {
  const out: [number, string][] = [];
  for (let ms = fromMs; ms <= toMs; ms += JOG_REPEAT_MS) out.push([ms * 1000, letter]);
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

test("프로그램의 조작 글자·데드맨 시간이 웹 상수와 같다", () => {
  const moves = /MOVES = \{(.*)\}/.exec(JOG_PROGRAM)![1];
  assert.deepEqual([...moves.matchAll(/"(.)":/g)].map((m) => m[1]), LETTERS);
  assert.ok(JOG_PROGRAM.includes(`c == "${JOG.stop}"`));
  assert.equal(Number(/DEAD_MS = (\d+)/.exec(JOG_PROGRAM)![1]), DEAD_MAN_MS);
  assert.ok(JOG_REPEAT_MS * 2 <= DEAD_MAN_MS, "글자 한 번이 늦어도 차가 멈추지 않아야 한다");
  assert.deepEqual(Object.values(ARROW_JOG).sort(), [...LETTERS].sort());
});

test("글자마다 두 바퀴가 맞는 방향으로 한 걸음씩 돈다(오른쪽은 배선상 반전), 모르는 글자는 무시한다", () => {
  const want: Record<string, number[]> = { [JOG.forward]: [1, -1], [JOG.back]: [-1, 1], [JOG.left]: [-1, -1], [JOG.right]: [1, 1] };
  for (const letter of LETTERS) {
    const { steps } = simulate(held(letter, 0, 200), 1_000_000);
    assert.ok(steps.length > 100, `${letter}: 걸음이 너무 적다 ${steps.length}`);
    for (const d of deltas(steps)) assert.deepEqual(d, want[letter], `${letter}: 바퀴 회전 방향`);
  }
  const { steps } = simulate([[0, "X"], [100_000, "f"], [200_000, "\r"]], 1_000_000);
  assert.equal(steps.length, 0);
});

test("출발 간격은 SLOW_US에서 FAST_US 쪽으로 줄어들고, 조작 글자가 끊기면 데드맨 시간 뒤 코일이 꺼진다", () => {
  const { steps, offAt } = simulate(held(JOG.forward, 0, 900), 2_500_000);
  const gaps = steps.slice(1).map((s, i) => s.t - steps[i].t);
  assert.ok(FAST > 1500 && SLOW > FAST, "힘을 위해 느리게 민다");
  assert.ok(Math.abs(gaps[0] - SLOW) <= 50, `첫 간격 ${gaps[0]}`);
  assert.ok(gaps.every((g) => g >= FAST - 50), "FAST_US보다 빨리 걸으면 안 된다");
  assert.ok(gaps[gaps.length - 1] < gaps[0] - 150, `간격이 줄어야 한다 ${gaps[0]} -> ${gaps[gaps.length - 1]}`);
  const lastLetterUs = 900_000;
  assert.ok(offAt !== null && offAt >= lastLetterUs + DEAD_MAN_MS * 1000 - 20_000 && offAt <= lastLetterUs + DEAD_MAN_MS * 1000 + 100_000, `꺼진 시각 ${offAt}`);
  assert.ok(steps[steps.length - 1].t < offAt!, "꺼진 뒤에는 걸음이 없다");
});

test("S는 즉시 서고, 방향이 바뀌면 간격이 다시 SLOW_US에서 시작한다", () => {
  const stopped = simulate([...held(JOG.forward, 0, 200), [300_000, JOG.stop]], 1_500_000);
  assert.ok(stopped.offAt !== null && stopped.offAt < 330_000, `S 뒤 꺼진 시각 ${stopped.offAt}`);

  const { steps } = simulate([...held(JOG.forward, 0, 1500), ...held(JOG.back, 1600, 1800)], 3_000_000);
  const d = deltas(steps);
  const k = d.findIndex((x) => x[0] === -1);                    // 후진 첫 걸음
  assert.ok(k > 0);
  assert.ok(steps[k - 1].t - steps[k - 2].t < SLOW - 300, "전진이 충분히 빨라진 뒤여야 시험이 의미 있다");
  assert.ok(Math.abs(steps[k + 1].t - steps[k].t - SLOW) <= 50, "방향이 바뀐 뒤 첫 간격");
});

test("lastErrorLine은 마지막 Traceback의 오류 줄만 뽑는다", () => {
  const raw = "OK\x04Traceback (most recent call last):\r\n  File \"<stdin>\", line 5, in <module>\r\nNameError: name 'x' isn't defined\r\n\x04>";
  assert.equal(lastErrorLine(raw), "NameError: name 'x' isn't defined");
  assert.equal(lastErrorLine("raw REPL; CTRL-B to exit\r\n>"), null);
  assert.equal(lastErrorLine("Traceback (most recent call last):\r\nKeyboardInterrupt: \r\nTraceback (most recent call last):\r\nOSError: [Errno 19] ENODEV\r\n"), "OSError: [Errno 19] ENODEV");
});
