# -*- coding: utf-8 -*-
"""tools/fetch_asos.py 시험: 가짜 API 서버 → CSV → kma.read_table, 그리고 결측 표시·튐 QC."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fetch_asos  # noqa: E402

KEY = "test+key/=="
MAKERTON = ROOT
# 달마다 3시각: (시, 기온, 지면온도). -99.0은 결측
HOURS = (("00", "-3.1", "-5.0"), ("01", "-3.4", "-99.0"), ("02", "-3.9", "-5.6"))


def hub_text(month, with_help):
    """kma_sfctm3.php 꼴 응답. help 모드에서는 TS와 TE_005 자리를 바꿔 '설명 순서를 따르는지'를 본다."""
    order = list(fetch_asos.HUB_DEFAULT_ORDER)
    if with_help:
        i, j = order.index("TS"), order.index("TE_005")
        order[i], order[j] = order[j], order[i]
    lines = ["#START7777"]
    if with_help:
        lines += ["#  %d. %-6s : 설명" % (n + 1, name) for n, name in enumerate(order)]
    lines.append("# YYMMDDHHMI STN  WD   WS ...")
    for hh, ta, ts in HOURS:
        vals = {name: "0.0" for name in order}
        vals.update({"TM": month + "01" + hh + "00", "STN": "119", "TA": ta, "TS": ts, "TE_005": "9.9",
                     "RN": "-9.0", "SD_TOT": "-9.0", "HM": "80.0", "WS": "1.2", "SS": "-9.0", "SI": "-9.0",
                     "WW": "-", "CT": "-"})
        lines.append(" ".join(vals[name] for name in order))
    lines.append("#7777END")
    return "\n".join(lines) + "\n"


def dgk_page(month, page):
    d = "%s-%s-01" % (month[:4], month[4:])
    items = [{"stnId": "119", "tm": "%s %s:00" % (d, hh), "ta": ta, "rn": "", "ws": "1.2", "hm": "80",
              "ss": "", "icsr": "", "dsnw": "", "ts": "" if ts == "-99.0" else ts} for hh, ta, ts in HOURS]
    return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                         "body": {"items": {"item": items[(page - 1) * 2:page * 2]}, "totalCount": 3}}}


class FakeApi(BaseHTTPRequestHandler):
    dgk_pages = []

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/dgk":
            if q.get("serviceKey") != [KEY]:
                return self.reply(401, json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
                    "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "returnAuthMsg": "등록되지 않은 서비스키"}}}))
            page = int(q["pageNo"][0])
            FakeApi.dgk_pages.append(page)
            return self.reply(200, json.dumps(dgk_page(q["startDt"][0][:6], page), ensure_ascii=False))
        if q.get("authKey") != [KEY]:
            return self.reply(401, json.dumps({"result": {"status": 401, "message": "유효한 인증키가 아닙니다."}},
                                              ensure_ascii=False))
        assert q["tm1"][0].endswith("0000") and q["tm2"][0].endswith("2300")
        body = hub_text(q["tm1"][0][:6], with_help=(url.path == "/hub"))
        self.reply(200, body, "cp949")  # typ01은 EUC-KR로 올 수 있다

    def reply(self, code, body, encoding="utf-8"):
        data = body.encode(encoding)
        self.send_response(code)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class FetchAsosTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.root = "http://127.0.0.1:%d" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def run_main(self, key, path, provider, out):
        os.environ["KMA_AUTH_KEY"] = key
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fetch_asos.main(["--from", "2025", "--to", "2025", "--provider", provider,
                                  "--base-url", self.root + path, "--out", str(out)])
        return rc, buf.getvalue()

    def check_output(self, path, provider):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "OBS_ASOS_TIM_119_api.csv"
            rc, log = self.run_main(KEY, path, provider, out)
            self.assertEqual(rc, 0, log)
            self.assertNotIn(KEY, log)
            self.assertFalse((Path(tmp) / ".kma_fetch.part").exists())
            self.assertEqual(len(out.read_text(encoding="utf-8-sig").splitlines()), 1 + 4 * 3)  # 겨울 4달 × 3시각
            if not (MAKERTON / "model/icezero/kma.py").exists():
                self.skipTest("makerton 없음: 로더 호환 확인 생략")
            sys.dont_write_bytecode = True  # omp 작업 폴더에 __pycache__를 남기지 않는다
            sys.path.insert(0, str(MAKERTON))
            from model.icezero import kma
            table = kma.read_table(out)
            self.assertEqual(len(table), 12)
            self.assertEqual(table["ground_temp"].isna().sum(), 4)  # -99.0 결측
            self.assertAlmostEqual(table["ground_temp"].min(), -5.6)
            self.assertAlmostEqual(table["ground_temp"].max(), -5.0)  # TE_005(9.9)를 잘못 읽지 않았다
            self.assertAlmostEqual(table["temp"].iloc[0], -3.1)
            self.assertTrue((table["precip"] == 0).all())  # -9.0 = 강수 없음 → 빈칸 → 로더가 0으로 읽는다

    def test_hub_follows_help_column_order(self):
        self.check_output("/hub", "hub")

    def test_hub_default_order_without_help(self):
        self.check_output("/hub_nohelp", "hub")

    def test_datagokr_pages(self):
        self.check_output("/dgk", "datagokr")
        self.assertIn(2, FakeApi.dgk_pages)

    def test_bad_key_fails_without_file_or_key_echo(self):
        for path, provider, msg in (("/hub", "hub", "유효한 인증키가 아닙니다"),
                                    ("/dgk", "datagokr", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR")):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "OBS_ASOS_TIM_119_api.csv"
                rc, log = self.run_main("wrong-key", path, provider, out)
                self.assertEqual(rc, 1)
                self.assertIn(msg, log)
                self.assertNotIn("wrong-key", log)
                self.assertFalse(out.exists())


class QcTest(unittest.TestCase):
    def test_sentinel_and_spike(self):
        q = fetch_asos.qc_values
        # 앞뒤가 따뜻한데 혼자 -9.0 → 결측 표시
        self.assertEqual(q(["4.9", "-9.0", "7.2"]), [4.9, None, 7.2])
        # 앞뒤가 -9 근처면 실제 -9.0°C
        self.assertEqual(q(["-8.9", "-9.0", "-9.1"]), [-8.9, -9.0, -9.1])
        # 추운 밤 앞뒤가 -9 근처면 몇 시간 이어진 -9.0도 실제 값(2025-01-09 밤)
        self.assertEqual(q(["-8.9", "-9.0", "-9.0", "-9.0", "-9.1"]), [-8.9, -9.0, -9.0, -9.0, -9.1])
        # 6시간보다 길게 멈춘 -9.0은 앞뒤가 -9 근처여도 결측
        self.assertEqual(q(["-8.8"] + ["-9.0"] * 7 + ["-8.5"]), [-8.8] + [None] * 7 + [-8.5])
        # 따뜻하다가 -9.0에서 멈춘 긴 구간(2023-12) → 결측
        self.assertEqual(q(["6.7", "-9.0", "-9.0", "-9.0"]), [6.7, None, None, None])
        # 앞뒤가 비슷한데 혼자 튄 값(-1.6, -18.0, -2.0) → 결측
        self.assertEqual(q(["-1.6", "-18.0", "-2.0"]), [-1.6, None, -2.0])
        # 해가 들면 지면이 한 시간에 크게 오른다: 한쪽으로만 바뀌면 남긴다
        self.assertEqual(q(["2.0", "11.0", "13.0"]), [2.0, 11.0, 13.0])
        self.assertEqual(q(["", "1.0"]), [None, 1.0])

    def test_qc_file_rewrites_blanks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "OBS_ASOS_TIM_119_api.csv"
            rows = [{"stnId": "119", "tm": "2025-01-01 0%d:00" % i, "ta": "1.0", "ts": ts}
                    for i, ts in enumerate(("4.9", "-9.0", "7.2"))]
            fetch_asos.write_csv(path, rows)
            out = Path(tmp) / "clean.csv"
            changed, total = fetch_asos.qc_file(path, out)
            self.assertEqual((changed, total), (1, 3))
            self.assertIn("-9.0", path.read_text(encoding="utf-8-sig"))   # 원본은 그대로
            text = out.read_text(encoding="utf-8-sig").splitlines()
            self.assertTrue(text[2].endswith(","))       # 지면온도가 빈칸이 됐다
            self.assertNotIn("-9.0", "".join(text))


if __name__ == "__main__":
    unittest.main()
