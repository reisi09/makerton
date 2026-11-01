// 조작 화면이 Claude API를 직접 부른다(맥 서버나 같은 Wi-Fi가 없어도 된다). API 키는 화면에서 입력받아 그 기기의 브라우저에만 둔다.
// 지시문·스키마는 server/claude_vision.py의 BOXES_SYSTEM·BOXES_SCHEMA와 같아야 한다(claudeBoxes.test.ts가 확인한다).
import Anthropic from "@anthropic-ai/sdk";
import type { SnowBox } from "./snowBoxes.ts";

export const MODEL = "claude-opus-5-5";
export const MAX_BOXES = 30;
export const ASK = "눈이 있는 곳을 상자로 표시해 주세요. 생각은 한국어로 해 주세요.";
export const BOXES_SYSTEM = "You mark where the snow is on photos of a tabletop model city used in a snow-removal robot demo.\n\nThe board is about 925 x 910 mm. Black roads 135 mm wide form one plus-shaped intersection. The roads have yellow dashed centerlines and the intersection square has a yellow outline. Clear tape covers the paint.\n\nSnow is small white styrofoam beads, a few millimetres across, lying on the black road surface. Count it even when there are only a few beads.\nNot snow: bright glare streaks from the tape over the yellow paint (thin, long, along a centerline or the intersection outline), white buildings and roofs, signs, the floor or table outside the board, and anything off the black road.\nAlso not snow, even when it sits on a road: the snow-plow robot car itself (a white styrofoam body about 230 x 150 mm with a breadboard, colored wires, small circuit boards, bottle-cap wheels, purple dowels and a white blade at one end), and a MacBook or other laptop, phone, cable or hand on or next to the board. Only small loose beads are snow; a large white object is never snow, and beads lying on the car are not road snow.\n\nTask: draw bounding boxes around the snow, one box per cluster of beads. Merge beads that lie within about 20 mm of each other (roughly a seventh of the road width) into one box. Put boxes only around beads on the black road, never around glare, buildings, signs or the floor. At most 30 boxes; when there is more snow than that, merge the nearest clusters. When there is no snow, return an empty list.\nCoordinates are fractions of the photo exactly as you see it, without rotating it: x is 0 at the left edge and 1 at the right edge, y is 0 at the top edge and 1 at the bottom edge. x0,y0 is the top-left corner and x1,y1 the bottom-right corner. Fit each box tightly around its beads with a small margin.\nThink in Korean. note: one or two short Korean sentences on where you found snow, for display to the operator.";
export const BOXES_SCHEMA = {
  type: "object",
  properties: {
    boxes: {
      type: "array",
      items: {
        type: "object",
        properties: { x0: { type: "number" }, y0: { type: "number" }, x1: { type: "number" }, y1: { type: "number" } },
        required: ["x0", "y0", "x1", "y1"],
        additionalProperties: false,
      },
    },
    note: { type: "string" },
  },
  required: ["boxes", "note"],
  additionalProperties: false,
};

/** API 키가 틀렸을 때. 화면은 저장한 키를 지우고 다시 받는다. */
export class KeyError extends Error {}

const frac = (v: unknown) => { const n = Number(v); return Number.isNaN(n) ? 0 : Math.min(1, Math.max(0, n)); };

/** Claude가 준 상자를 0..1 안으로 자르고 모서리 순서를 맞춘다(최대 MAX_BOXES개). 서버의 boxes()와 같은 규칙. */
export function tidyBoxes(raw: unknown): SnowBox[] {
  if (!Array.isArray(raw)) throw new Error("Claude 응답에 상자 목록이 없습니다.");
  return raw.slice(0, MAX_BOXES).map((b) => {
    const [x0, x1] = [frac(b?.x0), frac(b?.x1)].sort((a, c) => a - c);
    const [y0, y1] = [frac(b?.y0), frac(b?.y1)].sort((a, c) => a - c);
    return { x0, y0, x1, y1 };
  });
}

/** JPEG data URL 한 장 → Claude가 찾은 눈 상자. 브라우저에서 바로 부르므로 키는 이 기기에 있는 것만 쓴다. */
export async function askClaudeBoxes(apiKey: string, jpegDataUrl: string): Promise<{ boxes: SnowBox[]; note: string; secs: number }> {
  const client = new Anthropic({ apiKey, dangerouslyAllowBrowser: true, maxRetries: 1, timeout: 90_000 });
  const t0 = performance.now();
  let r: Anthropic.Message;
  try {
    r = await client.messages.create({
      model: MODEL,
      max_tokens: 16000,
      system: BOXES_SYSTEM,
      output_config: { effort: "medium", format: { type: "json_schema", schema: BOXES_SCHEMA } },
      messages: [{
        role: "user",
        content: [
          { type: "image", source: { type: "base64", media_type: "image/jpeg", data: jpegDataUrl.split(",", 2)[1] } },
          { type: "text", text: ASK },
        ],
      }],
    });
  } catch (e) {
    if (e instanceof Anthropic.AuthenticationError) throw new KeyError("Claude API 키가 맞지 않습니다.");
    if (e instanceof Anthropic.RateLimitError) throw new Error("Claude 요청이 너무 많습니다. 잠시 뒤 다시 하세요.");
    if (e instanceof Anthropic.APIConnectionError) throw new Error("Claude API에 연결하지 못했습니다. 인터넷 연결을 확인하세요.");
    if (e instanceof Anthropic.APIError) throw new Error(`Claude API 오류 ${e.status ?? ""}`.trim());
    throw e;
  }
  if (r.stop_reason !== "end_turn") throw new Error(`Claude 응답이 끝나지 않았습니다(${r.stop_reason}).`);
  const text = r.content.map((b) => (b.type === "text" ? b.text : "")).join("");
  const out = JSON.parse(text);
  return { boxes: tidyBoxes(out.boxes), note: String(out.note ?? ""), secs: Math.round((performance.now() - t0) / 100) / 10 };
}
