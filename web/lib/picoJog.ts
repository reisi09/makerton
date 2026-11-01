// Pico를 웹에서 USB(Web Serial)로 직접 움직이는 수동 조작: 웹과 Pico가 약속한 값과 Pico에 올릴 프로그램.
// 프로그램은 raw REPL로 올려 실행한다. Ctrl 문자가 끼면 안 되므로 ASCII만 쓴다(테스트가 확인한다).

export const PICO_USB_VENDOR_ID = 0x2e8a;   // Raspberry Pi
export const BAUD_RATE = 115200;

/** 조작 글자. 프로그램의 MOVES 키와 정지 글자가 이것과 같아야 한다(테스트가 비교한다). */
export const JOG = { forward: "F", back: "B", left: "L", right: "R", stop: "S" } as const;
export type JogLetter = (typeof JOG)[keyof typeof JOG];
export const ARROW_JOG: Record<string, JogLetter> = { ArrowUp: JOG.forward, ArrowDown: JOG.back, ArrowLeft: JOG.left, ArrowRight: JOG.right };

/** MicroPython REPL 제어 문자 */
export const CTRL_A = 0x01;   // raw REPL로 들어간다
export const CTRL_B = 0x02;   // raw REPL에서 나온다
export const CTRL_C = 0x03;   // 돌고 있는 프로그램을 끊는다
export const CTRL_D = 0x04;   // raw REPL에서는 실행, 일반 REPL에서는 소프트 리셋(main.py 다시 시작)

export const JOG_REPEAT_MS = 100;         // 누르고 있는 동안 같은 글자를 다시 보내는 간격
export const DEAD_MAN_MS = 300;           // 프로그램이 이 시간 동안 조작 글자를 못 받으면 스스로 선다
export const CTRL_GAP_MS = 100;           // Ctrl-C 사이, 그리고 종료 때 Ctrl 문자 사이의 간격(프로그램이 끝날 시간을 준다)
export const BANNER_WAIT_MS = 300;        // Ctrl-A 뒤 raw REPL 안내문을 기다리는 시간(안 오면 그냥 진행)
export const OK_WAIT_MS = 2000;           // Ctrl-D 뒤 raw REPL이 'OK'를 보내길 기다리는 시간
export const START_CHECK_MS = 200;        // 'OK' 뒤 이 시간 안에 Traceback이 없어야 실행 중으로 본다
export const TRACEBACK_SETTLE_MS = 150;   // Traceback이 보이면 나머지 줄이 도착하길 기다리는 시간
export const WRITE_CHUNK = 256;           // 프로그램 글을 이만큼씩 나눠 보낸다(mpremote와 같은 값)
export const WRITE_CHUNK_GAP_MS = 10;

/**
 * Pico에서 도는 수동 조작 프로그램.
 * - 현재 배선: 왼쪽 6,7,8,9번은 그대로, 오른쪽 2,3,4,5번은 마주 보게 달려 뒤집는다(Pico에 올라간 config는 옛 값이라 쓰지 않는다).
 * - F·B·L·R이 오면 그 방향으로 가고, S가 오거나 DEAD_MS 동안 조작 글자가 없으면 서며 코일을 모두 끈다.
 * - 2상 풀스텝으로 민다: 걸음마다 코일 두 개가 늘 켜져 있어 하프스텝보다 힘이 세다(모터당 약 200mA, 맥 USB로 충분하다).
 *   2026-11-01 사용자 요청 '좀 느려도 되니 힘을 세게': 초당 약 23mm(하프스텝 0.6ms의 초당 38mm보다 느리다).
 * - 출발하거나 방향이 바뀌면 간격을 SLOW_US에서 시작해 RAMP_STEPS 걸음 동안 FAST_US까지 줄인다(부하가 걸린 채 빠르게 출발하면 탈조한다).
 * - Ctrl-C(KeyboardInterrupt)로 코일을 끄고 조용히 끝난다.
 */
export const JOG_PROGRAM = `import sys, time, select
from machine import Pin

LEFT = [Pin(n, Pin.OUT, value=0) for n in (6, 7, 8, 9)]
RIGHT = [Pin(n, Pin.OUT, value=0) for n in (2, 3, 4, 5)]
LEFT_SIGN = 1
RIGHT_SIGN = -1
FULL = ((1, 1, 0, 0), (0, 1, 1, 0), (0, 0, 1, 1), (1, 0, 0, 1))
MOVES = {"F": (1, 1), "B": (-1, -1), "L": (-1, 1), "R": (1, -1)}
DEAD_MS = 300
SLOW_US = 3200
FAST_US = 2000
RAMP_STEPS = 600

poll = select.poll()
poll.register(sys.stdin, select.POLLIN)

def coils(pins, i):
    row = FULL[i % 4]
    for k in range(4):
        pins[k].value(row[k])

def off():
    for p in LEFT + RIGHT:
        p.value(0)

move = None
li = ri = steps = 0
heard = next_us = 0
try:
    while True:
        while poll.poll(0):
            c = sys.stdin.read(1)
            if c in MOVES:
                if MOVES[c] != move:
                    steps = 0
                    next_us = time.ticks_us()
                move = MOVES[c]
                heard = time.ticks_ms()
            elif c == "S":
                move = None
                off()
        if move is not None and time.ticks_diff(time.ticks_ms(), heard) > DEAD_MS:
            move = None
            off()
        if move is None:
            time.sleep_ms(1)
            continue
        now = time.ticks_us()
        if time.ticks_diff(now, next_us) >= 0:
            li += move[0] * LEFT_SIGN
            ri += move[1] * RIGHT_SIGN
            coils(LEFT, li)
            coils(RIGHT, ri)
            gap = SLOW_US - (SLOW_US - FAST_US) * min(steps, RAMP_STEPS) // RAMP_STEPS
            steps += 1
            next_us = time.ticks_add(next_us, gap)
            if time.ticks_diff(now, next_us) > gap:
                next_us = time.ticks_add(now, gap)
except KeyboardInterrupt:
    pass
finally:
    off()
`;

/** MicroPython이 보낸 글에서 마지막 Traceback의 오류 줄(예: "NameError: ...")만 뽑는다. Traceback이 없으면 null. */
export function lastErrorLine(text: string): string | null {
  const at = text.lastIndexOf("Traceback");
  if (at < 0) return null;
  const lines = text.slice(at)
    .replace(/[\x00-\x09\x0b\x0c\x0e-\x1f]/g, "")        // raw REPL이 끝에 붙이는 Ctrl-D 같은 제어 문자
    .split(/\r?\n/).map((l) => l.trim()).filter((l) => l && l !== ">" && l !== ">>>");
  return lines.length ? lines[lines.length - 1] : null;
}
