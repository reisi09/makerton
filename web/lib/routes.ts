// AI가 찾은 갈래별 눈 → 최적 경로 표(routeTable.json)의 키. 표는 tools/make_route_table.py가 server/route.py plan()으로 만든다.

export interface PlannedRoute { order: string[]; seconds: number; tried: number; worst_seconds: number; path: [number, number, number][] }

/** 보드 좌표(mm) → 사진 너비·높이 비율(0..1)의 아핀 [a, b, c, d, e, f]. 맥 서버 /api/vision/frame이 사진 속 도로 십자로 맞춘다. */
export type Frame = [number, number, number, number, number, number];
export const onPhoto = ([a, b, c, d, e, f]: Frame, x: number, y: number): [number, number] => [a * x + b * y + c, d * x + e * y + f];

const OUTWARD: Record<string, [number, number]> = { N: [0, -1], E: [1, 0], S: [0, 1], W: [-1, 0] };
/** 경로에서 그 갈래 쪽으로 가장 멀리 간 자리(눈을 끝까지 민 곳). 사진 위에 도는 순서 번호를 단다. */
export function armTip(path: PlannedRoute["path"], arm: string): [number, number] {
  const [dx, dy] = OUTWARD[arm];
  const tip = path.reduce((best, p) => (p[0] * dx + p[1] * dy > best[0] * dx + best[1] * dy ? p : best));
  return [tip[0], tip[1]];
}

/** 눈이 있는 갈래를 N·E·S·W 순서로 이은 키. 교차로에만 눈이 있으면 "C", 눈이 없으면 null.
 *  사진으로 판단하기 어려우면(usable=false) 네 갈래 모두("NESW"): 판단이 애매하면 다 치운다는 원칙. */
export function routeKey(arms: Record<string, boolean>, usable: boolean): string | null {
  if (!usable) return "NESW";
  const key = ["N", "E", "S", "W"].filter((a) => arms[a]).join("");
  if (key) return key;
  return arms.C ? "C" : null;
}
