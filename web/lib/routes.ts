// AI가 찾은 갈래별 눈 → 최적 경로 표(routeTable.json)의 키. 표는 tools/make_route_table.py가 server/route.py plan()으로 만든다.

export interface PlannedRoute { order: string[]; seconds: number; tried: number; worst_seconds: number; path: [number, number, number][] }

/** 눈이 있는 갈래를 N·E·S·W 순서로 이은 키. 교차로에만 눈이 있으면 "C", 눈이 없으면 null.
 *  사진으로 판단하기 어려우면(usable=false) 네 갈래 모두("NESW"): 판단이 애매하면 다 치운다는 원칙. */
export function routeKey(arms: Record<string, boolean>, usable: boolean): string | null {
  if (!usable) return "NESW";
  const key = ["N", "E", "S", "W"].filter((a) => arms[a]).join("");
  if (key) return key;
  return arms.C ? "C" : null;
}
