"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { addHours, decide, freezeProb, REST_HOURS, type Night, type Replay } from "@/lib/rules";

const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const HOUR_S = 1.2;   // 화면 1.2초 = 1시간
const EXEC_MS = 6000; // 출동 한 번(실물 약 44초)
const START_NIGHT = "2025-12-29";

interface LogRow { t: string; icon: string; title: string; sub: string; tag: string; p: number }
interface Sim {
  night: Night; si: number; playing: boolean; acc: number; snow: boolean; restUntil: string | null;
  run: { start: number; p: number; pushed: boolean } | null; runs: number; log: LogRow[];
}

const hhmm = (t: string) => t.slice(11, 16);
const day = (t: string) => `${+t.slice(5, 7)}월 ${+t.slice(8, 10)}일`;
const deg = (v: number | null | undefined) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(1)}°C`);

export default function Demo() {
  const [data, setData] = useState<Replay | null>(null);
  const [error, setError] = useState("");
  const sim = useRef<Sim | null>(null);
  const [, redraw] = useReducer((x: number) => x + 1, 0);

  useEffect(() => {
    fetch(`${BASE}/demo/replay.json`)
      .then((r) => r.json())
      .then((d: Replay) => {
        setData(d);
        load(d.nights.find((n) => n.night === START_NIGHT) ?? d.nights[0]);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const dt0 = data ? data.dt_grid.indexOf(0) : 0;
  const prob = (s: Sim) => freezeProb(s.night.steps[s.si], dt0);
  const resting = (s: Sim) => !!s.restUntil && s.night.steps[s.si].t < s.restUntil;

  function load(night: Night) {
    sim.current = { night, si: 0, playing: false, acc: 0, snow: false, restUntil: null, run: null, runs: 0, log: [] };
    redraw();
  }
  function log(s: Sim, row: Omit<LogRow, "t" | "p">) {
    s.log = [{ t: hhmm(s.night.steps[s.si].t), p: prob(s), ...row }, ...s.log].slice(0, 5);
  }
  function evaluate(s: Sim) {
    if (!data) return;
    const d = decide({ running: !!s.run, snow: s.snow, t: s.night.steps[s.si].t, restUntil: s.restUntil, p: prob(s), threshold: data.threshold });
    if (!d) return;
    s.run = { start: performance.now(), p: 0, pushed: false };
    s.runs += 1;
    log(s, d.kind === "snow"
      ? { icon: "🚜", title: "출동", sub: "조도센서가 눈 조각에 덮였다", tag: "눈 감지" }
      : { icon: "🚜", title: "출동", sub: `6시간 안 결빙 확률 ${Math.round(d.p * 100)}%`, tag: "모델 판단" });
  }
  function finish(s: Sim) {
    s.run = null;
    s.snow = false;
    s.restUntil = addHours(s.night.steps[s.si].t, REST_HOURS);
    log(s, { icon: "✓", title: "제설 끝", sub: `${hhmm(s.restUntil)}까지 쉼 (눈이 오면 바로 출동)`, tag: "" });
  }

  useEffect(() => {
    if (!data) return;
    let raf = 0, last = performance.now();
    const loop = (now: number) => {
      const s = sim.current, dt = (now - last) / 1000;
      last = now;
      if (s?.run) {
        s.run.p = Math.min(1, (now - s.run.start) / EXEC_MS);
        if (s.run.p >= 1) finish(s);
        redraw();
      } else if (s?.playing && (s.acc += dt) >= HOUR_S) {
        s.acc = 0;
        if (s.si < s.night.steps.length - 1) { s.si += 1; evaluate(s); } else s.playing = false;
        redraw();
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [data]);

  const s = sim.current;
  if (error) return <div className="app">자료를 불러오지 못했다: {error}</div>;
  if (!data || !s) return <div className="app">불러오는 중…</div>;

  const steps = s.night.steps, step = steps[s.si], p = prob(s), pct = Math.round(p * 100);
  const gap = Math.round(data.threshold * 100) - pct;
  const prev = s.si > 0 ? steps[s.si - 1].obs.ground_temp : null, g = step.obs.ground_temp;
  const ended = s.si >= steps.length - 1;

  const onPlay = () => {
    if (ended) load(s.night);
    const cur = sim.current!;
    cur.playing = !cur.playing;
    cur.acc = 0;
    if (cur.playing) evaluate(cur);
    redraw();
  };
  const onSnow = () => {
    if (s.run) return;
    s.snow = !s.snow;
    evaluate(s);
    redraw();
  };

  return (
    <>
      <div className="app">
        <div className="top">
          <div className="logo" aria-hidden>❄</div>
          <h1>사거리 제설</h1>
          <select className="pill" aria-label="밤 선택" value={s.night.night}
            onChange={(e) => load(data.nights.find((n) => n.night === e.target.value)!)}>
            {data.nights.map((n) => (
              <option key={n.night} value={n.night}>{day(n.night + "T")} 밤{n.freezing ? "" : " (안 얼음)"}</option>
            ))}
          </select>
          <span className="spacer" />
          <button className="btn" type="button" aria-pressed={s.snow} disabled={!!s.run} onClick={onSnow}>눈 올리기</button>
          <button className="btn dark" type="button" onClick={onPlay}>{s.playing ? "❚❚ 멈춤" : ended ? "↺ 다시" : "▶ 재생"}</button>
        </div>

        <div className="hero">
          <div>
            <div className="big">{pct}%</div>
            <div className="big-cap">6시간 안에 길이 얼 확률 · {day(step.t)} {hhmm(step.t)}</div>
          </div>
          <div>
            <div className="goal">
              {resting(s) ? <><b>제설 완료</b>{hhmm(s.restUntil!)}까지 모델 출동은 쉰다</>
                : gap <= 0 ? <><b>출동 기준을 넘었다</b>제설차를 보낸다</>
                : <><b>{gap}%p</b>더 오르면 출동</>}
            </div>
            <div className="bar">
              <div className="fill" style={{ width: `${Math.max(3, pct)}%` }}>{pct >= 12 && <span>{pct}%</span>}</div>
              <div className="mark"><span>출동 기준 50%</span></div>
            </div>
          </div>
        </div>

        <div className="kpis">
          <div className="kpi">
            <div className="lab">지금 지면온도</div>
            <div className="row">
              {g != null && prev != null && g !== prev && <span className={`sq ${g < prev ? "dn" : "up"}`}>{g < prev ? "↓" : "↑"}</span>}
              <span className="val">{deg(g)}</span>
              {g != null && prev != null && g !== prev && <span className="note">1시간 전보다 {Math.abs(g - prev).toFixed(1)}°C {g < prev ? "내려감" : "올라감"}</span>}
            </div>
          </div>
          <div className="kpi">
            <div className="lab">3시간 뒤 예보</div>
            <div className="row"><span className="val">{deg(step.fc.h3)}</span><span className="note">{step.fc.h3 <= 0 ? "0°C 아래 · 얼음 예상" : "0°C 위"}</span></div>
          </div>
          <div className="kpi">
            <div className="lab">오늘 밤 출동</div>
            <div className="row"><span className="val">{s.runs}번</span><span className="note">{ended ? "밤 끝" : `다음 판단 ${hhmm(steps[s.si + 1].t)}`}</span></div>
          </div>
        </div>

        <div className="lower">
          <section>
            <div className="sec-h"><h2>판단 기록</h2>
              <small>{s.night.freezing ? `이날 밤 실제 최저 ${s.night.t_min}°C` : `이날 밤은 얼지 않았다 (최저 ${s.night.t_min}°C)`}</small></div>
            <table><tbody>
              {s.log.length === 0 && <tr><td className="empty" colSpan={5}>▶ 재생을 누르면 18시부터 한 시간씩 모델이 판단한다</td></tr>}
              {s.log.map((e, i) => (
                <tr key={s.log.length - i}>
                  <td style={{ width: 44 }}><div className={`ico${e.icon === "🚜" ? " go" : ""}`}>{e.icon}</div></td>
                  <td><div className="t1">{e.title}</div><div className="t2">{e.sub}</div></td>
                  <td>{e.tag && <span className="tag">{e.tag}</span>}</td>
                  <td className="time">{e.t}</td>
                  <td><div className="ring"><Ring p={e.p} />{Math.round(e.p * 100)}%</div></td>
                </tr>
              ))}
            </tbody></table>
          </section>
          <section>
            <div className="sec-h"><h2>사거리</h2>
              <span className="state">{s.run ? (s.run.p < 0.5 ? "🚜 출동 중" : "🚜 돌아오는 중") : resting(s) ? "✓ 제설 완료" : "대기"}</span></div>
            <CrossMap sim={s} p={p} resting={resting(s)} />
          </section>
        </div>
      </div>
      <footer>
        확률과 예보는 수원 관측소(학교에서 0.4km) 자료로 학습한 실제 모델이 그 시각까지의 관측만 보고 계산한 값이다. 재생하는 밤은 학습에 쓰지 않은 2025년이다.
        확률이 50%를 넘거나 눈이 감지되면 출동하고, 한 번 치우면 3시간은 쉰다. 차와 눈은 화면 그림이다.
        {" · "}<a href={`${BASE}/designs.html`}>설계도</a>{" · "}<a href="https://github.com/reisi09/makerton">GitHub</a>
      </footer>
    </>
  );
}

function Ring({ p }: { p: number }) {
  const r = 9, c = 2 * Math.PI * r;
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden>
      <circle cx="12" cy="12" r={r} fill="none" stroke="#e8edf2" strokeWidth="3" />
      <circle cx="12" cy="12" r={r} fill="none" stroke="#2c7da0" strokeWidth="3" strokeLinecap="round"
        strokeDasharray={`${(c * p).toFixed(1)} ${c.toFixed(1)}`} transform="rotate(-90 12 12)" />
    </svg>
  );
}

// 사거리 평면. 광장 420mm = 240px. 차는 대기 칸(중심 남쪽 250mm)과 북쪽 멈춤(170mm) 사이를 오간다.
const K = 240 / 420, CX = 300, CY = 270, PW = 297 * K, PH = 420 * K, ROAD = 150 * K;
const HOME = CY + 250 * K, STOP = CY - 170 * K;
const ease = (x: number) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);

function CrossMap({ sim, p, resting }: { sim: Sim; p: number; resting: boolean }) {
  const run = sim.run;
  let y = HOME;
  if (run) y = run.p < 0.5 ? HOME + (STOP - HOME) * ease(run.p / 0.5) : STOP + (HOME - STOP) * ease((run.p - 0.5) / 0.5);
  if (run && sim.snow && run.p < 0.5 && y - 58 < CY + 18) run.pushed = true;
  const gone = run?.pushed ? Math.min(1, (run.p - 0.2) * 3) : 0;
  const ice = resting || (run && run.p > 0.25) ? 0 : p * 0.6;
  return (
    <svg className="map" viewBox="0 0 600 560" role="img" aria-label="사거리와 제설차">
      <rect width="600" height="560" rx="18" fill="#f3f6f9" />
      {[[24, 24], [426, 24], [24, 366], [426, 366]].map(([x, yy]) => <rect key={`${x}-${yy}`} x={x} y={yy} width="150" height="170" rx="14" fill="#e3eaf0" />)}
      <rect x={CX - ROAD / 2} y="0" width={ROAD} height="560" fill="#cfd8e0" />
      <rect x="0" y={CY - ROAD / 2} width="600" height={ROAD} fill="#cfd8e0" />
      <rect x={CX - PW / 2} y={CY - PH / 2} width={PW} height={PH} fill="#bcc9d4" />
      <rect x={CX - PW / 2} y={CY - PH / 2} width={PW} height={PH} fill="#2c7da0" opacity={ice} />
      <rect x={CX - PW / 2} y={CY - PH / 2} width={PW} height={PH} fill="none" stroke="#012a4a" strokeWidth="1.5" strokeDasharray="7 6" opacity=".45" />
      <circle cx={CX} cy={CY} r="7" fill="#f2c230" stroke="#fff" strokeWidth="2" />
      <rect x={CX - 18 + gone * 90} y={CY - 18} width="36" height="36" rx="6" fill="#fff" stroke="#a9d6e5" strokeWidth="2" opacity={sim.snow ? 1 - gone : 0} />
      <g transform={`translate(${CX},${y.toFixed(1)})`}>
        <rect x="-26" y="-34" width="52" height="69" rx="9" fill="#012a4a" />
        <rect x="-17" y="-21" width="34" height="24" rx="5" fill="#a9d6e5" />
        <rect x="-38" y="-52" width="76" height="6" rx="3" fill="#2c7da0" transform="rotate(-15)" />
      </g>
      {(["N", "E", "S", "W"] as const).map((a, i) => {
        const [x, yy] = [[CX, 18], [588, CY + 5], [CX, 552], [12, CY + 5]][i];
        return <text key={a} x={x} y={yy} fill="#6b7f90" fontSize="13" fontWeight="700" textAnchor={i === 1 ? "end" : i === 3 ? "start" : "middle"}>{a}</text>;
      })}
    </svg>
  );
}
