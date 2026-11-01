// 실제 모형 평면(2026-10-31 사진 실측, 단위 mm 그대로). 보드 925×910, 도로 폭 135, 교차로 중심 (582, 480).
// 건물과 색은 사진을 보고 그렸다: 북서 4동(파란 창), 공원, 북동 제설 기지(서쪽 출입구), 남서 H자 건물·노란 코트, 축구장, 남동 경사 지붕 건물·고색역 표지판.

import type { ReactElement } from "react";

export type Pose = [number, number, number];
export interface Arm { area_mm2: number; far_mm: number }

const CX = 582, CY = 480, RX0 = 515, RX1 = 650, RY0 = 404, RY1 = 552;
const ARM_END: Record<string, [number, number]> = { N: [CX, 70], E: [880, CY], S: [CX, 860], W: [60, CY] };
const INK = "#212529", GREY = "#495057", EDGE = "#adb5bd", SHADOW = "#ced4da", ROOF = "#e9ecef", WHITE = "#ffffff", BOARD = "#f1f3f5";
const ROAD = "#2b2f33", LANE = "#f2c230", WINDOW = "#2f8fd0", GRASS = "#40a34f", GRASS_D = "#2b7a3a", TREE = "#2f8a3e";
const BENCH = "#e8892b", FLOWER = "#f06595", COURT = "#f5c430", COURT_D = "#d9a514", GOAL_L = "#9c6b30", GOAL_R = "#2f6fd6";
const FIELD = "#2f9e44", SIGN = "#1f6fd6", SIGN_D = "#174ea6", GARAGE = "#dbe7f3", CAR = "#f76707", CAR_D = "#c2410c", SNOW_EDGE = "#4dabf7";

function Tower({ x, y, w, h }: { x: number; y: number; w: number; h: number }) {
  const cols = 3, rows = 4, gw = (w - 28) / cols, gh = (h - 28) / rows;
  return (
    <g>
      <rect x={x + 6} y={y + 6} width={w} height={h} rx="8" fill={SHADOW} />
      <rect x={x} y={y} width={w} height={h} rx="8" fill={WHITE} stroke={EDGE} strokeWidth="3" />
      {Array.from({ length: cols * rows }, (_, i) => (
        <rect key={i} x={x + 14 + (i % cols) * gw + 3} y={y + 14 + Math.floor(i / cols) * gh + 3} width={gw - 6} height={gh - 8} rx="2" fill={WINDOW} />
      ))}
    </g>
  );
}

function Snow({ arms, min }: { arms: Record<string, Arm>; min: number }) {
  // 갈래 눈 면적만큼 흰 점을 찍는다(위치는 고정 난수). 인식 결과를 지도에서 바로 보이게 한다.
  const dots: ReactElement[] = [];
  for (const a of ["C", "N", "E", "S", "W"]) {
    const area = arms[a]?.area_mm2 ?? 0;
    const n = Math.min(26, Math.round(area / 30));
    for (let i = 0; i < n; i++) {
      const r1 = ((i * 73 + a.charCodeAt(0) * 31) % 97) / 97, r2 = ((i * 41 + a.charCodeAt(0) * 17) % 89) / 89;
      let x = CX, y = CY;
      if (a === "C") { x = RX0 + 12 + r1 * (RX1 - RX0 - 24); y = RY0 + 12 + r2 * (RY1 - RY0 - 24); }
      if (a === "N") { x = RX0 + 12 + r1 * (RX1 - RX0 - 24); y = 20 + r2 * (RY0 - 40); }
      if (a === "S") { x = RX0 + 12 + r1 * (RX1 - RX0 - 24); y = RY1 + 20 + r2 * (890 - RY1 - 20); }
      if (a === "E") { x = RX1 + 20 + r1 * (905 - RX1 - 20); y = RY0 + 12 + r2 * (RY1 - RY0 - 24); }
      if (a === "W") { x = 20 + r1 * (RX0 - 40); y = RY0 + 12 + r2 * (RY1 - RY0 - 24); }
      dots.push(<circle key={`${a}${i}`} cx={x} cy={y} r={area >= min ? 7 : 5} fill={WHITE} stroke={SNOW_EDGE} strokeWidth="2" />);
    }
  }
  return <g>{dots}</g>;
}

export default function BoardMap({ arms, min = 100, path, upto, order, car }: {
  arms?: Record<string, Arm>; min?: number; path?: Pose[]; upto?: number; order?: string[]; car?: Pose;
}) {
  // car는 제설차가 보내는 실제 위치다. 없으면(차 연결 끊김) 경로의 upto번째 자세, 그것도 없으면 차고에 둔다.
  const pose: Pose = car ?? (path && path.length ? path[Math.min(path.length - 1, Math.max(0, upto ?? 0))] : [764, 250, 270]);
  const done = path && upto != null ? path.slice(0, upto + 1) : [];
  const line = (pts: Pose[]) => pts.map(([x, y]) => `${x},${y}`).join(" ");
  return (
    <svg className="map" viewBox="0 0 925 910" role="img"
      aria-label={`사거리 모형 지도${order?.length ? `, 최적 순서 ${order.join(" 다음 ")}` : ""}`}>
      <rect width="925" height="910" rx="24" fill={BOARD} />

      {/* 북서: 파란 창이 있는 4동 */}
      <Tower x={20} y={20} w={128} h={150} /><Tower x={160} y={20} w={128} h={150} />
      <Tower x={20} y={190} w={128} h={158} /><Tower x={160} y={190} w={128} h={158} />

      {/* 공원: 잔디·나무·주황 벤치·꽃 */}
      <path d="M330 60 C380 40 430 70 430 130 C430 190 470 240 462 310 C455 380 330 392 310 330 C292 270 352 220 340 160 C332 120 300 80 330 60 Z" fill={GRASS} stroke={GRASS_D} strokeWidth="3" />
      {[[372, 120], [400, 220], [350, 300], [430, 330]].map(([x, y]) => <circle key={`${x}${y}`} cx={x} cy={y} r="20" fill={TREE} stroke={GRASS_D} strokeWidth="3" />)}
      {[[392, 268], [420, 286], [376, 340]].map(([x, y]) => <circle key={`f${x}${y}`} cx={x} cy={y} r="6" fill={FLOWER} />)}
      <rect x="350" y="70" width="56" height="16" rx="4" fill={BENCH} />

      {/* 북동: 제설 기지. 서쪽 면에 출입구(N 도로 쪽) */}
      <rect x="696" y="26" width="219" height="324" rx="10" fill={SHADOW} />
      <path d="M690 180 L690 20 L909 20 L909 344 L690 344 L690 320" fill={WHITE} stroke={GREY} strokeWidth="4" strokeLinejoin="round" />
      <rect x="690" y="180" width="160" height="140" fill={GARAGE} />
      <line x1="690" y1="180" x2="690" y2="320" stroke={GREY} strokeWidth="4" strokeDasharray="10 8" />
      <text x="800" y="96" textAnchor="middle" fontSize="38" fontWeight="800" fill={INK}>제설 기지</text>
      <text x="800" y="138" textAnchor="middle" fontSize="24" fontWeight="600" fill={GREY}>출입구 ← N 갈래</text>

      {/* 남서: 노란 코트(양쪽 골대는 안쪽을 향한 ㄷ자)와 H자 건물 */}
      <rect x="16" y="560" width="340" height="146" rx="6" fill={COURT} stroke={COURT_D} strokeWidth="3" />
      <rect x="30" y="600" width="8" height="66" fill={GOAL_L} /><rect x="30" y="600" width="26" height="6" fill={GOAL_L} /><rect x="30" y="660" width="26" height="6" fill={GOAL_L} />
      <rect x="302" y="600" width="8" height="66" fill={GOAL_R} /><rect x="284" y="600" width="26" height="6" fill={GOAL_R} /><rect x="284" y="660" width="26" height="6" fill={GOAL_R} />
      <path d="M16 716 H112 V770 H260 V716 H356 V894 H260 V840 H112 V894 H16 Z" fill={WHITE} stroke={EDGE} strokeWidth="3" />

      {/* 축구장 */}
      <rect x="383" y="560" width="125" height="192" rx="4" fill={FIELD} />
      <rect x="392" y="569" width="107" height="174" fill="none" stroke={WHITE} strokeWidth="4" />
      <line x1="392" y1="656" x2="499" y2="656" stroke={WHITE} strokeWidth="4" />
      <circle cx="445" cy="656" r="22" fill="none" stroke={WHITE} strokeWidth="4" />

      {/* 남동: 경사 지붕 건물과 고색역 표지판 */}
      <rect x="751" y="676" width="158" height="204" rx="8" fill={SHADOW} />
      <rect x="745" y="670" width="158" height="204" rx="8" fill={WHITE} stroke={EDGE} strokeWidth="3" />
      <path d="M745 772 H903 L903 874 H745 Z" fill={ROOF} />
      <line x1="745" y1="772" x2="903" y2="772" stroke={EDGE} strokeWidth="3" />
      <rect x="722" y="654" width="6" height="18" fill={GREY} /><rect x="776" y="654" width="6" height="18" fill={GREY} />
      <rect x="700" y="610" width="104" height="46" rx="8" fill={SIGN} stroke={SIGN_D} strokeWidth="3" />
      <text x="752" y="643" textAnchor="middle" fontSize="26" fontWeight="800" fill={WHITE}>고색역</text>

      {/* 도로: 실측 폭 135, 노란 중앙선, 교차로 노란 테두리 */}
      <rect x="0" y={RY0} width="925" height={RY1 - RY0} fill={ROAD} />
      <rect x={RX0} y="0" width={RX1 - RX0} height="910" fill={ROAD} />
      {Array.from({ length: 23 }, (_, i) => i * 40).filter((v) => v < RY0 - 10 || v > RY1).map((v) =>
        <rect key={`v${v}`} x={CX - 3} y={v} width="6" height="20" fill={LANE} />)}
      {Array.from({ length: 24 }, (_, i) => i * 40).filter((v) => v < RX0 - 10 || v > RX1).map((v) =>
        <rect key={`h${v}`} x={v} y={CY - 3} width="20" height="6" fill={LANE} />)}
      <rect x={RX0 - 3} y={RY0 + 8} width={RX1 - RX0 + 6} height={RY1 - RY0 - 16} fill="none" stroke={LANE} strokeWidth="4" />

      {arms && <Snow arms={arms} min={min} />}

      {/* 최적 경로: 전체는 흐리게, 지나온 길은 진하게 */}
      {path && <polyline points={line(path)} fill="none" stroke={CAR} strokeWidth="6" strokeDasharray="14 10" opacity=".7" />}
      {done.length > 1 && <polyline points={line(done)} fill="none" stroke={CAR} strokeWidth="8" />}
      {order?.map((a, i) => {
        const [x, y] = ARM_END[a];
        return (
          <g key={a}>
            <circle cx={x} cy={y} r="26" fill={WHITE} stroke={CAR} strokeWidth="5" />
            <text x={x} y={y + 10} textAnchor="middle" fontSize="28" fontWeight="800" fill={INK}>{i + 1}</text>
          </g>
        );
      })}

      {/* 제설차: 도로 폭을 덮는 날이 앞에 붙어 있다 */}
      <g transform={`translate(${pose[0]},${pose[1]}) rotate(${pose[2]})`}>
        <rect x="-62" y="-75" width="124" height="150" rx="16" fill={CAR} stroke={WHITE} strokeWidth="4" />
        <rect x="-40" y="-48" width="80" height="50" rx="8" fill={WHITE} opacity=".85" />
        <rect x="-70" y="-90" width="140" height="14" rx="4" fill={CAR_D} stroke={WHITE} strokeWidth="2" />
      </g>

      {(["N", "E", "S", "W"] as const).map((a, i) => {
        const [x, y, anchor] = ([[RX0 - 16, 46, "end"], [905, RY0 - 16, "end"], [RX0 - 16, 892, "end"], [20, RY0 - 16, "start"]] as const)[i];
        return <text key={a} x={x} y={y} fill={INK} fontSize="36" fontWeight="800" textAnchor={anchor}>{a}</text>;
      })}
    </svg>
  );
}
