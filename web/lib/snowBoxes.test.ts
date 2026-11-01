import assert from "node:assert/strict";
import test from "node:test";
import { boxStyle } from "./snowBoxes.ts";

test("비율 상자는 사진 크기와 무관한 퍼센트 위치가 된다", () => {
  assert.deepEqual(boxStyle({ x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.6 }), { left: "10%", top: "20%", width: "40%", height: "40%" });
});

test("뒤집힌 모서리는 바로잡고, 사진 밖은 안으로 자른다", () => {
  assert.deepEqual(boxStyle({ x0: 0.5, y0: 0.6, x1: 0.1, y1: 0.2 }), { left: "10%", top: "20%", width: "40%", height: "40%" });
  assert.deepEqual(boxStyle({ x0: -0.2, y0: 0.5, x1: 1.3, y1: 0.9 }), { left: "0%", top: "50%", width: "100%", height: "40%" });
});

test("숫자가 아닌 좌표는 버리지 않고 null로 알린다(눈이 없다고 오해하지 않게)", () => {
  assert.equal(boxStyle({ x0: null, y0: 0, x1: 1, y1: 1 } as never), null);
  assert.equal(boxStyle({ x0: 0, y0: 0, x1: Number.NaN, y1: 1 }), null);
});
