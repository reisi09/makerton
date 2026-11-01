"use client";

import QRCode from "qrcode";
import { useEffect, useRef, useState } from "react";
import BoardMap, { type Arm, type Pose } from "@/components/BoardMap";
import { ARM_NAMES, padUrl } from "@/lib/vision";

const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const MAX_SIDE = 1600; // 올리기 전에 줄인다(12MP 사진을 그대로 보내지 않는다)
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

function shrink(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.naturalWidth * k);
      canvas.height = Math.round(img.naturalHeight * k);
      canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(img.src);
      resolve(canvas.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = () => reject(new Error("사진을 열지 못했습니다."));
    img.src = URL.createObjectURL(file);
  });
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
  const [go, setGo] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [qr, setQr] = useState("");
  const camera = useRef<HTMLInputElement>(null);
  const album = useRef<HTMLInputElement>(null);

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
  const onFile = (file: File | undefined) =>
    file && run(state.claude ? "맥이 도로와 눈을 찾고, Claude가 사진을 보는 중…" : "맥이 사진에서 도로와 눈을 찾는 중…",
      async () => post("/api/vision/detect", { image: await shrink(file), go }));
  const sweep = () => run("전체 청소 경로를 계산하는 중…", () => post("/api/sweep", {}));
  const stop = () => fetch("/api/car/stop", { method: "POST" }).catch(() => setError("정지 명령을 보내지 못했습니다."));

  const running = state.execution?.state === "running";
  const shown = result ?? state.vision ?? null;       // 새로고침해도 서버가 기억하는 마지막 판정을 보여 준다
  const tel = state.car?.ok ? state.car.tel : undefined;
  const live: Pose | undefined = tel && tel.x != null && tel.y != null ? [tel.x, tel.y, tel.h ?? 270] : undefined;
  const moving = tel && (tel.state === "run" || tel.state === "pause") && tel.phase ? PHASE[tel.phase] : undefined;
  const picker = (ref: React.RefObject<HTMLInputElement | null>, capture: boolean) => (
    <input ref={ref} type="file" accept="image/*" hidden {...(capture ? { capture: "environment" as const } : {})}
      onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
  );

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
            <h2>이 화면은 맥에서 실행 중인 서버에 접속해 열어야 합니다.</h2>
            <p>GitHub 페이지(https)에서는 브라우저가 같은 핫스팟에 연결된 맥으로 사진을 보내는 것을 차단합니다.
              맥에서 서버를 켠 뒤 아이패드의 Safari에서 <b>http://&lt;맥 IP&gt;:8000/app/</b>에 접속하면 됩니다.</p>
          </section>
        )}

        <div className="vgrid">
          <section>
            <div className="sec-h"><h2>출동</h2><small>사진을 찍으면 눈이 있는 갈래만, ‘전체 청소’를 누르면 네 갈래 모두 제설합니다.</small></div>
            <div className="vbtns">
              <button className="btn dark xl" type="button" disabled={!!busy || api !== "ok"} onClick={() => camera.current?.click()}>
                눈 사진 찍기</button>
              <button className="btn xl" type="button" disabled={!!busy || running || api !== "ok"} onClick={sweep}>전체 청소</button>
              <button className="btn" type="button" disabled={!!busy || api !== "ok"} onClick={() => album.current?.click()}>앨범에서 고르기</button>
            </div>
            {picker(camera, true)}
            {picker(album, false)}
            <label className="vopt"><input type="checkbox" checked={go} onChange={(e) => setGo(e.target.checked)} /> 사진에서 눈이 보이면 바로 출동</label>
            <p className="vhint">보드 전체가 보이도록 위에서 찍으면 됩니다. 촬영 방향은 상관없습니다. 맥이 사진을 돌려 노란 코트가 교차로 왼쪽 아래에 오도록 맞춥니다.
              제설차는 북동쪽 제설 기지에서 나와 갈래 끝까지 눈을 밀고 돌아옵니다.</p>
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
        맥이 사진에서 검은 도로만 찾고 도로 위 흰 알갱이를 갈래별로 셉니다(기준 사진·학습 없음). 서버에 Claude 키가 있으면 Claude도
        같은 사진을 보고, 둘의 판단이 다르면 네 갈래를 모두 치웁니다. 북동쪽 제설 기지에서 출발해
        눈의 면적이 100 mm²를 넘는 갈래를 도는 모든 순서를 비교하고 가장 빠른 순서로 제설차를 출동시킵니다.
        {" · "}<a href="https://reisi09.github.io/makerton/designs.html">설계도</a>{" · "}<a href="https://github.com/reisi09/makerton">GitHub</a>
      </footer>
    </>
  );
}
