"use client";

import QRCode from "qrcode";
import { useEffect, useRef, useState } from "react";
import BoardMap, { type Arm, type Pose } from "@/components/BoardMap";
import { ARM_NAMES, padUrl } from "@/lib/vision";

const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const MAX_SIDE = 1600; // 올리기 전에 줄인다(12MP 사진을 그대로 보내지 않는다)

interface Result {
  view: string; time: string; arms: Record<string, Arm>;
  decision: { go: boolean; text: string };
  route: { order: string[]; seconds: number; path: Pose[] } | null;
  dispatch: { plan_id?: string; mode?: string; error?: string } | null;
}
interface ServerState {
  monitor_url?: string;
  car?: { ok: boolean };
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
    img.onerror = () => reject(new Error("사진을 열지 못했습니다"));
    img.src = URL.createObjectURL(file);
  });
}

export default function Vision() {
  const [api, setApi] = useState<"checking" | "ok" | "missing">("checking");
  const [state, setState] = useState<ServerState>({});
  const [go, setGo] = useState(true);
  const [busy, setBusy] = useState(false);
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
    const id = setInterval(poll, 2000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const pad = state.monitor_url ? padUrl(state.monitor_url, BASE) : null;
  const onLaptop = typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname);
  useEffect(() => {
    if (pad && onLaptop) QRCode.toDataURL(pad, { margin: 1, width: 180 }).then(setQr);
  }, [pad, onLaptop]);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    setResult(null);                 // 이전 사진의 출동 판정을 새 사진 결과로 오해하지 않게 지운다
    try {
      const image = await shrink(file);
      const r = await fetch("/api/vision/detect", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image, go }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error ?? `서버 오류 ${r.status}`);
      setResult(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const running = state.execution?.state === "running";
  const stop = () => fetch("/api/car/stop", { method: "POST" }).catch(() => setError("정지 명령을 보내지 못했습니다"));
  const picker = (ref: React.RefObject<HTMLInputElement | null>, capture: boolean) => (
    <input ref={ref} type="file" accept="image/*" hidden {...(capture ? { capture: "environment" as const } : {})}
      onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
  );

  return (
    <>
      <main className="app">
        <div className="top">
          <a className="logo" href={`${BASE}/`} aria-label="재생 화면으로">❄</a>
          <h1>사진으로 출동</h1>
          <span className={`st ${api === "ok" ? "on" : "off"}`}>서버 {api === "ok" ? "연결" : api === "checking" ? "확인 중" : "없음"}</span>
          <span className={`st ${state.car?.ok ? "on" : "off"}`}>제설차 {state.car?.ok ? "연결" : "끊김"}</span>
          <span className="spacer" />
          {running && <button className="btn dark" type="button" onClick={stop}>■ 정지 ({state.execution?.plan_id} 출동 중)</button>}
        </div>

        {api === "missing" && (
          <section className="vcard">
            <h2>이 화면은 맥 서버에서 열어야 합니다</h2>
            <p>GitHub 페이지(https)에서는 브라우저가 핫스팟 안의 맥으로 사진을 보내지 못하게 막습니다.
              맥에서 서버를 켜고, 패드 Safari로 <b>http://&lt;맥 IP&gt;:8000/app/vision/</b> 을 여세요.</p>
          </section>
        )}

        {api === "ok" && (
          <div className="vgrid">
            <section>
              <div className="sec-h"><h2>찍기</h2><small>보드 전체가 보이게 위에서</small></div>
              <div className="vbtns">
                <button className="btn dark xl" type="button" disabled={busy} onClick={() => camera.current?.click()}>
                  {busy ? "맥이 계산 중…" : "눈 사진 찍기"}</button>
                <button className="btn" type="button" disabled={busy} onClick={() => album.current?.click()}>앨범에서 고르기</button>
              </div>
              {picker(camera, true)}
              {picker(album, false)}
              <label className="vopt"><input type="checkbox" checked={go} onChange={(e) => setGo(e.target.checked)} /> 차 경로에 눈이 보이면 바로 출동</label>
              <p className="vhint">방향은 상관없습니다. 노란 코트가 교차로 왼쪽 아래에 오도록 맥이 돌려서 봅니다.
                차는 북동쪽 제설 기지에서 나와 눈 있는 갈래를 끝까지 밀고 돌아옵니다.</p>
              {qr && (
                <div className="qr">
                  <img src={qr} alt="패드로 열기 QR" width={120} height={120} />
                  <p>패드 카메라로 찍으면 이 화면이 열립니다.<br /><b>{pad}</b></p>
                </div>
              )}
            </section>

            <section>
              <div className="sec-h"><h2>인식 결과</h2><small>파랑 = 도로, 빨강 = 눈</small></div>
              {busy ? (
                <p className="empty" role="status">맥이 사진에서 도로와 눈을 찾는 중…</p>
              ) : error ? (
                <p className="verr" role="alert">{error}</p>
              ) : result ? (
                <>
                  <p className={`vdecide ${result.decision.go ? "go" : ""}`} role="status">
                    {result.decision.text}
                    {result.dispatch?.plan_id && ` · ${result.dispatch.plan_id} ${result.dispatch.mode === "car" ? "제설차" : "모의 실행"}`}
                    {result.dispatch?.error && ` · ${result.dispatch.error}`}
                    {result.decision.go && !result.dispatch && " · 바로 출동이 꺼져 있어 보내지 않았습니다"}
                  </p>
                  <img className="vimg" src={result.view} alt="도로와 눈 인식 결과" />
                  {result.route && <BoardMap arms={result.arms} path={result.route.path} order={result.route.order} />}
                  <table>
                    <tbody>
                      {Object.entries(result.arms).map(([name, a]) => (
                        <tr key={name}>
                          <td className="t1 nowrap">{ARM_NAMES[name] ?? name}</td>
                          <td className="nowrap">{a.area_mm2} mm²</td>
                          <td className="far">{a.far_mm ? `중심에서 ${a.far_mm} mm까지` : "–"}</td>
                          <td><span className="tag">{result.route?.order.includes(name) ? `${result.route.order.indexOf(name) + 1}번째로 치움` : name === "C" ? "갈래를 돌며 밀림" : "기준 아래"}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              ) : (
                <p className="empty">눈 사진을 찍으면 여기에 도로·눈 인식 결과가 나옵니다.</p>
              )}
            </section>
          </div>
        )}
      </main>
      <footer>
        맥이 사진에서 검은 도로만 찾고 도로 위 흰 알갱이를 갈래별로 셉니다(기준 사진·학습 없음). 눈이 100mm² 넘는 갈래를
        북동쪽 제설 기지에서 도는 모든 순서를 비교해 가장 빠른 순서로 제설차를 보냅니다.
      </footer>
    </>
  );
}
