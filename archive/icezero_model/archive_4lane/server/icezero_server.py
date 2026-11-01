"""ICE-ZERO 모형 서버 — 대시보드·API(HTTP) + 제설차(UDP) + 보드 링크(시리얼 또는 Wi-Fi).

실행 예
    CMD_API_KEY="$(omp token commandcode)" python3 server/icezero_server.py
    python3 server/icezero_server.py --no-llm --board-serial none
    ICEZERO_TOKEN=team-secret python3 server/icezero_server.py

역할
- 계획 계산(plan.py)과 제보 해석(llm.py)을 대시보드·사람 승인 절차에 연결한다.
- 제설차와는 UDP(서버 9100 수신, 차 9101)로 계약 8절 메시지를 주고받는다.
- 보드는 USB 시리얼(@@TEL/@@LED) 또는 Wi-Fi(POST /api/board/telemetry)로 붙는다.
- LLM은 차를 조종하지 않는다. 사람이 '제보 확인 → 계획 승인 → 출동 승인'을 거쳐야만 움직인다.
"""

import argparse
import glob
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import llm
import plan

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")
EVENTS_PATH = os.environ.get("ICEZERO_EVENTS", os.path.join(HERE, "events.jsonl"))
TOKEN = os.environ.get("ICEZERO_TOKEN", "")

HTTP_PORT = 8000
UDP_PORT = 9100
CAR_PORT = 9101

BOARD_FRESH_S = 5.0      # 보드 링크가 살아 있다고 보는 시간(계약 3절·7절)
CAR_FRESH_S = 3.0        # 제설차 링크가 살아 있다고 보는 시간
RESEND_S = 0.3           # ack 없을 때 재전송 간격
RESEND_TRIES = 10        # 재전송 횟수 상한
MAX_EVENT_LINES = 50     # 대시보드에 보여 줄 최근 이벤트

WARN_TEXT = {"start": "출발", "marker": "칸 표식 통과", "salt": "살포",
             "obstacle": "장애물 감지 — 정지", "clear": "장애물 사라짐 — 재개",
             "estop": "비상 정지", "resume": "재개", "lost": "유도선을 놓침",
             "done": "실행 완료 — 계획 종료", "warn": "차 경고"}


class HttpError(Exception):
    """핸들러가 상태 코드와 함께 던지는 오류."""

    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status
        self.message = message


def _float_or_none(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "y")
    return False


def local_ip():
    """같은 와이파이에서 접속할 노트북 주소를 찾는다(실패하면 127.0.0.1)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def find_serial_ports():
    """auto 모드 후보. usbmodem·ttyACM·COM 계열을 찾는다."""
    found = []
    for pattern in ("/dev/cu.usbmodem*", "/dev/tty.usbmodem*", "/dev/ttyACM*", "/dev/cu.usbserial*"):
        found.extend(glob.glob(pattern))
    if os.name == "nt":
        try:
            import serial.tools.list_ports as list_ports
            found.extend(p.device for p in list_ports.comports())
        except Exception:  # pyserial 이 없으면 여기서 조용히 넘어간다
            pass
    return sorted(set(found))


# ---------------------------------------------------------------------------
# 상태 모형
# ---------------------------------------------------------------------------


class Model:
    """공유 상태. 모든 변경은 self.lock 안에서 하고, 스냅숏은 복사본을 돌려준다."""

    def __init__(self, no_llm=False, events_path=None):
        self.lock = threading.RLock()
        self.log_lock = threading.Lock()
        self.no_llm = bool(no_llm)
        self.events_path = events_path or EVENTS_PATH
        self.udp = None

        self.reports = []          # 확인된 제보 [{"cells": [...], "at": ts, "text": ...}]
        self.salt_times = {}       # {칸: 마지막 살포 시각}
        self.manual_watch = None   # None=보드 따름, True/False=수동
        self.budget = plan.default_budget()
        self.rows = plan.plan_rows((), False, None, ())
        self.proposal = plan.propose(self.rows, self.budget)
        self.approved = None
        self.plan_counter = 0
        self.plan_ack = None       # {"plan_id":..., "at":...} 차가 계획을 받았다고 알린 시각
        self.pending = None
        self.llm_last = {"engine": None, "error": None, "latency_ms": None}

        self.board = {"tel": None, "seen": 0.0, "mode": "none"}
        self.car = {"st": "", "pos": None, "dist": None, "plan": None, "cells": [],
                    "salted": [], "seen": 0.0, "addr": None}
        self.events = []

    # -- 이벤트 ------------------------------------------------------------
    def event(self, kind, text):
        entry = {"ts": round(time.time(), 3), "time": time.strftime("%H:%M:%S"),
                 "kind": kind, "text": text}
        with self.lock:
            self.events.append(entry)
            del self.events[:-MAX_EVENT_LINES]
        try:
            with self.log_lock:
                with open(self.events_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:  # 기록 실패가 현장 동작을 막지 않게 한다
            print("[이벤트 기록 실패]", e)

    # -- 계산 --------------------------------------------------------------
    def _watch(self):
        """보드 warn(신선할 때) 과 수동 관측을 합친 '관측 주의' 값. lock 안에서 부른다."""
        if self.manual_watch is not None:
            return bool(self.manual_watch)
        tel = self.board.get("tel")
        if tel and time.time() - self.board["seen"] <= BOARD_FRESH_S:
            return bool(tel.get("warn"))
        return False

    def recompute(self):
        with self.lock:
            confirmed = plan.confirmed_cells(self.reports)
            salted = plan.salted_cells(self.reports, self.salt_times)
            self.rows = plan.plan_rows(confirmed, self._watch(), self.manual_watch, salted)
            self.proposal = plan.propose(self.rows, self.budget)
        return self.proposal

    def led_modes(self):
        """보드 LED 8칸. 승인 계획의 미살포 칸=plan, 살포한 칸=salted, 나머지=위험 단계."""
        with self.lock:
            approved = set((self.approved or {}).get("cells") or ())
            modes = {}
            for cell in plan.LOOP:
                row = self.rows[cell]
                if row["salted"]:
                    modes[cell] = "salted"
                elif cell in approved:
                    modes[cell] = "plan"
                else:
                    modes[cell] = row["risk"]
            return modes

    def snapshot(self):
        now = time.time()
        with self.lock:
            proposal_cells = set((self.proposal or {}).get("cells") or ())
            approved_cells = set((self.approved or {}).get("cells") or ())
            cells = {}
            for cell in plan.LOOP:
                row = self.rows[cell]
                cells[cell] = {
                    "score": row["score"],
                    "reasons": list(row["reasons"]),
                    "risk": row["risk"],
                    "in_proposal": cell in proposal_cells,
                    "in_approved": cell in approved_cells,
                    "salted": row["salted"],
                    "section": plan.SECTION_OF[cell],
                }
            tel = self.board.get("tel")
            board_age = round(now - self.board["seen"], 1) if self.board["seen"] else None
            car_age = round(now - self.car["seen"], 1) if self.car["seen"] else None
            sensors = {
                "t_piece": (tel or {}).get("t_piece"),
                "t_air": (tel or {}).get("t_air"),
                "wet": (tel or {}).get("wet"),
                "wet_raw": (tel or {}).get("wet_raw"),
                "warn": (tel or {}).get("warn"),
                "up": (tel or {}).get("up"),
                "seen": self.board["seen"] or None,
                "age": board_age,
                "caution": self.manual_watch,
                "watch": self._watch(),
                "source": self.board["mode"],
            }
            car = {
                "st": self.car["st"],
                "pos": self.car["pos"],
                "dist": self.car["dist"],
                "plan": self.car["plan"],
                "cells": list(self.car["cells"]),
                "salted": list(self.car["salted"]),
                "seen": self.car["seen"] or None,
                "age": car_age,
                "fresh": bool(car_age is not None and car_age <= CAR_FRESH_S),
                "addr": ("%s:%s" % self.car["addr"]) if self.car["addr"] else None,
            }
            pending = None
            if self.pending:
                pending = dict(self.pending)
                pending["result"] = dict(pending.get("result") or {})
                pending["rule"] = dict(pending.get("rule") or {})
            return {
                "now": round(now, 3),
                "time": time.strftime("%H:%M:%S"),
                "cells": cells,
                "budget": self.budget,
                "loop": list(plan.LOOP),
                "sections": dict(plan.SECTION_NAMES),
                "sensors": sensors,
                "proposal": self.proposal,
                "approved": self.approved,
                "car": car,
                "pending_report": pending,
                "plan_ack": self.plan_ack,
                "links": {
                    "board": {"mode": self.board["mode"],
                              "ok": bool(tel and board_age is not None and board_age <= BOARD_FRESH_S),
                              "age": board_age},
                    "car": {"ok": bool(car_age is not None and car_age <= CAR_FRESH_S),
                            "age": car_age, "addr": car["addr"]},
                    "llm": {"enabled": bool(not self.no_llm and llm.API_KEY),
                            "model": llm.TEXT_MODEL,
                            "engine": self.llm_last.get("engine"),
                            "error": self.llm_last.get("error"),
                            "latency_ms": self.llm_last.get("latency_ms")},
                },
                "events": list(self.events[-MAX_EVENT_LINES:]),
            }

    # -- 제보 --------------------------------------------------------------
    def submit_report(self, text):
        text = (text or "").strip()
        if not text:
            raise HttpError(400, "제보 문장이 비어 있습니다")
        use_llm = not self.no_llm and bool(llm.API_KEY)
        result = llm.interpret(text, use_llm=use_llm)
        error = result["error"]
        if not use_llm and not error:
            error = "LLM 꺼짐(--no-llm 또는 CMD_API_KEY 없음) — 규칙 파서만 사용"
        pending = {
            "text": text,
            "engine": result["engine"],
            "result": result["result"],
            "rule": result["rule"],
            "error": error,
            "latency_ms": result["latency_ms"],
            "at": round(time.time(), 3),
            "time": time.strftime("%H:%M:%S"),
        }
        with self.lock:
            self.pending = pending
            self.llm_last = {"engine": result["engine"], "error": error,
                             "latency_ms": result["latency_ms"]}
        self.event("report", "제보 접수(%s): %s" % (result["engine"], text[:50]))
        return pending

    def confirm_report(self, cells, budget, lane1_closed, text=""):
        cells = plan.cells_of(cells)
        lane1 = plan.cells_of(lane1_closed)
        with self.lock:
            if self.pending:
                text = text or self.pending.get("text") or ""
            if cells:
                self.reports.append({"cells": cells, "lane1_closed": lane1,
                                     "at": time.time(), "text": text[:200]})
            self.pending = None
            if budget is not None and budget != "":
                self.budget = plan.clamp_budget(budget)
            self.recompute()
            chosen = self.budget
        if cells:
            self.event("confirm", "제보 확인: %s (예산 %d회분)" % (", ".join(cells), chosen))
        else:
            self.event("confirm", "확인된 칸 없이 제보를 닫았습니다")
        return {"cells": cells, "budget": chosen}

    def reject_report(self):
        with self.lock:
            had = self.pending is not None
            self.pending = None
        if had:
            self.event("report", "제보를 버렸습니다(사람 판단)")
        return {"ok": True}

    def observe(self, caution):
        if caution not in (True, False, None):
            raise HttpError(400, "caution 은 true/false/null 중 하나입니다")
        with self.lock:
            self.manual_watch = caution
            self.recompute()
        label = {True: "주의 켬", False: "주의 끔", None: "자동(해제)"}[caution]
        self.event("observe", "수동 관측: %s" % label)
        return {"caution": caution}

    def set_budget(self, value):
        if value is None or isinstance(value, bool):
            raise HttpError(400, "budget 은 0~8 정수입니다")
        if isinstance(value, str):
            text = value.strip()
            if not re.match(r"^-?\d+$", text):
                raise HttpError(400, "budget 은 0~8 정수입니다")
            value = int(text)
        with self.lock:
            self.budget = plan.clamp_budget(value)
            self.recompute()
            budget = self.budget
        self.event("budget", "예산을 %d회분으로 바꿨습니다" % budget)
        return {"budget": budget}

    # -- 승인·출동 ---------------------------------------------------------
    def approve_plan(self):
        with self.lock:
            if not self.proposal or not self.proposal["cells"]:
                raise HttpError(409, "제안이 비어 있습니다. 제보 확인이나 예산 조정을 먼저 하세요")
            self.plan_counter += 1
            plan_id = "P%d" % self.plan_counter
            self.approved = {
                "plan_id": plan_id,
                "cells": list(self.proposal["cells"]),
                "budget": self.proposal["budget"],
                "scores": dict(self.proposal["scores"]),
                "reasons": {c: list(v) for c, v in self.proposal["reasons"].items()},
                "at": round(time.time(), 3),
                "time": time.strftime("%H:%M:%S"),
            }
            self.plan_ack = None
            cells = list(self.approved["cells"])
            had_addr = bool(self.car["addr"])
        sent = False
        if self.udp is not None and had_addr:
            sent = self.udp.send("plan", plan_id=plan_id, cells=cells) is not None
        self.event("approve", "계획 승인 %s: %s%s" % (
            plan_id, ", ".join(cells), "" if sent else " (차 주소 미확인 — 전송 보류)"))
        return {"plan_id": plan_id, "cells": cells, "sent": sent}

    def dispatch(self):
        with self.lock:
            approved = self.approved
            if not approved:
                raise HttpError(409, "승인된 계획이 없습니다. 먼저 '계획 승인'을 누르세요")
            age = time.time() - self.car["seen"] if self.car["seen"] else None
            if age is None or age > CAR_FRESH_S:
                raise HttpError(409, "제설차 신호가 없거나 오래됐습니다(마지막 %.1f초 전)" % (age or 0.0))
            if self.car["st"] not in ("IDLE", "DONE"):
                raise HttpError(409, "제설차 상태가 %s 입니다. IDLE·DONE일 때만 출동합니다" % self.car["st"])
            if not self.plan_ack or self.plan_ack.get("plan_id") != approved["plan_id"]:
                raise HttpError(409, "차가 아직 같은 계획(%s)을 확인(ack)하지 않았습니다" % approved["plan_id"])
            plan_id = approved["plan_id"]
        if self.udp is None or not self.udp.send("go", plan_id=plan_id):
            raise HttpError(409, "제설차 주소를 아직 모릅니다")
        self.event("dispatch", "출동 승인: %s" % plan_id)
        return {"plan_id": plan_id}

    def control(self, command):
        if self.udp is None or not self.car["addr"]:
            raise HttpError(409, "제설차 주소를 아직 모릅니다. 차의 hello를 기다리세요")
        if not self.udp.send(command):
            raise HttpError(409, "UDP 전송에 실패했습니다")
        text = {"stop": "비상 정지 명령", "resume": "재개 명령", "abort": "중단 명령"}[command]
        self.event("command", text)
        return {"command": command}

    def reset(self):
        with self.lock:
            self.reports = []
            self.salt_times = {}
            self.manual_watch = None
            self.pending = None
            self.approved = None
            self.plan_ack = None
            self.budget = plan.default_budget()
            self.recompute()
        self.event("reset", "시연 초기화(제보·살포·수동 관측·승인 계획)")
        return {"ok": True}

    # -- 차 UDP ------------------------------------------------------------
    def car_addr(self):
        with self.lock:
            return self.car["addr"]

    def car_hello(self, msg, addr):
        salted = plan.cells_of(msg.get("salted") or ())
        with self.lock:
            prev_st = self.car["st"]
            prev_plan = self.car["plan"]
            self.car.update({
                "st": str(msg.get("st") or "")[:12],
                "plan": msg.get("plan"),
                "cells": plan.cells_of(msg.get("cells") or ()),
                "salted": salted,
                "pos": msg.get("pos") if isinstance(msg.get("pos"), dict) else None,
                "dist": _int_or_none(msg.get("dist")),
                "seen": time.time(),
                "addr": (addr[0], addr[1]),
            })
            fresh_salt = False
            for cell in salted:
                if cell not in self.salt_times:
                    self.salt_times[cell] = time.time()
                    fresh_salt = True
            st, car_plan = self.car["st"], self.car["plan"]
            if fresh_salt:
                self.recompute()
        if st != prev_st:
            self.event("car", "제설차 상태: %s" % st)
        if car_plan != prev_plan and car_plan:
            self.event("car", "제설차가 계획 %s을(를) 들고 있습니다" % car_plan)

    def plan_acked(self, job):
        msg = (job or {}).get("msg") or {}
        kind = msg.get("t")
        if kind == "plan":
            plan_id = msg.get("plan_id")
            with self.lock:
                self.plan_ack = {"plan_id": plan_id, "at": round(time.time(), 3)}
            self.event("udp", "차가 계획 %s을(를) 받았습니다" % plan_id)
        elif kind:
            self.event("udp", "차가 '%s' 명령을 확인했습니다" % kind)

    def car_event(self, msg):
        kind = str(msg.get("e") or "")
        cell = msg.get("cell")
        cell = cell.upper() if isinstance(cell, str) and cell.upper() in plan.CELLS else None
        grp = msg.get("grp")
        if kind == "salt" and cell:
            with self.lock:
                self.salt_times[cell] = time.time()
                self.recompute()
            self.event("salt", "살포 완료: %s (계획에서 제외)" % cell)
            return
        label = WARN_TEXT.get(kind, kind or "알 수 없는 이벤트")
        detail = label
        if kind == "marker":
            bits = []
            if cell:
                bits.append(cell)
            if grp:
                bits.append("그룹 %s" % grp)
            if bits:
                detail = "%s (%s)" % (label, ", ".join(bits))
        self.event("car", detail)
        if kind == "done":
            self.recompute()

    def board_telemetry(self, body, source="wifi"):
        if not isinstance(body, dict):
            raise HttpError(400, "텔레메트리는 JSON 객체여야 합니다")
        tel = {
            "t_piece": _float_or_none(body.get("t_piece")),
            "t_air": _float_or_none(body.get("t_air")),
            "wet": _bool(body.get("wet")),
            "wet_raw": _int_or_none(body.get("wet_raw")),
            "warn": _bool(body.get("warn")),
            "up": _int_or_none(body.get("up")),
        }
        with self.lock:
            prev_warn = bool((self.board.get("tel") or {}).get("warn"))
            self.board["tel"] = tel
            self.board["seen"] = time.time()
            self.board["mode"] = source
            self.recompute()
            modes = self.led_modes()
        if tel["warn"] != prev_warn:
            self.event("board", "보드 관측 주의 %s" % ("켜짐" if tel["warn"] else "꺼짐"))
        return {"cells": modes}


# ---------------------------------------------------------------------------
# 제설차 UDP
# ---------------------------------------------------------------------------


class UdpLink(threading.Thread):
    """제설차 UDP. 받은 패킷의 주소를 학습해 그 주소로 답한다. ack 없으면 300ms×10 재전송."""

    def __init__(self, model, port=UDP_PORT, host="0.0.0.0"):
        threading.Thread.__init__(self, name="udp", daemon=True)
        self.model = model
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.settimeout(0.1)
        self.port = port
        self._seq = 0
        self._lock = threading.Lock()
        self._pending = {}   # seq -> job {"seq","msg","addr","tries","next"}
        self._stop = threading.Event()

    def next_seq(self):
        with self._lock:
            self._seq += 1
            return self._seq

    def _raw_send(self, msg, addr):
        try:
            data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
            if len(data) > 512:  # 계약 8절: 512바이트 이하
                return False
            self.sock.sendto(data, addr)
            return True
        except OSError as e:
            self.model.event("udp", "UDP 전송 실패: %s" % str(e)[:60])
            return False

    def send(self, kind, **fields):
        """명령을 만들고 즉시 보낸다. 차 주소를 모르면 None."""
        addr = self.model.car_addr()
        if not addr:
            return None
        msg = {"t": kind}
        msg.update(fields)
        seq = self.next_seq()
        msg["seq"] = seq
        if TOKEN:
            msg["tok"] = TOKEN
        job = {"seq": seq, "msg": msg, "addr": addr, "tries": 0, "next": time.time() + RESEND_S}
        with self._lock:
            self._pending[seq] = job
        if not self._raw_send(msg, addr):
            with self._lock:
                self._pending.pop(seq, None)
            return None
        return seq

    def _handle(self, data, addr):
        try:
            msg = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.model.event("udp", "UDP 패킷을 읽지 못했습니다(%d바이트)" % len(data))
            return
        if not isinstance(msg, dict):
            return
        if TOKEN and msg.get("tok") != TOKEN:
            return  # 토큰이 다른 패킷은 조용히 버린다
        kind = msg.get("t")
        if kind == "hello":
            self.model.car_hello(msg, addr)
        elif kind == "ack":
            seq = msg.get("seq")
            with self._lock:
                job = self._pending.pop(seq, None)
            if job:
                self.model.plan_acked(job)
        elif kind == "evt":
            self.model.car_event(msg)

    def _retransmit(self):
        now = time.time()
        with self._lock:
            jobs = list(self._pending.values())
        for job in jobs:
            if now < job["next"]:
                continue
            if job["tries"] >= RESEND_TRIES:
                with self._lock:
                    self._pending.pop(job["seq"], None)
                self.model.event("udp", "'%s' 응답 없음 — %d회 재전송 후 포기" % (
                    job["msg"].get("t"), RESEND_TRIES))
                continue
            job["tries"] += 1
            job["next"] = now + RESEND_S
            self._raw_send(job["msg"], job["addr"])

    def run(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                data = None
            except OSError:
                break
            if data:
                self._handle(data, addr)
            self._retransmit()

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 보드 링크(USB 시리얼)
# ---------------------------------------------------------------------------


class BoardLink(threading.Thread):
    """시리얼 115200. '@@TEL {...}' 를 읽고 '@@LED {...}' 를 바뀔 때 + 2초마다 쓴다."""

    def __init__(self, model, port, path=""):
        threading.Thread.__init__(self, name="board", daemon=True)
        self.model = model
        self.port = port
        self.path = path
        self._stop = threading.Event()
        self._last_led = None
        self._last_tx = 0.0

    def run(self):
        if self.port is None:
            return
        while not self._stop.is_set():
            try:
                line = self.port.readline()
            except Exception as e:  # 케이블이 빠지면 링크만 끈다
                self.model.event("board", "시리얼 읽기 실패: %s" % str(e)[:60])
                break
            if line:
                text = line.decode("utf-8", "replace").strip()
                if text.startswith("@@TEL"):
                    payload = text[5:].strip()
                    try:
                        self.model.board_telemetry(json.loads(payload), "serial")
                    except (ValueError, HttpError) as e:
                        self.model.event("board", "텔레메트리 해석 실패: %s" % str(e)[:60])
            self._maybe_send_led()
        try:
            self.port.close()
        except Exception:
            pass

    def _maybe_send_led(self):
        modes = self.model.led_modes()
        payload = json.dumps({"cells": modes}, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        if payload == self._last_led and now - self._last_tx < 2.0:
            return
        try:
            self.port.write(("@@LED " + payload + "\n").encode("utf-8"))
            self.port.flush()
            self._last_led = payload
            self._last_tx = now
        except Exception as e:
            self.model.event("board", "LED 전송 실패: %s" % str(e)[:60])

    def stop(self):
        self._stop.set()


def open_board_serial(spec, model):
    """--board-serial auto|<포트>|none. pyserial 이 없으면 경고하고 none 으로 돈다."""
    if spec == "none":
        return None, "none"
    target = ""
    if spec == "auto":
        ports = find_serial_ports()
        if not ports:
            print("[보드] 시리얼 포트를 찾지 못했습니다. Wi-Fi 모드(/api/board/telemetry)로 계속합니다.")
            return None, "none"
        if len(ports) > 1:
            print("[보드] 시리얼 후보가 2개 이상이라 자동 연결을 끕니다:")
            for p in ports:
                print("   ", p)
            print("      원하는 포트를 --board-serial <포트> 로 지정하세요.")
            return None, "none"
        target = ports[0]
    else:
        target = spec
    try:
        import serial
    except ImportError:
        print("[보드] pyserial 이 없어 시리얼 연결을 끕니다. 'pip install pyserial' 후 다시 실행하세요.")
        return None, "none"
    try:
        ser = serial.Serial(target, 115200, timeout=0.2)
    except Exception as e:
        print("[보드] 시리얼 열기 실패(%s): %s — Wi-Fi 모드로 계속합니다." % (target, e))
        return None, "none"
    print("[보드] 시리얼 연결:", target)
    return ser, target


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    model = None
    server_version = "icezero/1.0"

    def log_message(self, fmt, *args):
        # 정상 200 응답은 조용히 두고 4xx·5xx 만 남긴다.
        code = str(args[1]) if len(args) > 1 else ""
        if code.startswith("4") or code.startswith("5"):
            print("[HTTP]", fmt % args)

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _body(self):
        length = _int_or_none(self.headers.get("Content-Length")) or 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HttpError(400, "JSON 본문이 아닙니다")
        if not isinstance(body, dict):
            raise HttpError(400, "JSON 객체 본문이 필요합니다")
        return body

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            try:
                with open(INDEX_PATH, "rb") as f:
                    html = f.read()
            except OSError:
                self._send(500, {"error": "static/index.html 을 읽지 못했습니다"})
                return
            self._send(200, html, "text/html; charset=utf-8")
        elif path == "/api/state":
            self._send(200, self.model.snapshot())
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._send(404, {"error": "없는 경로입니다: %s" % path})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
        route = {
            "/api/report": self._report,
            "/api/report/confirm": self._confirm,
            "/api/report/reject": self._reject,
            "/api/observe": self._observe,
            "/api/budget": self._budget,
            "/api/plan/approve": self._approve,
            "/api/dispatch": self._dispatch,
            "/api/estop": self._estop,
            "/api/resume": self._resume,
            "/api/abort": self._abort,
            "/api/reset": self._reset,
            "/api/board/telemetry": self._telemetry,
        }.get(path)
        if route is None:
            self._send(404, {"error": "없는 경로입니다: %s" % path})
            return
        try:
            if TOKEN and path != "/api/board/telemetry":
                if self.headers.get("X-Token") != TOKEN:
                    raise HttpError(403, "X-Token 헤더가 필요합니다")
            status, payload = route(self._body())
        except HttpError as e:
            status, payload = e.status, {"error": e.message}
        except Exception as e:  # 마지막 그물
            status, payload = 500, {"error": "서버 오류: %s" % str(e)[:160]}
        self._send(status, payload)

    # -- 라우트 ------------------------------------------------------------
    def _report(self, body):
        text = body.get("text")
        if not isinstance(text, str):
            raise HttpError(400, "text 필드가 필요합니다")
        return 200, self.model.submit_report(text)

    def _confirm(self, body):
        cells = body.get("cells")
        if cells is not None and not isinstance(cells, (list, tuple)):
            raise HttpError(400, "cells 는 칸 ID 목록입니다")
        budget = body.get("budget")
        if budget is not None and (isinstance(budget, bool) or not isinstance(budget, (int, str))):
            raise HttpError(400, "budget 은 정수 또는 null 입니다")
        lane1 = body.get("lane1_closed") or []
        if not isinstance(lane1, (list, tuple)):
            raise HttpError(400, "lane1_closed 는 칸 ID 목록입니다")
        result = self.model.confirm_report(cells or [], budget, lane1)
        return 200, {"ok": True, "confirmed": result, "state": self.model.snapshot()}

    def _reject(self, body):
        return 200, self.model.reject_report()

    def _observe(self, body):
        if "caution" not in body:
            raise HttpError(400, "caution 필드가 필요합니다(true/false/null)")
        result = self.model.observe(body.get("caution"))
        return 200, dict(result, state=self.model.snapshot())

    def _budget(self, body):
        value = body.get("budget")
        if value is None or isinstance(value, bool) or not isinstance(value, (int, str)):
            raise HttpError(400, "budget 은 0~8 정수입니다")
        result = self.model.set_budget(value)
        return 200, dict(result, state=self.model.snapshot())

    def _approve(self, body):
        result = self.model.approve_plan()
        return 200, dict(result, state=self.model.snapshot())

    def _dispatch(self, body):
        result = self.model.dispatch()
        return 200, dict(result, state=self.model.snapshot())

    def _estop(self, body):
        result = self.model.control("stop")
        return 200, dict(result, state=self.model.snapshot())

    def _resume(self, body):
        result = self.model.control("resume")
        return 200, dict(result, state=self.model.snapshot())

    def _abort(self, body):
        result = self.model.control("abort")
        return 200, dict(result, state=self.model.snapshot())

    def _reset(self, body):
        result = self.model.reset()
        return 200, dict(result, state=self.model.snapshot())

    def _telemetry(self, body):
        # 보드는 토큰을 다루기 어려우므로 이 경로는 X-Token 을 요구하지 않는다(README에 적는다).
        return 200, self.model.board_telemetry(body, "wifi")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(description="ICE-ZERO 모형 서버(대시보드 + 제설차 UDP + 보드 링크)")
    p.add_argument("--host", default="0.0.0.0", help="HTTP 바인드 주소(기본 0.0.0.0)")
    p.add_argument("--port", type=int, default=HTTP_PORT, help="HTTP 포트(기본 8000)")
    p.add_argument("--udp-port", type=int, default=UDP_PORT, help="제설차 UDP 수신 포트(기본 9100)")
    p.add_argument("--board-serial", default="auto", metavar="auto|PORT|none",
                   help="보드 시리얼 포트(기본 auto: usbmodem·ttyACM·COM 자동, 2개 이상이면 끔)")
    p.add_argument("--no-llm", action="store_true", help="LLM 호출 없이 규칙 파서만 쓴다")
    p.add_argument("--events", default=None, help="이벤트 기록 파일(기본 server/events.jsonl)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    model = Model(no_llm=args.no_llm, events_path=args.events)
    udp = UdpLink(model, args.udp_port, "0.0.0.0")
    model.udp = udp
    udp.start()

    port, path = open_board_serial(args.board_serial, model)
    board = BoardLink(model, port, path) if port is not None else None
    if board is not None:
        board.start()
    else:
        model.board["mode"] = "none"

    Handler.model = model
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    ip = local_ip()
    print("=" * 62)
    print("ICE-ZERO 모형 서버를 시작했습니다.")
    print("  대시보드(이 노트북): http://127.0.0.1:%d" % args.port)
    print("  같은 와이파이에서:   http://%s:%d   ← 휴대폰·다른 노트북" % (ip, args.port))
    print("  노트북 IP 확인: macOS 'ipconfig getifaddr en0', Windows 'ipconfig', 리눅스 'hostname -I'")
    print("  제설차 UDP: 0.0.0.0:%d 수신 / 차는 %d 에서 듣는다" % (args.udp_port, CAR_PORT))
    print("  보드 링크: %s" % (path if port is not None else "없음(Wi-Fi 모드 /api/board/telemetry)"))
    if args.no_llm:
        print("  LLM: 꺼짐(--no-llm) — 제보는 규칙 파서로만 해석합니다")
    elif llm.API_KEY:
        print("  LLM: %s (reasoning=%s)" % (llm.TEXT_MODEL, llm.TEXT_REASONING or "없음"))
    else:
        print("  LLM: 키 없음 — 규칙 파서로만 해석합니다(CMD_API_KEY 환경변수를 설정하세요)")
    print("  공유 비밀(ICEZERO_TOKEN): %s" % ("켜짐 — 쓰기 요청에 X-Token 필요" if TOKEN else "없음"))
    print("  예산 기본값: %d회분 / 이벤트 기록: %s" % (model.budget, model.events_path))
    print("=" * 62)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 멈춥니다.")
    finally:
        httpd.server_close()
        udp.stop()
        if board is not None:
            board.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
