import assert from "node:assert/strict";
import test from "node:test";
import { padUrl } from "./vision.ts";

test("패드 주소는 맥 IP로 만들고, 루프백이면 없다", () => {
  assert.equal(padUrl("http://172.20.10.3:8000/monitor", "/app"), "http://172.20.10.3:8000/app/vision/");
  assert.equal(padUrl("http://127.0.0.1:8000/monitor", "/app"), null);
  assert.equal(padUrl("", "/app"), null);
});
