import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ASK, BOXES_SCHEMA, BOXES_SYSTEM, MAX_BOXES, MODEL, tidyBoxes } from "./claudeBoxes.ts";

const PY = `import json, sys
sys.path.insert(0, "..")
from server import claude_vision as cv
print(json.dumps({"system": cv.BOXES_SYSTEM, "schema": cv.BOXES_SCHEMA, "model": cv.MODEL, "max": cv.MAX_BOXES}))`;

test("화면이 직접 부를 때도 서버와 같은 지시문·스키마·모델을 쓴다", () => {
  const r = spawnSync("/usr/bin/python3", ["-c", PY], { encoding: "utf8" });
  assert.equal(r.status, 0, r.stderr);
  const server = JSON.parse(r.stdout);
  assert.equal(BOXES_SYSTEM, server.system, "server/claude_vision.py의 BOXES_SYSTEM이 바뀌면 claudeBoxes.ts도 같이 고친다");
  assert.deepEqual(BOXES_SCHEMA, server.schema);
  assert.equal(MODEL, server.model);
  assert.equal(MAX_BOXES, server.max);
  assert.ok(readFileSync("../server/claude_vision.py", "utf8").includes(`ask = "${ASK}"`), "질문 문장도 서버와 같다");
});

test("Claude가 준 상자는 0..1 안으로 자르고 모서리 순서를 맞춘다", () => {
  assert.deepEqual(tidyBoxes([{ x0: 0.6, y0: 0.5, x1: 0.2, y1: -0.1 }, { x0: -1, y0: "x", x1: 2, y1: 1.5 }]),
    [{ x0: 0.2, y0: 0, x1: 0.6, y1: 0.5 }, { x0: 0, y0: 0, x1: 1, y1: 1 }]);
  assert.equal(tidyBoxes(Array.from({ length: 40 }, () => ({ x0: 0, y0: 0, x1: 0.1, y1: 0.1 }))).length, MAX_BOXES);
  assert.throws(() => tidyBoxes(undefined));
});
