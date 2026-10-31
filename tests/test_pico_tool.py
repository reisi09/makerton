# -*- coding: utf-8 -*-
"""tools/pico.py 시험: raw REPL을 흉내 내는 가짜 시리얼(CPython exec)로 업로드·Wi-Fi 주입을 본다."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pico  # noqa: E402


class FakeRawRepl(object):
    """Ctrl-A로 raw REPL에 들어가고, Ctrl-D마다 모은 코드를 exec해 OK·출력·오류를 돌려준다."""

    def __init__(self, cwd):
        self.cwd = cwd
        self.out = b""
        self.code = b""
        self.raw = False
        self.env = {}

    def write(self, data):
        for b in data:
            c = bytes([b])
            if c == b"\x01":
                self.raw, self.code = True, b""
                self.out += pico.BANNER
            elif c == b"\x04" and self.raw:
                self._run()
            elif self.raw:
                self.code += c

    def _run(self):
        stdout, err = io.StringIO(), b""
        here = os.getcwd()
        os.chdir(self.cwd)
        try:
            with contextlib.redirect_stdout(stdout):
                exec(self.code.decode(), self.env)
        except Exception as e:  # 가짜 장치가 예외를 오류 채널로 돌려준다
            err = repr(e).encode()
        finally:
            os.chdir(here)
        self.out += b"OK" + stdout.getvalue().encode() + b"\x04" + err + b"\x04>"
        self.code = b""

    def read(self, n=1):
        data, self.out = self.out[:n], self.out[n:]
        return data

    def reset_input_buffer(self):
        self.out = b""


class PutTest(unittest.TestCase):
    def test_put_car_with_wifi_writes_exact_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev = pico.Pico.__new__(pico.Pico)
            dev.s = FakeRawRepl(tmp)
            args = type("A", (), {"which": "car", "wifi": True, "server_ip": ""})()
            secret = 'p"w\'한글'
            stdout = io.StringIO()
            with unittest.mock.patch("builtins.input", return_value="hotspot"), \
                    unittest.mock.patch("getpass.getpass", return_value=secret), \
                    contextlib.redirect_stdout(stdout):
                pico.cmd_put(dev, args)
            src = ROOT / "pico" / "car"
            for path in src.glob("*.py"):
                if path.name != "config.py":
                    self.assertEqual((Path(tmp) / path.name).read_bytes(), path.read_bytes())
            ns = {}
            exec((Path(tmp) / "config.py").read_text(encoding="utf-8"), ns)
            self.assertEqual(ns["WIFI_SSID"], "hotspot")
            self.assertEqual(ns["WIFI_PASS"], secret)
            self.assertEqual(ns["SERVER_IP"], "")
            self.assertNotIn(secret, stdout.getvalue())
            self.assertIn('WIFI_PASS = ""', (src / "config.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
