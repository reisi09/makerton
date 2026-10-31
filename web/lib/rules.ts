// 재생 자료 형식(tools/export_demo.py)과 출동 규칙(server/gosaek_server.py _maybe_auto_dispatch와 같다).

export type Horizon = "h1" | "h3" | "h6";
export const HORIZONS: Horizon[] = ["h1", "h3", "h6"];

export interface Step {
  t: string;
  obs: { temp: number | null; ground_temp: number | null; humidity: number | null; wind: number | null; snow: number | null };
  fc: { h0: number; h1: number; h3: number; h6: number };
  truth: Record<Horizon, number | null>;
  p: Record<Horizon, (number | null)[]>;
}

export interface Night { night: string; t18: number | null; t_min: number | null; freezing: boolean; steps: Step[] }

export interface Replay {
  generated: string;
  station: string;
  model: { rmse: Record<string, number>; persistence_rmse: Record<string, number> };
  dt_grid: number[];
  threshold: number;
  nights: Night[];
}

export const REST_HOURS = 3; // 한 번 치우면 이만큼은 모델 출동을 쉰다(서버 처리 효과 3시간)

/** 현장 보정 dtIndex에서 +1·+3·+6시간 동결확률 중 가장 큰 값. */
export function freezeProb(step: Step, dtIndex: number): number {
  return Math.max(...HORIZONS.map((h) => step.p[h][dtIndex] ?? 0));
}

export function addHours(t: string, hours: number): string {
  const d = new Date(t + "Z");
  d.setUTCHours(d.getUTCHours() + hours);
  return d.toISOString().slice(0, 19);
}

export type Decision = { kind: "snow" } | { kind: "model"; p: number } | null;

/** 눈 감지면 바로, 아니면 쉬는 중이 아니고 확률이 문턱 이상일 때 출동한다. */
export function decide(s: { running: boolean; snow: boolean; t: string; restUntil: string | null; p: number; threshold: number }): Decision {
  if (s.running) return null;
  if (s.snow) return { kind: "snow" };
  if (s.restUntil && s.t < s.restUntil) return null;
  return s.p >= s.threshold ? { kind: "model", p: s.p } : null;
}
