#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pico(MicroPython)에 펌웨어를 올리고 확인한다. USB 시리얼 raw REPL을 쓴다(pyserial).

    python3 tools/pico.py ls                    # 보드 이름·MicroPython 버전·파일 목록
    python3 tools/pico.py put car --wifi        # pico/car/*.py 업로드. Wi-Fi 이름·비밀번호는 이때 입력받는다
    python3 tools/pico.py put sensors           # pico/sensors/*.py 업로드
    python3 tools/pico.py reset                 # 소프트 리셋 → main.py가 돌고, 처음 몇 초 출력을 보여 준다
    python3 tools/pico.py exec "import hwtest; hwtest.main()"

Wi-Fi 비밀번호는 Mac 디스크에 쓰지 않는다. 업로드하는 config.py 내용에만 넣어 Pico 플래시로 보낸다.
Thonny가 포트를 잡고 있으면 열리지 않는다. Thonny에서 실행 > 연결해제를 누르고 쓴다.
"""
import argparse
import getpass
import glob
import re
import sys
import time
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[1]
CHUNK = 256                       # 한 번에 보내는 파일 바이트. raw REPL 입력 버퍼를 넘기지 않는다
BANNER = b"raw REPL; CTRL-B to exit\r\n>"


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/ttyACM*"))
    if len(ports) != 1:
        sys.exit("Pico 포트를 하나로 못 정했다: %s. --port로 고른다." % (ports or "없음"))
    return ports[0]


class Pico(object):
    def __init__(self, port):
        try:
            self.s = serial.Serial(port, 115200, timeout=0.2)
        except serial.SerialException as e:
            sys.exit("포트를 못 열었다(%s). Thonny라면 실행 > 연결해제를 누른다." % e)

    def read_until(self, end, timeout=10.0, echo=False):
        buf = b""
        deadline = None if timeout is None else time.time() + timeout
        while not buf.endswith(end):
            c = self.s.read(1)
            if c:
                buf += c
                if echo and c != b"\x04":
                    sys.stdout.buffer.write(c)
                    sys.stdout.flush()
            elif deadline is not None and time.time() > deadline:
                raise TimeoutError("Pico 응답 없음. 마지막: %r" % buf[-80:])
        return buf[:-len(end)]

    def enter_raw(self):
        self.s.write(b"\r\x03\x03")          # 돌고 있는 main.py를 멈춘다
        time.sleep(0.3)
        self.s.reset_input_buffer()
        self.s.write(b"\r\x01")
        self.read_until(BANNER)

    def exec(self, code, timeout=10.0, echo=False):
        """raw REPL에서 code를 돌리고 표준 출력을 돌려준다. 예외가 나면 RuntimeError."""
        data = code.encode()
        for i in range(0, len(data), CHUNK):
            self.s.write(data[i:i + CHUNK])
            time.sleep(0.005)
        self.s.write(b"\x04")
        if self.read_until(b"OK", 5.0) != b"":
            raise RuntimeError("raw REPL이 코드를 받지 않았다")
        out = self.read_until(b"\x04", timeout, echo)
        err = self.read_until(b"\x04", timeout)
        self.read_until(b">", timeout)
        if err:
            raise RuntimeError(err.decode("utf-8", "replace").strip())
        return out.decode("utf-8", "replace")

    def put(self, name, data):
        self.exec("f=open(%r,'wb')\nw=f.write" % name)
        for i in range(0, len(data), CHUNK):
            self.exec("w(%r)" % data[i:i + CHUNK])
        self.exec("f.close()")
        size = int(self.exec("import os\nprint(os.stat(%r)[6])" % name))
        if size != len(data):
            raise RuntimeError("%s 크기가 다르다: 보냄 %d, Pico %d" % (name, len(data), size))

    def soft_reset(self, watch_s):
        """raw REPL을 나와 Ctrl-D로 재부팅한다. main.py가 돈다."""
        self.s.write(b"\x02")
        time.sleep(0.1)
        self.s.write(b"\x04")
        end = time.time() + watch_s
        while time.time() < end:
            c = self.s.read(256)
            if c:
                sys.stdout.buffer.write(c)
                sys.stdout.flush()


def with_wifi(text, ssid, password, server_ip=""):
    """config.py의 빈 WIFI_SSID·WIFI_PASS·SERVER_IP 줄을 채운 내용을 돌려준다(파일은 안 고친다)."""
    for key, val in (("WIFI_SSID", ssid), ("WIFI_PASS", password), ("SERVER_IP", server_ip)):
        line = "%s = %r" % (key, val)
        text, n = re.subn(r'^%s = ""' % key, lambda m: line, text, flags=re.M)
        if n != 1:
            raise ValueError('config.py에 빈 %s = "" 줄이 하나 있어야 한다' % key)
    return text


def cmd_put(pico, args):
    src = ROOT / "pico" / args.which
    files = sorted(src.glob("*.py"))
    wifi = None
    if args.wifi:
        ssid = input("Wi-Fi 이름(2.4GHz 핫스팟): ").strip()
        password = getpass.getpass("Wi-Fi 비밀번호(화면에 안 보임): ")
        wifi = (ssid, password, args.server_ip)
    pico.enter_raw()
    for path in files:
        data = path.read_bytes()
        if path.name == "config.py" and wifi:
            data = with_wifi(data.decode("utf-8"), *wifi).encode("utf-8")
        pico.put(path.name, data)
        print("올림 %-14s %6d B" % (path.name, len(data)))
    print("%s 펌웨어 %d개 파일 확인 끝%s." % (args.which, len(files), " (Wi-Fi 넣음)" if wifi else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pico 펌웨어 업로드·확인(raw REPL)")
    ap.add_argument("--port", help="기본: /dev/cu.usbmodem* 하나")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ls")
    p = sub.add_parser("put")
    p.add_argument("which", choices=("car", "sensors"))
    p.add_argument("--wifi", action="store_true", help="Wi-Fi 이름·비밀번호를 입력받아 config.py에 넣어 보낸다")
    p.add_argument("--server-ip", default="", help="서버(맥북) IP. 비우면 차가 hello를 브로드캐스트한다")
    p = sub.add_parser("reset")
    p.add_argument("--watch", type=float, default=4.0, help="재부팅 뒤 출력을 보여 줄 초")
    p = sub.add_parser("exec")
    p.add_argument("code")
    args = ap.parse_args(argv)

    pico = Pico(args.port or find_port())
    if args.cmd == "ls":
        pico.enter_raw()
        print(pico.exec("import os,sys\nprint(os.uname().machine)\nprint(sys.version)\n"
                        "print(sorted(os.listdir()))").strip())
    elif args.cmd == "put":
        cmd_put(pico, args)
    elif args.cmd == "reset":
        pico.enter_raw()
        pico.soft_reset(args.watch)
    else:
        pico.enter_raw()
        try:
            pico.exec(args.code, timeout=None, echo=True)
        except KeyboardInterrupt:
            pico.s.write(b"\x03")
            print("\n중단했다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
