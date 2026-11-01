// 눈 상자 표시의 순수 계산. 서버가 주는 상자는 사진 가로·세로에 대한 0~1 비율이다.

export interface SnowBox { x0: number; y0: number; x1: number; y1: number }
export interface BoxStyle { left: string; top: string; width: string; height: string }

const clamp = (v: number) => Math.min(1, Math.max(0, v));
const pct = (v: number) => `${+(v * 100).toFixed(2)}%`;

/** 비율 상자 → 사진 위에 얹을 퍼센트 위치. 숫자가 아닌 값이 있으면 null, 사진 밖은 안으로 자르고, 뒤집힌 모서리는 바로잡는다. */
export function boxStyle(b: SnowBox): BoxStyle | null {
  if (![b.x0, b.y0, b.x1, b.y1].every((v) => typeof v === "number" && Number.isFinite(v))) return null;
  const x0 = clamp(Math.min(b.x0, b.x1)), x1 = clamp(Math.max(b.x0, b.x1));
  const y0 = clamp(Math.min(b.y0, b.y1)), y1 = clamp(Math.max(b.y0, b.y1));
  return { left: pct(x0), top: pct(y0), width: pct(x1 - x0), height: pct(y1 - y0) };
}
