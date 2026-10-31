"use client";

import { useEffect, useRef, useState } from "react";
import BoardMap, { type Arm, type Pose } from "@/components/BoardMap";
import { ARM_NAMES } from "@/lib/vision";

const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const PLAY_MS = 12000; // 화면에서 출동 한 번을 12초로 줄여 보여 준다(실물은 route.seconds)

interface Route { order: string[]; seconds: number; worst_order: string[]; worst_seconds: number; tried: number; path: Pose[] }
interface Sample { id: string; photo: string; overlay: string; arms: Record<string, Arm>; decision: { go: boolean; text: string }; route: Route | null }
interface Demo { min_mm2: number; samples: Sample[] }

const label = (s: Sample) => (s.route ? s.route.order.join("→") : "눈 없음");

export default function Demo() {
  const [data, setData] = useState<Demo | null>(null);
  const [error, setError] = useState("");
  const [pick, setPick] = useState(0);
  const [step, setStep] = useState<number | null>(null);
  const raf = useRef(0);

  useEffect(() => {
    fetch(`${BASE}/demo/vision.json`).then((r) => r.json()).then((d: Demo) => {
      setData(d);
      setPick(Math.max(0, d.samples.findIndex((s) => s.route && s.route.order.length >= 3)));
    }).catch((e) => setError(String(e)));
    return () => cancelAnimationFrame(raf.current);
  }, []);

  if (error) return <main className="app">자료를 불러오지 못했다: {error}</main>;
  if (!data) return <main className="app">불러오는 중…</main>;

  const s = data.samples[pick];
  const route = s.route;
  const playing = step != null && route != null && step < route.path.length - 1;

  function choose(i: number) {
    cancelAnimationFrame(raf.current);
    setStep(null);
    setPick(i);
  }
  function play() {
    if (!route) return;
    cancelAnimationFrame(raf.current);
    const t0 = performance.now(), last = route.path.length - 1;
    const tick = (now: number) => {
      const i = Math.min(last, Math.round(((now - t0) / PLAY_MS) * last));
      setStep(i);
      if (i < last) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  }

  return (
    <>
      <main className="app">
        <div className="top">
          <div className="logo" aria-hidden>❄</div>
          <h1>ICE-ZERO 사거리 제설</h1>
          <span className="sub">사진 한 장 → 눈 인식 → 최적 경로 → 제설차 출동</span>
          <span className="spacer" />
          <a className="btn" href={`${BASE}/vision/`}>패드로 찍어 출동</a>
        </div>

        <section className="samples" aria-label="모형 사진 고르기">
          {data.samples.map((x, i) => (
            <button key={x.id} type="button" className="thumb" aria-pressed={i === pick} onClick={() => choose(i)}>
              <img src={`${BASE}/demo/${x.photo}`} alt="" />
              <span>{label(x)}</span>
            </button>
          ))}
        </section>

        <div className="vgrid">
          <section>
            <div className="sec-h"><h2>1. 눈 인식</h2><small>파랑 = 찾은 도로, 빨강 = 눈</small></div>
            <img className="vimg" src={`${BASE}/demo/${s.overlay}`} alt="모형 사진에서 찾은 도로와 눈" />
            <table>
              <tbody>
                {(["C", "N", "E", "S", "W"] as const).map((a) => {
                  const arm = s.arms[a], hit = arm.area_mm2 >= data.min_mm2;
                  return (
                    <tr key={a}>
                      <td className="t1 nowrap">{ARM_NAMES[a]}</td>
                      <td className="nowrap">{arm.area_mm2} mm²</td>
                      <td><span className="tag">{a === "C" ? "갈래를 돌며 같이 밀림" : hit ? "치우러 감" : "기준 아래"}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <section>
            <div className="sec-h"><h2>2. 최적 경로</h2><small>제설 기지(북동) 출발 → 갈래 → 기지</small>
              {route && <button className="btn dark" type="button" onClick={play} disabled={playing}>{playing ? "출동 중…" : "▶ 출동 재생"}</button>}
            </div>
            <p className={`vdecide ${s.decision.go ? "go" : ""}`} role="status">{s.decision.text}</p>
            <BoardMap arms={s.arms} min={data.min_mm2} path={route?.path} upto={step ?? 0} order={route?.order} />
            {route && (
              <p className="legend">
                순서마다 차가 도는 시간을 펌웨어 경로로 직접 계산해 {route.tried}가지를 비교했다. 가장 느린 순서({route.worst_order.join("→")})는
                약 {route.worst_seconds}초, 고른 순서는 약 {route.seconds}초.
              </p>
            )}
          </section>
        </div>
      </main>
      <footer>
        사진은 팀이 찍은 실제 모형이다. 서버와 같은 코드가 검은 도로만 찾아 그 위 흰 알갱이(우드락 눈)를 갈래별로 세고(학습·기준 사진 없음),
        눈이 {data.min_mm2}mm² 넘는 갈래를 기지에서 도는 모든 순서를 비교해 가장 빠른 것을 고른다. 차는 갈래 끝까지 밀고 같은 길로 후진한다.
        {" · "}<a href={`${BASE}/designs.html`}>설계도</a>{" · "}<a href="https://github.com/reisi09/makerton">GitHub</a>
      </footer>
    </>
  );
}
