import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { armTip, onPhoto, routeKey, type Frame } from "./routes.ts";

const table = JSON.parse(readFileSync(new URL("./routeTable.json", import.meta.url), "utf8"));

test("AI가 찾은 갈래로 표의 최적 경로를 고른다", () => {
  assert.equal(routeKey({ C: true, N: false, E: true, S: true, W: false }, true), "ES");
  assert.equal(routeKey({ C: true, N: false, E: false, S: false, W: false }, true), "C", "교차로만 눈이면 가장 빠른 갈래로 밀어낸다");
  assert.equal(routeKey({ C: false, N: false, E: false, S: false, W: false }, true), null, "눈이 없으면 경로도 없다");
  assert.equal(routeKey({ C: false, N: false, E: false, S: false, W: false }, false), "NESW", "판단이 애매하면 네 갈래 모두");
  for (const [key, plan] of Object.entries(table) as [string, { order: string[] }][]) {
    const want = key === "C" ? plan.order : key.split("");
    assert.equal(plan.order.length, want.length, `${key}: 갈래 수`);
    assert.deepEqual([...plan.order].sort(), [...want].sort(), `${key}: 표의 순서가 그 갈래들만 돈다`);
  }
  assert.equal(table.C.order.length, 1, "교차로만 눈이면 갈래 하나로 밀어낸다");
});

test("경로를 사진 위로 옮기고 갈래 끝에 순서 번호 자리를 잡는다", () => {
  // 사진 1px = 1mm로 90° 돌려 찍은 경우: 보드 (x, y) → 사진 (1 - y/910, x/925)
  const frame: Frame = [0, -1 / 910, 1, 1 / 925, 0, 0];
  assert.deepEqual(onPhoto(frame, 0, 0), [1, 0]);
  assert.deepEqual(onPhoto(frame, 925, 910), [0, 1]);
  const path = table.NESW.path;
  assert.deepEqual(path[0].slice(0, 2), [764, 250], "경로는 차고 안에서 출발한다");
  const tip = (a: string) => armTip(path, a);
  assert.ok(tip("N")[1] < 150 && tip("S")[1] > 750 && tip("E")[0] > 780 && tip("W")[0] < 150, JSON.stringify(["N", "E", "S", "W"].map(tip)));
  for (const a of ["N", "S"]) assert.equal(tip(a)[0], 582, `${a} 끝은 세로 도로 가운데`);
  for (const a of ["E", "W"]) assert.equal(tip(a)[1], 480, `${a} 끝은 가로 도로 가운데`);
});
