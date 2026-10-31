import assert from "node:assert/strict";
import { test } from "node:test";
import { addHours, decide, freezeProb, type Step } from "./rules.ts";

const base = { running: false, snow: false, t: "2025-12-29T21:00:00", restUntil: null, p: 0.2, threshold: 0.5 };

test("눈 감지는 쉬는 중이어도 바로 출동한다", () => {
  assert.deepEqual(decide({ ...base, snow: true, restUntil: "2025-12-30T00:00:00" }), { kind: "snow" });
});

test("모델 출동은 문턱 이상이고 쉬는 중이 아닐 때만", () => {
  assert.equal(decide(base), null);
  assert.deepEqual(decide({ ...base, p: 0.79 }), { kind: "model", p: 0.79 });
  assert.equal(decide({ ...base, p: 0.79, restUntil: "2025-12-29T22:00:00" }), null);
  assert.deepEqual(decide({ ...base, p: 0.79, restUntil: "2025-12-29T21:00:00" }), { kind: "model", p: 0.79 }); // 3시간이 다 찼다
});

test("출동 중에는 아무것도 하지 않는다", () => {
  assert.equal(decide({ ...base, running: true, snow: true, p: 1 }), null);
});

test("확률은 +1·+3·+6시간 중 최대, 시간 더하기는 날짜를 넘긴다", () => {
  const step = { p: { h1: [0.07, 0.1], h3: [0.44, 0.5], h6: [0.79, 0.9] } } as unknown as Step;
  assert.equal(freezeProb(step, 0), 0.79);
  assert.equal(addHours("2025-12-29T22:00:00", 3), "2025-12-30T01:00:00");
});
