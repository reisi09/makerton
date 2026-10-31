// 패드 사진 화면의 순수 계산.

export const ARM_NAMES: Record<string, string> = { C: "교차로", N: "N 갈래", S: "S 갈래", E: "E 갈래", W: "W 갈래" };

/** 서버가 알려 주는 모니터 주소(http://<맥 IP>:8000/monitor) → 패드가 열 주소. 이 노트북 주소면 쓸 수 없다. */
export function padUrl(monitorUrl: string, base: string): string | null {
  try {
    const u = new URL(monitorUrl);
    if (u.hostname === "127.0.0.1" || u.hostname === "localhost") return null;
    return `${u.origin}${base}/vision/`;
  } catch {
    return null;
  }
}
