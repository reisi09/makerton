#!/usr/bin/env python3
"""USB 시리얼로 제설차에 계획을 넣는 CLI(예비 수단).

서버 없이 시연할 때, 또는 Wi-Fi가 안 될 때 쓴다. 차는 IDLE·DONE 상태에서만 받는다.

    python3 tools/car_usb_plan.py --list
    python3 tools/car_usb_plan.py --port /dev/tty.usbmodem1101 --cells U2,D2,D3
    python3 tools/car_usb_plan.py --port COM5 --cells D3 --plan-id P2 --baud 115200

보내는 줄: @@PLAN {"plan_id": "P1", "cells": ["U2", "D2", "D3"]}
계획을 넣은 뒤 차의 버튼을 짧게 누르면 출발한다(USB 대체 모드).
"""
import argparse
import json
import sys
import time

# 계약 2절의 칸 ID(루프 순서). 이 밖의 값은 차가 버리므로 미리 막는다.
LOOP = ["U1", "U2", "U3", "U4", "D4", "D3", "D2", "D1"]

DEFAULT_BAUD = 115200

try:
    import serial
except ImportError:                     # pyserial이 없어도 --list 안내는 할 수 있게
    serial = None

try:
    from serial.tools import list_ports
except ImportError:
    list_ports = None


def parse_cells(text):
    """'U2,D2,D3' → ['U2','D2','D3'](루프 순서로 정리, 중복 제거)."""
    cells = []
    for raw in (text or "").split(","):
        cell = raw.strip().upper()
        if not cell:
            continue
        if cell not in LOOP:
            raise ValueError("모르는 칸 ID: %s (가능: %s)" % (cell, ", ".join(LOOP)))
        if cell not in cells:
            cells.append(cell)
    cells.sort(key=LOOP.index)          # 보기 좋게 루프 순서로
    return cells


def show_ports():
    if list_ports is None:
        print("pyserial이 없어 포트를 찾을 수 없다: python3 -m pip install pyserial")
        return
    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    if not ports:
        print("시리얼 포트를 찾지 못했다. 피코를 USB로 연결하고 다시 실행한다.")
        return
    print("사용 가능한 시리얼 포트:")
    for port in ports:
        print("  %-24s %s" % (port.device, port.description))
    print("리눅스·macOS는 보통 /dev/tty.usbmodem… 또는 /dev/ttyACM…, 윈도우는 COM…")


def build_line(plan_id, cells):
    payload = {"plan_id": plan_id, "cells": cells}
    return "@@PLAN " + json.dumps(payload, ensure_ascii=False).replace("\n", " ") + "\n"


def send_plan(port, baud, plan_id, cells, read_ms=600):
    if serial is None:
        print("pyserial이 필요하다: python3 -m pip install pyserial")
        return 2
    line = build_line(plan_id, cells)
    try:
        with serial.Serial(port, baud, timeout=0) as link:
            time.sleep(0.2)                 # 포트가 열린 뒤 잠깐 기다린다
            link.write(line.encode())
            link.flush()
            print("%s 에 보냈다: %s" % (port, line.strip()))
            print("차의 Thonny 셸에 '계획 받음(USB): %s %s'가 보이면 성공이다." % (plan_id, cells))
            # 차가 찍는 로그를 잠깐만 읽어 보여 준다(없으면 그냥 넘어간다)
            deadline = time.time() + read_ms / 1000.0
            shown = False
            while time.time() < deadline:
                data = link.readline()
                if not data:
                    continue
                text = data.decode("utf-8", "replace").strip()
                if text:
                    print("  차:", text)
                    shown = True
            if not shown:
                print("  (차가 보낸 줄은 없다. Thonny 셸을 직접 보면 된다)")
            return 0
    except serial.SerialException as e:
        print("시리얼 포트를 열 수 없다: %s" % e)
        print("  - 다른 프로그램(Thonny·시리얼 모니터)이 포트를 잡고 있는지 확인한다")
        print("  - 포트 이름은 --list로 확인한다")
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="USB 시리얼로 제설차에 계획을 넣는다(@@PLAN 한 줄).")
    parser.add_argument("--port", help="시리얼 포트(예: /dev/tty.usbmodem1101, COM5)")
    parser.add_argument("--cells", help="칸 ID를 쉼표로. 예: U2,D2,D3")
    parser.add_argument("--plan-id", default="P-usb", help="계획 번호(기본 P-usb)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="통신 속도(기본 115200)")
    parser.add_argument("--list", action="store_true", help="사용 가능한 시리얼 포트를 보여 준다")
    args = parser.parse_args(argv)

    if args.list:
        show_ports()
        return 0
    if not args.port or not args.cells:
        show_ports()
        print()
        parser.print_usage()
        print("예: python3 tools/car_usb_plan.py --port /dev/tty.usbmodem1101 --cells U2,D2,D3")
        return 2

    try:
        cells = parse_cells(args.cells)
    except ValueError as e:
        print(e)
        return 2
    if not cells:
        print("칸이 하나도 없다. --cells U2,D2,D3 처럼 고른다.")
        return 2
    return send_plan(args.port, args.baud, args.plan_id, cells)


if __name__ == "__main__":
    sys.exit(main())
