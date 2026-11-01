"use client";

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import {
  ARROW_JOG, BANNER_WAIT_MS, BAUD_RATE, CTRL_A, CTRL_B, CTRL_C, CTRL_D, CTRL_GAP_MS, JOG, JOG_PROGRAM, JOG_REPEAT_MS, OK_WAIT_MS,
  PICO_USB_VENDOR_ID, START_CHECK_MS, TRACEBACK_SETTLE_MS, WRITE_CHUNK, WRITE_CHUNK_GAP_MS, lastErrorLine, type JogLetter,
} from "@/lib/picoJog";
import css from "./PicoPad.module.css";

// Web Serial은 TS lib.dom에 없어서 쓰는 만큼만 선언한다.
interface SerialPort extends EventTarget {
  readable: ReadableStream<Uint8Array> | null;
  writable: WritableStream<Uint8Array> | null;
  open(options: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
  getInfo(): { usbVendorId?: number; usbProductId?: number };
}
interface Serial extends EventTarget {
  getPorts(): Promise<SerialPort[]>;
  requestPort(options?: { filters?: { usbVendorId?: number }[] }): Promise<SerialPort>;
}

type Phase = "idle" | "connecting" | "running" | "closing";
interface Session {
  port: SerialPort;
  writer: WritableStreamDefaultWriter<Uint8Array>;
  reader: ReadableStreamDefaultReader<Uint8Array>;
  reading: Promise<void>;     // 읽기 루프. 끝나야 reader 잠금을 풀 수 있다
  text: string;               // Pico가 보낸 글 전부(조작 프로그램은 평소 아무것도 안 찍는다)
  mark: number;               // 조작 프로그램을 올리기 시작한 위치. 이 뒤의 Traceback만 오류로 본다(-1이면 아직)
  failing: boolean;           // Traceback을 봤고 정리 대기 중
  closing: boolean;           // 끝내는 중이거나 끝났다. 이 뒤로는 아무것도 보내지 않는다
}

const JOG_PAD = [[JOG.forward, "↑", "앞으로"], [JOG.left, "↺", "왼쪽 돌기"], [JOG.stop, "■", "정지"], [JOG.right, "↻", "오른쪽 돌기"], [JOG.back, "↓", "뒤로"]] as const;
const KEY_CLASS = { F: css.keyF, L: css.keyL, S: css.keyS, R: css.keyR, B: css.keyB } as const;
const MAX_TEXT = 100_000;       // ponytail: 조작 프로그램이 폭주해도 메모리가 늘지 않게 자른다(오류는 앞쪽에 있다)

const getSerial = () => (navigator as Navigator & { serial?: Serial }).serial;
const isPico = (p: SerialPort) => p.getInfo().usbVendorId === PICO_USB_VENDOR_ID;
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const put = (s: Session, ...bytes: number[]) => s.writer.write(new Uint8Array(bytes));
// 화살표 키를 글자 입력에 쓰는 칸에서는 가로채지 않는다
const isTyping = (t: EventTarget | null) => t instanceof HTMLElement && !!t.closest("textarea, select, input:not([type=checkbox], [type=radio]), [contenteditable]");

async function waitFor(s: Session, needle: string, from: number, ms: number) {
  const end = performance.now() + ms;
  while (performance.now() < end && !s.text.includes(needle, from)) await sleep(10);
  return s.text.includes(needle, from);
}

// Pico가 보낸 글을 계속 비운다. Traceback이 보이면 나머지 줄이 올 때까지 잠깐 기다렸다가 onFail로 알린다.
async function drain(s: Session, onFail: (why: string) => void) {
  const decoder = new TextDecoder();
  try {
    for (;;) {
      const { value, done } = await s.reader.read();
      if (done) break;
      if (s.text.length < MAX_TEXT) s.text += decoder.decode(value, { stream: true });
      if (!s.closing && !s.failing && s.mark >= 0 && s.text.indexOf("Traceback", s.mark) >= 0) {
        s.failing = true;
        setTimeout(() => onFail(`Pico 오류: ${lastErrorLine(s.text.slice(s.mark)) ?? "Traceback"}`), TRACEBACK_SETTLE_MS);
      }
    }
  } catch { /* USB를 뽑으면 읽기가 실패한다 */ }
  if (!s.closing) onFail("Pico와 연결이 끊겼습니다.");
}

// raw REPL로 들어가 조작 프로그램을 올려 실행한다. 문제가 있으면 사용자에게 보일 글을, 잘 시작했으면 null을 돌려준다.
async function startJog(s: Session): Promise<string | null> {
  await put(s, CTRL_C);                        // 차의 main.py를 끊는다
  await sleep(CTRL_GAP_MS);
  await put(s, CTRL_C);                        // REPL 프롬프트가 깨끗하게 나오도록 한 번 더
  await sleep(CTRL_GAP_MS);
  const from = s.text.length;
  await put(s, CTRL_A);                        // raw REPL
  const banner = await waitFor(s, "raw REPL", from, BANNER_WAIT_MS);
  s.mark = banner ? s.text.indexOf("raw REPL", from) : s.text.length;   // 앞의 KeyboardInterrupt 글은 오류로 보지 않는다
  const bytes = new TextEncoder().encode(JOG_PROGRAM);
  for (let i = 0; i < bytes.length; i += WRITE_CHUNK) {
    await s.writer.write(bytes.slice(i, i + WRITE_CHUNK));
    await sleep(WRITE_CHUNK_GAP_MS);
  }
  await put(s, CTRL_D);                        // 실행
  if (!(await waitFor(s, "OK", s.mark, OK_WAIT_MS))) return "Pico가 MicroPython 조작 모드에 들어가지 않았습니다. USB를 다시 꽂고 한 번 더 눌러 주세요.";
  await sleep(START_CHECK_MS);                 // 문법·배선 오류는 'OK' 직후에 Traceback으로 온다
  return null;
}

// 조작 프로그램을 끊고(Ctrl-C) raw REPL을 나와(Ctrl-B) 소프트 리셋(Ctrl-D)해 차의 main.py를 되살린 뒤 포트를 닫는다.
// Ctrl 문자 사이에 간격을 두는 까닭: Ctrl-C는 프로그램이 끝나야 처리되는데, 그 전에 Ctrl-B·D가 도착하면 조작 프로그램이 일반 글자로 먹어 버린다.
async function endSession(s: Session) {
  s.closing = true;
  try {
    for (const byte of [CTRL_C, CTRL_B, CTRL_D]) {
      await put(s, byte);
      await sleep(CTRL_GAP_MS);
    }
  } catch { /* 이미 뽑힌 장치 */ }
  try { await s.reader.cancel(); } catch { /* 이미 닫힘 */ }
  await s.reading;
  try { s.reader.releaseLock(); } catch { /* 이미 풀림 */ }
  try { s.writer.releaseLock(); } catch { /* 이미 풀림 */ }
  try { await s.port.close(); } catch { /* 이미 닫힘 */ }
}

export default function PicoPad() {
  const [support, setSupport] = useState<"checking" | "yes" | "no">("checking");   // 서버 렌더와 맞추려고 마운트 뒤에 판단한다
  const [ports, setPorts] = useState<SerialPort[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [held, setHeld] = useState<JogLetter | null>(null);
  const [error, setError] = useState("");
  const session = useRef<Session | null>(null);
  const timer = useRef<number | null>(null);
  const dir = useRef<JogLetter | null>(null);

  // 감지: 이미 허용한 Pico 목록을 읽고, 꽂고 뽑을 때마다 다시 읽는다. 허용 전의 Pico는 브라우저가 알려 주지 않는다.
  useEffect(() => {
    const serial = getSerial();
    setSupport(serial ? "yes" : "no");
    if (!serial) return;
    let alive = true;
    const refresh = () => serial.getPorts().then((all) => { if (alive) setPorts(all.filter(isPico)); }).catch(() => {});
    refresh();
    serial.addEventListener("connect", refresh);
    serial.addEventListener("disconnect", refresh);
    return () => { alive = false; serial.removeEventListener("connect", refresh); serial.removeEventListener("disconnect", refresh); };
  }, []);

  // 화면이 사라지면 Pico를 원래대로 돌려 놓는다
  useEffect(() => () => {
    const s = session.current;
    if (s && !s.closing) void endSession(s);
  }, []);

  // 누르고 있는 동안 JOG_REPEAT_MS마다 같은 글자를 보내고, 떼면 S를 보낸다. 프로그램은 DEAD_MAN_MS 동안 못 받으면 스스로 선다.
  const send = (letter: JogLetter) => {
    const s = session.current;
    if (s && !s.closing) put(s, letter.charCodeAt(0)).catch(() => {});   // 쓰기가 실패하면 읽기 루프가 끊김을 알린다
  };
  const release = (only?: JogLetter) => {
    if (only && only !== dir.current) return;
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
    dir.current = null;
    setHeld(null);
    send(JOG.stop);
  };
  const hold = (letter: JogLetter) => {
    if (dir.current === letter) return;
    if (timer.current !== null) window.clearInterval(timer.current);
    dir.current = letter;
    setHeld(letter);
    send(letter);
    timer.current = window.setInterval(() => send(letter), JOG_REPEAT_MS);
  };

  useEffect(() => {
    if (phase !== "running") return;
    const down = (e: KeyboardEvent) => {
      const d = ARROW_JOG[e.key];
      if (!d || e.repeat || e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      e.preventDefault();
      hold(d);
    };
    const up = (e: KeyboardEvent) => { const d = ARROW_JOG[e.key]; if (d) release(d); };
    const stop = () => release();
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", stop);
    document.addEventListener("visibilitychange", stop);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", stop);
      document.removeEventListener("visibilitychange", stop);
      release();               // 끊기거나 연결을 해제하면 누르던 것도 멈춘다
    };
  }, [phase]);

  async function close(s: Session, message = "") {
    if (s.closing) return;
    s.closing = true;          // release()가 이미 닫히는 세션으로 S를 보내지 않게 먼저 표시한다
    release();
    setPhase("closing");
    setError(message);
    await endSession(s);
    if (session.current === s) session.current = null;
    setPhase("idle");
  }

  // 처음에는 requestPort(사용자 클릭 안에서 바로 불러야 한다), 한 번 허용한 뒤에는 목록의 포트를 바로 연다.
  async function connect() {
    const serial = getSerial();
    if (!serial || phase !== "idle") return;
    setError("");
    setPhase("connecting");
    let port: SerialPort | undefined = ports[0];
    try {
      port ??= await serial.requestPort({ filters: [{ usbVendorId: PICO_USB_VENDOR_ID }] });
    } catch (e) {
      setPhase("idle");
      if ((e as DOMException).name !== "NotFoundError") setError("Pico를 고르지 못했습니다. 크롬이나 엣지의 장치 선택 창에서 Pico를 골라 주세요.");   // NotFoundError = 사용자가 창을 닫음
      return;
    }
    const chosen = port;
    setPorts((p) => (p.includes(chosen) ? p : [...p, chosen]));
    try {
      await chosen.open({ baudRate: BAUD_RATE });
    } catch {
      setPhase("idle");
      setError("포트를 열지 못했습니다. Thonny·mpremote·screen 같은 프로그램이 Pico를 쓰고 있으면 닫고 다시 눌러 주세요.");
      return;
    }
    const s: Session = {
      port: chosen, writer: chosen.writable!.getWriter(), reader: chosen.readable!.getReader(),
      reading: Promise.resolve(), text: "", mark: -1, failing: false, closing: false,
    };
    session.current = s;
    s.reading = drain(s, (why) => close(s, why));
    let problem: string | null;
    try {
      problem = await startJog(s);
    } catch {
      problem = "Pico와 통신하지 못했습니다. USB 연결을 확인해 주세요.";
    }
    if (problem) return close(s, problem);
    if (!s.closing) setPhase("running");       // closing이면 시작 직후의 Traceback을 close가 이미 처리했다
  }

  const onPress = (letter: JogLetter) => (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    hold(letter);
  };

  const running = phase === "running";
  const chip = running ? ["조작 중", css.chipOn]
    : phase === "connecting" ? ["연결하는 중", ""]
    : phase === "closing" ? ["연결 해제 중", ""]
    : ports.length ? ["Pico 감지됨 (연결 전)", ""]
    : ["Pico 없음", css.chipOff];
  const hint = running ? "누르고 있는 동안만 움직이고, 떼면 섭니다. 맥에서는 방향키로도 됩니다. 연결을 해제하면 제설차 프로그램이 다시 시작됩니다."
    : phase === "connecting" ? "Pico에 조작 프로그램을 올리는 중입니다."
    : phase === "closing" ? "제설차 프로그램을 다시 시작하는 중입니다."
    : ports.length ? "연결하면 제설차 프로그램(main.py)을 멈추고 이 화면의 조작 프로그램으로 바꿉니다."
    : "처음 한 번은 ‘연결’을 눌러 목록에서 Pico를 골라야 합니다. 허용한 뒤에는 USB를 꽂기만 해도 감지됩니다.";

  return (
    <section className={css.pad}>
      <div className={css.head}>
        <h2>Pico 직접 조작</h2>
        {support === "yes" && <span className={`${css.chip} ${chip[1]}`} role="status">{chip[0]}</span>}
      </div>
      {support === "no" && (
        <p className={css.note}>Pico 직접 조작은 맥의 Chrome이나 Edge에서만 됩니다(Safari·아이패드는 지원하지 않습니다).
          주소도 https이거나 http://localhost여야 합니다.</p>
      )}
      {support === "yes" && (
        <>
          <p className={css.hint}>{hint}</p>
          <div className={css.bar}>
            {phase === "idle" || phase === "connecting"
              ? <button className={`${css.btn} ${css.btnDark}`} type="button" disabled={phase !== "idle"} onClick={connect}>연결</button>
              : <button className={css.btn} type="button" disabled={phase !== "running"} onClick={() => session.current && close(session.current)}>연결 해제</button>}
          </div>
          <div className={css.cross} role="group" aria-label="Pico 직접 조작">
            {JOG_PAD.map(([d, icon, label]) => (
              <button key={d} type="button" className={`${css.key} ${KEY_CLASS[d]}`} aria-label={label} aria-pressed={held === d} disabled={!running}
                {...(d === JOG.stop
                  ? { onClick: () => release() }
                  : { onPointerDown: onPress(d), onPointerUp: () => release(d), onPointerLeave: () => release(d), onPointerCancel: () => release(d) })}
                onContextMenu={(e) => e.preventDefault()}>
                <span aria-hidden>{icon}</span>{label}
              </button>
            ))}
          </div>
          {error && <p className={css.err} role="alert">{error}</p>}
        </>
      )}
    </section>
  );
}
