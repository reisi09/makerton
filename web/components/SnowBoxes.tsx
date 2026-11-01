"use client";

import { useEffect, useRef, useState } from "react";
import { askClaudeBoxes, KeyError, type Arms } from "@/lib/claudeBoxes";
import { armTip, onPhoto, type Frame, type PlannedRoute } from "@/lib/routes";
import { boxStyle, type BoxStyle, type SnowBox } from "@/lib/snowBoxes";
import styles from "./SnowBoxes.module.css";

const MAX_SIDE = 1600; // 올리기 전에 줄인다(12MP 사진을 그대로 보내지 않는다)
const KEY_STORE = "makerton-claude-key";

interface Reply { boxes?: SnowBox[]; note?: string; secs?: number; error?: string; photo?: string; usable?: boolean; arms?: Partial<Arms> }
interface View { url: string; boxes: BoxStyle[]; note: string; secs: number | null; frame: Frame | null }
// arms가 null이면 갈래 판단이 없는 응답(갈래를 모르는 예전 서버)이라 경로를 그리지 않는다.
interface Found { boxes: SnowBox[]; note: string; secs: number | null; photo: string; usable: boolean; arms: Arms | null }
const NO_SNOW: Arms = { C: false, N: false, E: false, S: false, W: false };

// Claude API 키는 이 기기의 브라우저에만 둔다(코드·저장소·서버에는 두지 않는다). 저장소가 막힌 브라우저에서는 새로고침 전까지만 쓴다.
const readKey = () => { try { return localStorage.getItem(KEY_STORE) ?? ""; } catch { return ""; } };
const writeKey = (k: string) => { try { if (k) localStorage.setItem(KEY_STORE, k); else localStorage.removeItem(KEY_STORE); } catch { /* 무시 */ } };

// Vision.tsx의 shrink()와 같은 방식. 화면에 보여 줄 사진이 서버가 본 사진과 같도록 줄인 결과를 그대로 쓴다.
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
    img.onerror = () => { URL.revokeObjectURL(img.src); reject(new Error("사진을 열지 못했습니다.")); };
    img.src = URL.createObjectURL(file);
  });
}

// 브라우저가 열지 못하는 사진(맥 Chrome의 HEIC 등)은 원본 그대로 보내고, 맥 서버가 JPEG로 바꿔 분석한 사진을 돌려받아 보여 준다.
function rawDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("사진 파일을 읽지 못했습니다."));
    reader.readAsDataURL(file);
  });
}

const jpegUrl = (dataUrl: string) =>
  URL.createObjectURL(new Blob([Uint8Array.from(atob(dataUrl.split(",")[1]), (c) => c.charCodeAt(0))], { type: "image/jpeg" }));

/** 맥 서버를 거쳐 Claude에 보낸다. 서버는 HEIC도 JPEG로 바꿔 분석하고, 분석한 사진을 돌려준다. */
async function viaServer(image: string, jpeg: string | null): Promise<Found> {
  let r: Response;
  try {
    r = await fetch("/api/vision/boxes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image }) });
  } catch {
    throw new Error("맥의 서버에 연결하지 못했습니다. Claude API 키를 넣으면 서버 없이 바로 보낼 수 있습니다.");
  }
  const data: Reply | null = await r.json().catch(() => null);
  if (!r.ok) throw new Error(data?.error ?? `서버 오류 ${r.status}`);
  // 응답을 읽지 못했는데 '눈이 보이지 않습니다'로 보이면 안 된다.
  if (!Array.isArray(data?.boxes)) throw new Error("서버 응답을 읽지 못했습니다.");
  const photo = typeof data.photo === "string" && data.photo.startsWith("data:image/jpeg") ? data.photo : jpeg;
  if (!photo) throw new Error("서버가 분석한 사진을 돌려주지 않았습니다.");
  return { boxes: data.boxes, note: data.note ?? "", secs: typeof data.secs === "number" ? data.secs : null, photo,
           usable: data.usable !== false, arms: data.arms ? { ...NO_SNOW, ...data.arms } : null };
}

/** 사진 속 도로 십자로 보드 좌표를 사진 위로 옮기는 아핀을 맥 서버에 묻는다. 방향을 모르거나 서버가 없으면 null(사진 위 경로 생략).
 *  키로 Claude를 바로 부른 결과가 꺼진 맥을 기다리지 않게 4초에서 끊는다(서버 계산은 0.1초 안팎). */
async function photoFrame(image: string): Promise<Frame | null> {
  try {
    const r = await fetch("/api/vision/frame", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image }),
      signal: AbortSignal.timeout(4000) });
    const data: { frame?: unknown } = await r.json();
    return r.ok && Array.isArray(data.frame) && data.frame.length === 6 && data.frame.every(Number.isFinite) ? (data.frame as Frame) : null;
  } catch {
    return null;
  }
}

/** 최적 경로를 사진 위에 주황 선으로 그린다. 차고(출발)에 표시, 갈래 끝에 도는 순서. 선 굵기는 화면 픽셀로 고정한다. */
function RouteOnPhoto({ route, frame }: { route: PlannedRoute; frame: Frame }) {
  const clamp = (v: number) => Math.min(97, Math.max(3, v * 100));       // 사진 밖이면 가장자리에 붙여 보인다
  const at = (x: number, y: number) => { const [u, v] = onPhoto(frame, x, y); return { left: `${clamp(u)}%`, top: `${clamp(v)}%` }; };
  const points = route.path.map(([x, y]) => onPhoto(frame, x, y).join(",")).join(" ");
  return (
    <>
      <svg className={styles.route} viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden>
        <polyline className={styles.routeEdge} points={points} vectorEffect="non-scaling-stroke" />
        <polyline className={styles.routeLine} points={points} vectorEffect="non-scaling-stroke" />
      </svg>
      <span className={styles.garage} style={at(route.path[0][0], route.path[0][1])} role="img" aria-label="차고(출발)">차고</span>
      {route.order.map((a, i) => (
        <span key={a} className={styles.step} style={at(...armTip(route.path, a))} role="img" aria-label={`${i + 1}번째로 치울 ${a} 갈래`}>{i + 1}</span>
      ))}
    </>
  );
}

/** 사진을 찍으면 AI가 눈이 있는 곳을 상자로 표시한다. 표시 전용이며 제설차를 움직이지 않는다.
 *  Claude API 키가 이 기기에 있으면 브라우저가 Claude를 바로 부르고, 없으면 맥 서버(enabled)를 거친다. */
/** onFound: 찾은 갈래별 눈(새 사진을 보내기 시작하면 null). 조작 화면이 최적 경로를 골라 route로 돌려주면 사진 위에도 그린다. 출동은 하지 않는다. */
export default function SnowBoxes({ enabled, onFound, route }: {
  enabled: boolean; onFound?: (f: { arms: Arms; usable: boolean } | null) => void; route?: PlannedRoute | null;
}) {
  const [apiKey, setApiKey] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<View | null>(null);
  const camera = useRef<HTMLInputElement>(null);
  const album = useRef<HTMLInputElement>(null);

  useEffect(() => setApiKey(readKey()), []);   // 정적 내보내기라 서버 렌더에는 저장소가 없다
  useEffect(() => () => { if (view) URL.revokeObjectURL(view.url); }, [view]);

  function saveKey(e: React.FormEvent) {
    e.preventDefault();
    const k = draft.trim();
    if (!k) return;
    if (/[^\x21-\x7e]/.test(k)) { setError("API 키에 쓸 수 없는 글자가 있습니다. 키보드를 영문으로 바꿔 다시 붙여 넣으세요."); return; }
    writeKey(k);
    setApiKey(k);
    setDraft("");
    setError("");
  }

  async function analyze(file: File | undefined) {
    if (!file || busy || (!apiKey && !enabled)) return;
    setBusy(true);
    setError("");
    setView(null);                             // 이전 상자·경로를 새 결과로 오해하지 않게 지운다
    onFound?.(null);
    try {
      const jpeg = await shrink(file).catch(() => null);      // 맥 Chrome은 HEIC를 못 연다
      const image = jpeg ?? (enabled ? await rawDataUrl(file) : null);
      const framing = enabled && image ? photoFrame(image) : Promise.resolve(null);   // Claude를 기다리는 동안 함께 계산
      let found: Found;
      if (jpeg && apiKey) {
        found = { ...(await askClaudeBoxes(apiKey, jpeg)), photo: jpeg };
      } else if (enabled && image) {
        found = await viaServer(image, jpeg);
      } else {
        throw new Error("이 브라우저는 이 사진 형식(HEIC)을 열지 못합니다. Safari를 쓰거나 맥 서버에 접속한 화면에서 보내세요.");
      }
      const boxes = found.boxes.map(boxStyle).filter((b): b is BoxStyle => b !== null);
      if (boxes.length !== found.boxes.length) throw new Error("상자 위치가 올바르지 않습니다.");
      setView({ url: jpegUrl(found.photo), boxes, note: found.note, secs: found.secs, frame: await framing });
      if (found.arms) onFound?.({ arms: found.arms, usable: found.usable });
    } catch (e) {
      if (e instanceof KeyError) { writeKey(""); setApiKey(""); }
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const picker = (ref: React.RefObject<HTMLInputElement | null>, capture: boolean) => (
    <input ref={ref} type="file" accept="image/*" hidden {...(capture ? { capture: "environment" as const } : {})}
      onChange={(e) => { analyze(e.target.files?.[0]); e.target.value = ""; }} />
  );
  const n = view?.boxes.length ?? 0;
  const locked = busy || (!apiKey && !enabled);

  return (
    <section>
      <div className="sec-h"><h2>눈 위치 표시</h2><small>사진에서 눈이 있는 곳을 AI가 상자로 표시합니다. 표시만 하고 제설차는 움직이지 않습니다.</small></div>

      {apiKey ? (
        <div className={styles.keyRow}>
          <span className="st on">Claude API 키 저장됨 · 바로 보냄</span>
          <button className="btn" type="button" onClick={() => { writeKey(""); setApiKey(""); }}>키 지우기</button>
        </div>
      ) : (
        <form className={styles.keyForm} onSubmit={saveKey}>
          <label htmlFor="claude-key" className={styles.keyLabel}>Claude API 키</label>
          <input id="claude-key" className={styles.keyInput} type="password" value={draft} onChange={(e) => setDraft(e.target.value)}
            autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} placeholder="sk-ant-…" />
          <button className="btn dark" type="submit">저장</button>
        </form>
      )}
      <p className="vhint">
        {apiKey ? "키는 이 기기의 브라우저에만 있고, 사진을 Claude에 바로 보냅니다. 다른 사람과 쓰는 기기라면 끝나고 키를 지우세요."
          : enabled ? "키가 없으면 맥 서버를 거쳐 보냅니다. 키를 넣으면 맥 서버나 같은 Wi-Fi 없이 바로 보냅니다."
          : "맥 서버에 닿지 않습니다. Claude API 키를 넣으면 바로 보낼 수 있습니다."}
      </p>

      <div className="vbtns">
        <button className="btn dark xl" type="button" disabled={locked} onClick={() => camera.current?.click()}>눈 사진 찍기</button>
        <button className="btn xl" type="button" disabled={locked} onClick={() => album.current?.click()}>앨범에서 고르기</button>
      </div>
      {picker(camera, true)}
      {picker(album, false)}

      <div role="status">
        {busy ? <p className="empty">AI가 사진에서 눈을 찾는 중…</p> : view && (
          <p className={`${styles.head} ${n ? styles.found : ""}`}>
            <b>{n ? `눈 ${n}곳` : "눈이 보이지 않습니다"}</b>
            {view.note && <span className={styles.note}>{view.note}</span>}
            {view.secs !== null && <span className={styles.note}>· {view.secs.toFixed(1)}초</span>}
          </p>
        )}
      </div>
      {error && <p className="verr" role="alert">{error}</p>}

      {view && (
        <div className={styles.frame}>
          <img className={styles.photo} src={view.url} alt={n ? `눈이 있는 ${n}곳을 상자로 표시한 사진` : "눈이 보이지 않는 사진"} />
          {view.boxes.map((b, i) => (
            <span key={i} className={styles.box} style={b} role="img" aria-label={`눈 ${i + 1}`}>
              <span className={styles.tag} aria-hidden>{i + 1}</span>
            </span>
          ))}
          {route && view.frame && <RouteOnPhoto route={route} frame={view.frame} />}
        </div>
      )}
      {view && route && !view.frame && (
        <p className="vhint">사진 위 경로는 노란 코트가 보이게 위에서 찍은 사진에만 그립니다(맥 서버 필요). 경로는 결과 지도에서 보세요.</p>
      )}
    </section>
  );
}
