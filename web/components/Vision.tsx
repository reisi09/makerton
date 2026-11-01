"use client";

import QRCode from "qrcode";
import { useEffect, useState } from "react";
import BoardMap, { type Arm, type Pose } from "@/components/BoardMap";
import PicoPad from "@/components/PicoPad";
import SnowBoxes from "@/components/SnowBoxes";
import { ARM_NAMES, padUrl } from "@/lib/vision";

const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const PHASE: Record<string, string> = { depart: "기지에서 나가는 중", turn: "방향 바꾸는 중", out: "눈 미는 중", back: "교차로로 후진 중", home: "기지로 돌아가는 중" };

interface Eye { usable?: boolean; arms?: Record<string, boolean>; note?: string; thinking?: string; secs?: number; error?: string }
interface Result {
  view?: string; time: string; arms: Record<string, Arm> | null;
  decision: { go: boolean; text: string };
  route: { order: string[]; seconds: number; path: Pose[] } | null;
  dispatch: { plan_id?: string; mode?: string; error?: string } | null;
  eye?: Eye | null;
}
interface ServerState {
  monitor_url?: string;
  vision?: Result | null;
  vision_live?: { thinking: string } | null;
  claude?: boolean;
  car?: { ok: boolean; tel?: { x: number | null; y: number | null; h: number | null; state?: string; phase?: string; arm?: string | null } };
  execution?: { state?: string; plan_id?: string };
}

async function post(path: string, body: object): Promise<Result> {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error ?? `서버 오류 ${r.status}`);
  return data;
}

export default function Vision() {
  const [api, setApi] = useState<"checking" | "ok" | "missing">("checking");
  const [state, setState] = useState<ServerState>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [qr, setQr] = useState("");
  const [onMac, setOnMac] = useState(false);       // Pico USB 조작은 맥에서 localhost로 열었을 때만 보인다

  useEffect(() => {
    let alive = true;
    const poll = () =>
      fetch("/api/state")
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((s: ServerState) => { if (alive) { setState(s); setApi("ok"); } })
        .catch(() => { if (alive) setApi((a) => (a === "ok" ? a : "missing")); });
    poll();
    const id = setInterval(poll, 1000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const pad = state.monitor_url ? padUrl(state.monitor_url, BASE) : null;
  const onLaptop = typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname);
  useEffect(() => {
    if (pad && onLaptop) QRCode.toDataURL(pad, { margin: 1, width: 180 }).then(setQr);
  }, [pad, onLaptop]);
  useEffect(() => setOnMac(onLaptop), [onLaptop]);   // 정적 HTML과 첫 렌더를 맞추려고 마운트 뒤에 정한다

  async function run(label: string, job: () => Promise<Result>) {
    setBusy(label);
    setError("");
    setResult(null);                 // 이전 판정을 새 결과로 오해하지 않게 지운다
    try {
      setResult(await job());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  const sweep = () => run("전체 청소 경로를 계산하는 중…", () => post("/api/sweep", {}));
  const stop = () => fetch("/api/car/stop", { method: "POST" }).catch(() => setError("정지 명령을 보내지 못했습니다."));

  const running = state.execution?.state === "running";
  const shown = result ?? state.vision ?? null;       // 새로고침해도 서버가 기억하는 마지막 판정을 보여 준다
  const tel = state.car?.ok ? state.car.tel : undefined;
  const live: Pose | undefined = tel && tel.x != null && tel.y != null ? [tel.x, tel.y, tel.h ?? 270] : undefined;
  const moving = tel && (tel.state === "run" || tel.state === "pause") && tel.phase ? PHASE[tel.phase] : undefined;

  return (
    <>
      <main className="app">
        <div className="top">
          <div className="logo" aria-hidden>❄</div>
          <h1>ICE-ZERO 사거리 제설</h1>
          {api === "ok" && <>
            <span className="st on">서버 연결</span>
            <span className={`st ${state.car?.ok ? "on" : "off"}`}>제설차 {state.car?.ok ? "연결" : "연결 끊김"}</span>
          </>}
          <span className="spacer" />
          {running && <button className="btn dark" type="button" onClick={stop}>■ 정지 ({state.execution?.plan_id} 출동 중)</button>}
        </div>

        {api === "missing" && (
          <section className="vcard">
            <h2>AI 눈 찾기와 자동 출동은 맥 서버에 접속해야 쓸 수 있습니다.</h2>
            <p>GitHub 페이지(https)에서는 브라우저가 같은 핫스팟에 연결된 맥으로 사진을 보내는 것을 차단합니다.
              맥에서 서버를 켠 뒤 <b>http://localhost:8000/app/</b>(맥) 또는 <b>http://&lt;맥 IP&gt;:8000/app/</b>(아이패드)에 접속하면 됩니다.
              Pico 수동 조작은 맥에서 <b>http://localhost:8000/app/</b>으로 열었을 때만 보입니다.</p>
          </section>
        )}

        <div className="vgrid">
          <section>
            <SnowBoxes />

            {onMac ? <PicoPad /> : (
              <p className="vhint">Pico 수동 조작은 맥에서 <b>http://localhost:8000/app/</b>을 Chrome·Edge로 열었을 때만 쓸 수 있습니다.</p>
            )}

            <div className="sec-h"><h2>자동 출동</h2><small>‘전체 청소’를 누르면 기지에서 나와 네 갈래를 모두 제설합니다(Wi-Fi 연결 필요).</small></div>
            <div className="vbtns">
              <button className="btn xl" type="button" disabled={!!busy || running || api !== "ok"} onClick={sweep}>전체 청소</button>
            </div>
            {qr && (
              <div className="qr">
                <img src={qr} alt="아이패드 접속용 QR" width={120} height={120} />
                <p>아이패드 카메라로 QR을 스캔하면 이 화면이 열립니다.<br /><b>{pad}</b></p>
              </div>
            )}
          </section>

          <section>
            <div className="sec-h"><h2>결과</h2><small>파랑 = 도로, 빨강 = 눈</small></div>
            {busy || state.vision_live ? (
              <>
                <p className="empty" role="status">{busy || "다른 기기에서 올린 사진을 Claude가 보는 중…"}</p>
                {state.vision_live?.thinking && <p className="vthink" aria-live="polite">{state.vision_live.thinking}</p>}
              </>
            ) : error ? (
              <p className="verr" role="alert">{error}</p>
            ) : shown ? (
              <p className={`vdecide ${shown.decision.go ? "go" : ""}`} role="status">
                {shown.decision.text}
                {shown.dispatch?.plan_id && ` · ${shown.dispatch.plan_id} ${shown.dispatch.mode === "car" ? "제설차" : "모의 실행"}`}
                {shown.dispatch?.error && ` · ${shown.dispatch.error}`}
                {shown.decision.go && !shown.dispatch && " · 바로 출동 기능이 꺼져 있어 제설차를 출동시키지 않았습니다."}
              </p>
            ) : running ? null : (
              <p className="empty">제설차는 북동쪽 제설 기지에서 기다리고 있습니다.</p>
            )}
            {!busy && !state.vision_live && shown?.eye && (
              <div className="vcard">
                <h2>Claude의 판단{shown.eye.secs ? ` · ${shown.eye.secs}초` : ""}</h2>
                {shown.eye.error ? <p>판정 실패: {shown.eye.error}</p> : <>
                  <p>{shown.eye.usable === false && "사진으로는 판단하기 어렵다고 봤습니다. "}{shown.eye.note}</p>
                  {shown.eye.thinking && <details><summary>생각한 과정</summary><p className="vthink">{shown.eye.thinking}</p></details>}
                </>}
              </div>
            )}
            {shown?.view && <img className="vimg" src={shown.view} alt="도로와 눈 인식 결과" />}
            {moving && <p className="sub" role="status">제설차 {tel?.arm ? `${ARM_NAMES[tel.arm] ?? tel.arm} ` : ""}{moving}{tel?.state === "pause" ? " (일시 정지)" : ""}</p>}
            <BoardMap arms={shown?.arms ?? undefined} path={shown?.route?.path} order={shown?.route?.order} car={live} />
            {shown?.arms && (
              <table>
                <tbody>
                  {Object.entries(shown.arms).map(([name, a]) => (
                    <tr key={name}>
                      <td className="t1 nowrap">{ARM_NAMES[name] ?? name}</td>
                      <td className="nowrap">{a.area_mm2} mm²</td>
                      <td className="far">{a.far_mm ? `중심에서 ${a.far_mm} mm까지` : "–"}</td>
                      {shown.eye?.arms && <td className="nowrap">Claude {shown.eye.arms[name] ? "눈" : "없음"}</td>}
                      <td><span className="tag">{shown.route?.order.includes(name) ? `${shown.route.order.indexOf(name) + 1}번째 제설` : name === "C" ? "갈래 순회 중 눈이 밀려남" : "제설 기준 미달"}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      </main>
      <footer>
        사진은 보안키를 넣은 뒤 맥 서버를 거쳐 Claude가 보고, 도로 위 눈을 상자로 표시합니다(차는 움직이지 않음).
        수동 조작은 맥의 Chrome·Edge가 USB로 꽂힌 Pico에 직접 명령을 보냅니다. ‘전체 청소’는 북동쪽 제설 기지에서 나와
        네 갈래를 가장 빠른 순서로 도는 자동 출동입니다.
        {" · "}<a href="https://reisi09.github.io/makerton/designs.html">설계도</a>{" · "}<a href="https://github.com/reisi09/makerton">GitHub</a>
      </footer>
    </>
  );
}
