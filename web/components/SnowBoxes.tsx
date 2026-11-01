"use client";

import { useEffect, useId, useRef, useState } from "react";
import { boxStyle, type BoxStyle, type SnowBox } from "@/lib/snowBoxes";
import styles from "./SnowBoxes.module.css";

const MAX_SIDE = 1600; // 올리기 전에 줄인다(12MP 사진을 그대로 보내지 않는다)
const KEY_STORE = "makerton-key";

interface Reply { boxes?: SnowBox[]; note?: string; secs?: number; error?: string }
interface View { url: string; boxes: BoxStyle[]; note: string; secs: number | null }

// 저장소가 막힌 브라우저(사생활 보호 창 등)에서는 새로고침 전까지만 키를 기억한다.
const readKey = () => { try { return sessionStorage.getItem(KEY_STORE) ?? ""; } catch { return ""; } };
const writeKey = (k: string) => { try { if (k) sessionStorage.setItem(KEY_STORE, k); else sessionStorage.removeItem(KEY_STORE); } catch { /* 무시 */ } };

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

const jpegUrl = (dataUrl: string) =>
  URL.createObjectURL(new Blob([Uint8Array.from(atob(dataUrl.split(",")[1]), (c) => c.charCodeAt(0))], { type: "image/jpeg" }));

/** 사진을 찍으면 AI가 눈이 있는 곳을 상자로 표시한다. 표시 전용이며 제설차를 움직이지 않는다.
 *  enabled가 false면(맥 서버가 없는 GitHub 페이지 등) 보안키를 받지도, 사진을 보내지도 않는다. 키가 엉뚱한 곳으로 가지 않게 한다. */
export default function SnowBoxes({ enabled }: { enabled: boolean }) {
  const [key, setKey] = useState("");          // "" = 아직 입력 전
  const [draft, setDraft] = useState("");
  const [keyMsg, setKeyMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<View | null>(null);
  const keyInput = useRef<HTMLInputElement>(null);
  const focusKey = useRef(false);
  const camera = useRef<HTMLInputElement>(null);
  const album = useRef<HTMLInputElement>(null);
  const id = useId();

  useEffect(() => setKey(readKey()), []);      // 정적 내보내기라 서버 렌더에는 저장소가 없다
  useEffect(() => {                            // 키를 다시 받아야 할 때 입력칸으로 커서를 옮긴다
    if (!key && focusKey.current) { focusKey.current = false; keyInput.current?.focus(); }
  }, [key]);
  useEffect(() => () => { if (view) URL.revokeObjectURL(view.url); }, [view]);

  function askKeyAgain(msg: string) {
    writeKey("");
    focusKey.current = true;
    setKey("");
    setKeyMsg(msg);
  }

  function saveKey(e: React.FormEvent) {
    e.preventDefault();
    const k = draft.trim();
    if (!k) return;
    // 헤더에는 영문·숫자·기호만 실을 수 있다. 한글 입력기가 켜진 채로 입력한 경우를 알려 준다.
    if (/[^\x20-\x7e]/.test(k)) { setKeyMsg("보안키에 쓸 수 없는 글자가 있습니다. 키보드를 영문으로 바꿔 다시 입력하세요."); return; }
    writeKey(k);
    setKey(k);
    setDraft("");
    setKeyMsg("");
  }

  async function analyze(file: File | undefined) {
    if (!enabled || !file || !key || busy) return;
    setBusy(true);
    setError("");
    setView(null);                             // 이전 상자를 새 결과로 오해하지 않게 지운다
    try {
      const image = await shrink(file);
      let r: Response;
      try {
        r = await fetch("/api/vision/boxes", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Makerton-Key": key },
          body: JSON.stringify({ image }),
        });
      } catch {
        throw new Error("서버에 연결하지 못했습니다. 같은 핫스팟에 연결돼 있는지, 맥에서 서버가 켜져 있는지 확인하세요.");
      }
      const data: Reply | null = await r.json().catch(() => null);
      if (r.status === 401) { askKeyAgain("보안키가 맞지 않습니다"); return; }
      if (!r.ok) throw new Error(data?.error ?? `서버 오류 ${r.status}`);
      // 응답을 읽지 못했는데 '눈이 보이지 않습니다'로 보이면 안 된다.
      if (!Array.isArray(data?.boxes)) throw new Error("서버 응답을 읽지 못했습니다.");
      const boxes = data.boxes.map(boxStyle).filter((b): b is BoxStyle => b !== null);
      if (boxes.length !== data.boxes.length) throw new Error("서버가 보낸 상자 위치가 올바르지 않습니다.");
      setView({ url: jpegUrl(image), boxes, note: data.note ?? "", secs: typeof data.secs === "number" ? data.secs : null });
    } catch (e) {
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
  const locked = !enabled || !key || busy;

  return (
    <section>
      <div className="sec-h"><h2>눈 위치 표시</h2><small>사진에서 눈이 있는 곳을 AI가 상자로 표시합니다. 표시만 하고 제설차는 움직이지 않습니다.</small></div>

      {!enabled ? (
        <p className="vhint">맥 서버에 접속한 화면에서만 쓸 수 있습니다. 보안키도 그때 입력합니다.</p>
      ) : key ? (
        <div className={styles.keyRow}>
          <span className="st on">보안키 입력됨</span>
          <button className="btn" type="button" onClick={() => askKeyAgain("")}>다시 입력</button>
        </div>
      ) : (
        <form className={styles.keyForm} onSubmit={saveKey}>
          <label htmlFor={`${id}-key`} className={styles.keyLabel}>보안키</label>
          <input id={`${id}-key`} ref={keyInput} className={styles.keyInput} type="password" value={draft}
            onChange={(e) => setDraft(e.target.value)} autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false}
            aria-invalid={!!keyMsg} aria-describedby={keyMsg ? `${id}-msg` : undefined} />
          <button className="btn dark" type="submit">확인</button>
        </form>
      )}
      {enabled && keyMsg && <p id={`${id}-msg`} className="verr" role="alert">{keyMsg}</p>}
      {enabled && !key && <p className="vhint">보안키를 입력해야 사진을 보낼 수 있습니다.</p>}

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
        </div>
      )}
    </section>
  );
}
