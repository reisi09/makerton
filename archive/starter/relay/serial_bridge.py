"""USB 직렬 대체 경로: 피코의 '@@REQ {json}' 줄을 중계 서버 /decide로 넘기고 '@@RES {json}'으로 돌려준다.

Wi-Fi가 안 될 때(핫스팟 단말 간 차단, 노트북 방화벽 등)만 쓴다. 피코 config.py의 TRANSPORT를 "usb"로 바꾼다.
    pip install pyserial
    python3 serial_bridge.py /dev/tty.usbmodem1101      # Windows는 COM3 같은 포트 이름
Thonny 같은 직렬 모니터는 반드시 닫는다(포트는 한 프로그램만 열 수 있다). 피코의 다른 print 출력은 그대로 화면에 보인다.
"""
import json
import os
import sys
import urllib.error
import urllib.request

import serial  # pyserial

RELAY = os.environ.get("RELAY_DECIDE_URL", "http://127.0.0.1:%s/decide" % os.environ.get("PORT", "8000"))
TOKEN = os.environ.get("RELAY_TOKEN", "")


def decide(line):
    try:
        seq = json.loads(line).get("seq")
    except ValueError:
        return json.dumps({"error": "bad json"})
    req = urllib.request.Request(RELAY, data=line.encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "X-Relay-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:  # 502 등: level 없는 응답을 보내 피코가 로컬 규칙을 쓰게 한다
        return json.dumps({"error": "relay %s" % e.code, "seq": seq})
    except Exception as e:
        return json.dumps({"error": str(e), "seq": seq})


def main(port):
    with serial.serial_for_url(port, baudrate=115200, timeout=1) as ser:
        print("bridge:", port, "->", RELAY)
        while True:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("@@REQ "):
                res = decide(line[6:])
                ser.write(("@@RES " + res.replace("\n", " ") + "\n").encode("utf-8"))
                print("AI", res)
            elif line:
                print("pico>", line)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python3 serial_bridge.py <직렬 포트>")
    main(sys.argv[1])
