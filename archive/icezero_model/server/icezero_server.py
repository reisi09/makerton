"""ICE-ZERO 사거리 모형 서버 — 대시보드·API(HTTP) + 재생 + 승인 + Pico 시리얼 링크.

실행 예
    CMD_API_KEY="$(omp token commandcode)" python3 server/icezero_server.py --pico-serial auto
    python3 server/icezero_server.py --no-llm --pico-serial none
    python3 server/icezero_server.py --port 8010 --night 2025-01-09

역할
- Engine(engine/icezero_cross.py)을 불러 실제 ASOS 겨울밤 한 밤을 시간 단위로 재생한다.
- 제보(llm.py) → 사람 확인 → 계획 승인 → 출동 승인의 순서를 강제한다.
- 승인된 계획 순서대로 Pico #1 에 @@SPRAY 를 하나씩 보내고 @@EVT spray_done 을 기다린다.
- Pico 가 없으면 모의 실행으로 표시하고 시연은 그대로 진행한다.
- LLM 은 기기를 조종하지 않는다.
"""

import argparse
import glob
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC_DIR = os.path.join(HERE, "static")
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")
EVENTS_PATH = os.environ.get("ICEZERO_EVENTS", os.path.join(HERE, "events.jsonl"))

# 엔진 모듈은 engine/ 에 있다. PYTHONPATH 로 다른 모듈을 먼저 잡으면 시험용 가짜 엔진이 쓰인다.
ENGINE_MODULE = os.environ.get("ICEZERO_ENGINE_MODULE", "icezero_cross")
ENGINE_DIR = os.path.join(ROOT, "engine")
if ENGINE_DIR not in sys.path:
    sys.path.append(ENGINE_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import llm  # noqa: E402

HTTP_PORT = 8000
ARMS = ("N", "E", "S", "W")
PICO_FRESH_S = 5.0        # Pico 텔레메트리가 살아 있다고 보는 시간(계약 3·5절)
SPRAY_TIMEOUT_S = 4.0     # 갈래당 살포 완료 대기 한계(계약 4절)
LED_RESEND_S = 2.0        # LED 명령을 바꿨을 때 + 2초마다 다시 보낸다
MAX_EVENT_LINES = 80
DEFAULT_BUDGET = 2
DEFAULT_SEC_PER_HOUR = 6.0
MOCK_SPRAY_S = 0.35       # Pico 없이 모의 실행할 때 갈래당 시간


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


def _arms_of(values):
    """갈래 목록을 N·E·S·W 로 제한하고 계약 순서로 정리한다."""
    if not values:
        return []
    if isinstance(values, str):
        values = values.replace(",", " ").split()
    found = set()
    for item in values:
        if isinstance(item, str) and item.strip().upper() in ARMS:
            found.add(item.strip().upper())
    return [a for a in ARMS if a in found]


def local_ip():
    """같은 와이파이에서 접속할 노트북 주소를 찾는다(실패하면 127.0.0.1)."""
    import socket
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
# 가짜 Pico (시험·시연 대비)
# ---------------------------------------------------------------------------


class FakePico(object):
    """시리얼 대신 쓰는 가짜 Pico. pyserial 과 같은 readline/write/flush/close 를 흉내 낸다.

    1초마다 @@TEL 을 내보내고, @@SPRAY 를 받으면 delay 초 뒤 @@EVT spray_done 을 보낸다.
    done_after=None 이면 절대 완료를 보내지 않는다(시간초과 시험용).
    """

    def __init__(self, delay=0.05, done_after=None, t_bridge=-3.2, wet=True):
        self.delay = delay
        self.done_after = delay if done_after is None else done_after
        self.t_bridge = t_bridge
        self.wet = wet
        self._rx = []
        self._tx = []
        self._lock = threading.Lock()
        self.commands = []
        self._closed = False

    def readline(self):
        with self._lock:
            if self._tx:
                return self._tx.pop(0)
        return b""

    def write(self, data):
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            self.commands.append(line)
            self._handle(line)
        return len(data)

    def flush(self):
        return None

    def close(self):
        self._closed = True

    def _push(self, text):
        with self._lock:
            self._tx.append((text + "\n").encode("utf-8"))

    def _handle(self, line):
        if line.startswith("@@SPRAY"):
            body = _json_tail(line, "@@SPRAY")
            seq = (body or {}).get("seq")
            arm = (body or {}).get("arm")
            if self.done_after is None:
                return
            threading.Timer(self.done_after, self._done, args=(seq, arm)).start()
        elif line.startswith("@@STOP"):
            self._push("@@EVT " + json.dumps({"e": "stopped", "seq": 0, "arm": None}))

    def _done(self, seq, arm):
        self._push("@@EVT " + json.dumps({"e": "spray_done", "seq": seq, "arm": arm},
                                         ensure_ascii=False))


class FakePicoSerial(FakePico):
    """가짜 Pico + 1초 TEL 하트비트. 서버 스레드가 readline 으로 받아 간다."""

    def __init__(self, **kw):
        FakePico.__init__(self, **kw)
        self._stop_flag = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()

    def _beat(self):
        while not self._stop_flag.is_set():
            t = self.t_bridge
            warn = t is not None and (t <= 0.0 or (t <= 1.0 and bool(self.wet)))  # 계약 5절 로컬 규칙과 같게
            self._push("@@TEL " + json.dumps(
                {"t_bridge": t, "t_air": -1.0, "wet": self.wet,
                 "wet_raw": 900 if self.wet else 2400, "warn": warn, "busy": False, "up": 1},
                ensure_ascii=False))
            self._stop_flag.wait(1.0)

    def close(self):
        self._stop_flag.set()
        FakePico.close(self)


def _json_tail(line, prefix):
    raw = line[len(prefix):].strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


# ---------------------------------------------------------------------------
# 상태 모형
# ---------------------------------------------------------------------------


class Model(object):
    """공유 상태. 모든 변경은 self.lock 안에서 하고, 스냅숏은 복사본을 돌려준다."""

    def __init__(self, engine=None, no_llm=False, events_path=None,
                 night=None, budget=DEFAULT_BUDGET, engine_error=None):
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.log_lock = threading.Lock()
        self.no_llm = bool(no_llm)
        self.events_path = events_path or EVENTS_PATH
        self.engine = engine
        self.engine_error = engine_error
        self.pico = None

        self.budget = self._clamp_budget(budget)
        self.reports = []          # 확인된 제보 [{"arms": [...], "condition": ..., "text": ...}]
        self.pending = None
        self.llm_last = {"engine": None, "error": None, "latency_ms": None}
        self.manual_t_bridge = None
        self.use_sensor = False
        self.approved = None
        self.plan_counter = 0
        self.plan_ack = None

        self.nights = []
        self.night = None
        self.timeline = []
        self.index = 0
        self.auto = False
        self.sec_per_hour = DEFAULT_SEC_PER_HOUR
        self._auto_next = 0.0
        self.series = {}           # {night: {"time": [...], "obs_ground": [...], "pred_h3": [...]}}
        self._series_busy = set()
        self._step_cache = {}
        self.step = None

        self.execution = self._blank_execution()
        self._spray_seq = 0
        self._run_id = 0          # 출동 실행 번호. 멈춘 옛 스레드가 새 실행을 덮어쓰지 못하게 한다
        self._done_seqs = set()
        self._estop_flag = False
        self._dispatch_thread = None

        self.pico_state = {"mode": "none", "port": "", "tel": None, "seen": 0.0}
        self.events = []

        self._stopped = False
        self._load_nights(night)
        self._auto_thread = threading.Thread(target=self._auto_loop, name="auto", daemon=True)
        self._auto_thread.start()
        self.refresh_step()

    # -- 작은 도구 ---------------------------------------------------------
    @staticmethod
    def _clamp_budget(value):
        n = _int_or_none(value)
        if n is None:
            return DEFAULT_BUDGET
        return max(0, min(4, n))

    def _blank_execution(self):
        return {"state": "idle", "mode": "none", "plan_id": None, "order": [],
                "current": None, "done": [], "seq": None, "message": "",
                "started": None, "finished": None}

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

    # -- 엔진·재생 ---------------------------------------------------------
    def _load_nights(self, night=None):
        nights = []
        if self.engine is not None:
            try:
                raw = self.engine.nights() or []
            except Exception as e:
                self.engine_error = "밤 목록을 읽지 못했습니다: %s" % str(e)[:120]
                raw = []
            for item in raw:
                if isinstance(item, str):
                    nights.append(item[:10])
                elif isinstance(item, dict):
                    value = item.get("night") or item.get("date") or item.get("day")
                    if value:
                        nights.append(str(value)[:10])
        seen = []
        for n in nights:
            if n not in seen:
                seen.append(n)
        self.nights = seen
        if night:
            self.night = night
        elif self.nights:
            self.night = self.nights[0]
        self._rebuild_timeline()

    def _rebuild_timeline(self):
        self.timeline = []
        self.index = 0
        self.step = None
        self._step_cache = {}
        if self.engine is None or not self.night:
            return
        try:
            ts = list(self.engine.timeline(self.night) or [])
        except Exception as e:
            self.engine_error = "시각 목록을 만들지 못했습니다: %s" % str(e)[:120]
            return
        self.timeline = [str(t) for t in ts]
        self._ensure_series(self.night)

    def current_ts(self):
        with self.lock:
            if not self.timeline:
                return None
            idx = max(0, min(self.index, len(self.timeline) - 1))
            return self.timeline[idx]

    def sensor_info(self):
        """계약 4절: Pico TEL 의 t_bridge 가 5초 안에 있으면 그 값, 없으면 수동 값.

        반환: {"payload": 엔진에 넘길 dict|None, "source": "pico"|"manual"|"none"}
        """
        with self.lock:
            if not self.use_sensor:
                return {"payload": None, "source": "none"}
            seen = self.pico_state["seen"]
            tel = self.pico_state["tel"] or {}
            if seen and time.time() - seen <= PICO_FRESH_S and tel.get("t_bridge") is not None:
                return {"payload": {"t_bridge": float(tel["t_bridge"]), "wet": tel.get("wet")},
                        "source": "pico"}
            if self.manual_t_bridge is not None:
                return {"payload": {"t_bridge": float(self.manual_t_bridge), "wet": None},
                        "source": "manual"}
            return {"payload": None, "source": "none"}

    def sensor_payload(self):
        return self.sensor_info()["payload"]

    def confirmed_arms(self):
        with self.lock:
            found = set()
            for rep in self.reports:
                found.update(rep.get("arms") or ())
            return [a for a in ARMS if a in found]

    def refresh_step(self):
        """현재 시각의 step 을 다시 계산해 self.step 에 넣는다."""
        with self.lock:
            ts = self.current_ts()
            if ts is None:
                self.step = None
                return None
            sensor = self.sensor_payload()
            reports = self.confirmed_arms()
            key = (ts, tuple(reports), self.budget,
                   None if sensor is None else (round(float(sensor["t_bridge"]) if sensor.get("t_bridge") is not None else 0.0, 3),
                                                sensor.get("wet")))
            cached = self._step_cache.get(key)
            if cached is not None:
                self.step = cached
                return cached
            try:
                result = self.engine.step(ts, sensor=sensor, reports=reports, budget=self.budget)
            except Exception as e:
                self.engine_error = "step 계산 실패: %s" % str(e)[:160]
                self.step = None
                return None
            self.engine_error = None
            self.step = result
            if len(self._step_cache) > 64:
                self._step_cache.clear()
            self._step_cache[key] = result
            return result

    def _ensure_series(self, night):
        """그 밤 관측 지면온도와 +3h 예측을 한 번만 계산해 둔다(그래프용)."""
        if self.engine is None or night in self.series or night in self._series_busy:
            return
        self._series_busy.add(night)

        def work():
            try:
                times, obs, pred = [], [], []
                for ts in list(self.timeline):
                    try:
                        st = self.engine.step(ts, sensor=None, reports=[], budget=self.budget)
                    except Exception:
                        continue
                    times.append(str(ts))
                    obs.append((st.get("obs") or {}).get("ground_temp"))
                    pred.append(((st.get("forecast") or {}).get("h3")))
                with self.lock:
                    if times:
                        self.series[night] = {"time": times, "obs_ground": obs, "pred_h3": pred}
            finally:
                self._series_busy.discard(night)

        threading.Thread(target=work, name="series", daemon=True).start()

    def set_night(self, night):
        night = str(night or "").strip()[:10]
        if not night:
            raise HttpError(400, "night 값이 필요합니다(YYYY-MM-DD)")
        if self.nights and night not in self.nights:
            # 목록에 없어도 엔진이 그 밤 자료를 만들 수 있으면 시도한다.
            pass
        with self.lock:
            self.night = night
            self._rebuild_timeline()
            self.auto = False
            self.refresh_step()
            ts = self.current_ts()
        self.event("replay", "재생 밤을 %s 로 바꿨습니다(18:00부터)" % night)
        return {"night": night, "ts": ts}

    def move(self, hours):
        n = _int_or_none(hours)
        if n is None:
            raise HttpError(400, "hours 는 정수입니다")
        with self.lock:
            if not self.timeline:
                raise HttpError(409, "재생할 시각이 없습니다")
            self.index = max(0, min(self.index + n, len(self.timeline) - 1))
            self.auto = False
            self.refresh_step()
            ts = self.current_ts()
            idx = self.index
        self.event("replay", "시각 이동: %s" % ts)
        return {"ts": ts, "index": idx}

    def set_auto(self, on, sec_per_hour=None):
        with self.lock:
            if not self.timeline:
                raise HttpError(409, "재생할 시각이 없습니다")
            self.auto = bool(on)
            if sec_per_hour is not None:
                value = _float_or_none(sec_per_hour)
                if value is None or value < 0.2:
                    value = DEFAULT_SEC_PER_HOUR
                self.sec_per_hour = min(60.0, value)
            self._auto_next = time.time() + self.sec_per_hour
            state = self.auto
        if state:
            self.event("replay", "자동 재생 시작(%.1f초/시간)" % self.sec_per_hour)
        else:
            self.event("replay", "자동 재생 정지")
        return {"auto": state, "sec_per_hour": self.sec_per_hour}

    def _auto_loop(self):
        while not self._stopped:
            time.sleep(0.1)
            with self.lock:
                if not self.auto or not self.timeline:
                    continue
                if time.time() < self._auto_next:
                    continue
                if self.index >= len(self.timeline) - 1:
                    self.auto = False
                    continue
                self.index += 1
                self._auto_next = time.time() + self.sec_per_hour
            try:
                self.refresh_step()
            except Exception:
                pass

    def stop(self):
        """시험·종료용. 자동 재생 스레드를 멈춘다."""
        self._stopped = True

    # -- Pico 링크 ---------------------------------------------------------
    def pico_ok(self):
        with self.lock:
            seen = self.pico_state["seen"]
            return bool(self.pico_state["mode"] != "none" and seen
                        and time.time() - seen <= PICO_FRESH_S)

    def write_pico(self, line):
        """Pico 로 한 줄 보낸다. 링크가 없으면 False."""
        pico = self.pico
        if pico is None:
            return False
        try:
            pico.write_line(line)
            return True
        except Exception as e:
            self.event("pico", "시리얼 쓰기 실패: %s" % str(e)[:60])
            return False

    def pico_telemetry(self, body):
        if not isinstance(body, dict):
            return
        tel = {
            "t_bridge": _float_or_none(body.get("t_bridge")),
            "t_air": _float_or_none(body.get("t_air")),
            "wet": _bool(body.get("wet")) if body.get("wet") is not None else None,
            "wet_raw": _int_or_none(body.get("wet_raw")),
            "warn": _bool(body.get("warn")),
            "busy": _bool(body.get("busy")),
            "up": _int_or_none(body.get("up")),
        }
        with self.lock:
            prev = (self.pico_state.get("tel") or {}).get("warn")
            self.pico_state["tel"] = tel
            self.pico_state["seen"] = time.time()
        if prev is not None and prev != tel["warn"]:
            self.event("pico", "교량 주의 %s" % ("켜짐" if tel["warn"] else "꺼짐"))
        if self.use_sensor:
            self.refresh_step()

    def pico_event(self, body):
        if not isinstance(body, dict):
            return
        kind = str(body.get("e") or "")
        arm = body.get("arm")
        arm = arm.upper() if isinstance(arm, str) and arm.upper() in ARMS else None
        seq = _int_or_none(body.get("seq"))
        if kind == "spray_start":
            self.event("pico", "살포 시작: %s (seq %s)" % (arm or "?", seq))
        elif kind == "spray_done":
            with self.lock:
                if seq is not None:
                    self._done_seqs.add(seq)
                done = self.execution.get("done")
                if done is not None and arm and arm not in done:
                    done.append(arm)
                self.cond.notify_all()
            self.event("pico", "살포 완료: %s (seq %s)" % (arm or "?", seq))
        elif kind == "spray_reject":
            self.event("pico", "Pico 가 살포를 거절했습니다: %s (seq %s)" % (arm or "?", seq))
        elif kind == "stopped":
            self.event("pico", "Pico 정지 확인")
        else:
            self.event("pico", "알 수 없는 이벤트: %s" % (kind or "?"))

    def led_modes(self):
        """갈래별 LED: 위험 단계, 승인 계획=plan, 살포 완료=done."""
        with self.lock:
            approved = set((self.approved or {}).get("order") or ())
            sprayed = set(self.execution.get("done") or ())
            modes = {}
            for arm in ARMS:
                if arm in sprayed:
                    modes[arm] = "done"
                elif arm in approved:
                    modes[arm] = "plan"
                else:
                    try:
                        modes[arm] = ((self.step or {}).get("arms") or {}).get(arm, {}).get("level") or "off"
                    except Exception:
                        modes[arm] = "off"
            return modes

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

    def confirm_report(self, arms, budget):
        chosen = _arms_of(arms)
        with self.lock:
            text = (self.pending or {}).get("text") or ""
            condition = ((self.pending or {}).get("result") or {}).get("condition") or "other"
            if chosen:
                self.reports.append({"arms": chosen, "condition": condition,
                                     "at": time.time(), "text": text[:200]})
            self.pending = None
            if budget is not None and budget != "":
                self.budget = self._clamp_budget(budget)
            self.refresh_step()
            budget_now = self.budget
        if chosen:
            self.event("confirm", "제보 확인: %s (예산 %d회분)" % (", ".join(chosen), budget_now))
        else:
            self.event("confirm", "갈래 없이 제보를 닫았습니다")
        return {"arms": chosen, "budget": budget_now}

    def reject_report(self):
        with self.lock:
            had = self.pending is not None
            self.pending = None
        if had:
            self.event("report", "제보를 버렸습니다(사람 판단)")
        return {"ok": True}

    def set_budget(self, value):
        n = _int_or_none(value)
        if n is None:
            raise HttpError(400, "budget 은 0~4 정수입니다")
        with self.lock:
            self.budget = self._clamp_budget(n)
            self.refresh_step()
            budget = self.budget
        self.event("budget", "예산을 %d회분으로 바꿨습니다" % budget)
        return {"budget": budget}

    def set_sensor(self, use_sensor=None, t_bridge="__keep__"):
        with self.lock:
            if use_sensor is not None:
                self.use_sensor = _bool(use_sensor)
            if t_bridge != "__keep__":
                value = _float_or_none(t_bridge)
                self.manual_t_bridge = value
            self.refresh_step()
            state = {"use_sensor": self.use_sensor, "t_bridge": self.manual_t_bridge}
        self.event("sensor", "현장 보정 %s (수동 t_bridge=%s)" % (
            "사용" if state["use_sensor"] else "사용 안 함",
            "없음" if state["t_bridge"] is None else ("%.1f℃" % state["t_bridge"])))
        return state

    # -- 승인·출동 ---------------------------------------------------------
    def proposal(self):
        step = self.step or {}
        d = step.get("dispatch") or {}
        return {"selected": list(d.get("selected") or ()), "order": list(d.get("order") or ()),
                "budget": d.get("budget"), "threshold": d.get("threshold"),
                "recommend": bool(d.get("recommend"))}

    def approve_plan(self):
        with self.lock:
            prop = self.proposal()
            if not prop["order"]:
                raise HttpError(409, "제안이 비어 있습니다. 제보 확인이나 예산 조정을 먼저 하세요")
            self.plan_counter += 1
            plan_id = "P%d" % self.plan_counter
            self.approved = {
                "plan_id": plan_id,
                "order": list(prop["order"]),
                "budget": prop["budget"],
                "at": round(time.time(), 3),
                "time": time.strftime("%H:%M:%S"),
            }
            self.plan_ack = None
            order = list(self.approved["order"])
            self.execution = self._blank_execution()
        sent = self.write_pico("@@LED " + json.dumps({"arms": self.led_modes()},
                                                     ensure_ascii=False, separators=(",", ":")))
        self.event("approve", "계획 승인 %s: %s%s" % (
            plan_id, " → ".join(order), "" if sent else " (Pico 없음 — LED 생략)"))
        return {"plan_id": plan_id, "order": order, "sent": sent}

    def dispatch(self):
        with self.lock:
            approved = self.approved
            if not approved:
                raise HttpError(409, "승인된 계획이 없습니다. 먼저 '계획 승인'을 누르세요")
            if self.execution.get("state") == "running":
                raise HttpError(409, "이미 실행 중입니다")
            mode = "pico" if self.pico_ok() else "mock"
            order = list(approved["order"])
            if not order:
                raise HttpError(409, "승인된 계획의 갈래가 비어 있습니다")
            self._estop_flag = False
            self._run_id += 1
            run_id = self._run_id
            self.execution = {
                "state": "running", "mode": mode, "plan_id": approved["plan_id"],
                "order": order, "current": None, "done": [], "seq": None,
                "message": "Pico 실행" if mode == "pico" else "모의 실행(Pico 없음)",
                "started": round(time.time(), 3), "finished": None,
            }
            self._dispatch_thread = threading.Thread(target=self._run_dispatch,
                                                     args=(order, approved["plan_id"], mode, run_id),
                                                     name="dispatch", daemon=True)
            self._dispatch_thread.start()
        self.event("dispatch", "출동 승인 %s (%s): %s" % (
            approved["plan_id"], "Pico" if mode == "pico" else "모의 실행", " → ".join(order)))
        return {"plan_id": approved["plan_id"], "order": order, "mode": mode}

    def _alive(self, run_id):
        """이 스레드가 아직 현재 실행의 주인인지. lock 안에서 부른다."""
        return self._run_id == run_id

    def _run_dispatch(self, order, plan_id, mode, run_id):
        for arm in order:
            with self.lock:
                if not self._alive(run_id):
                    return
                if self._estop_flag:
                    break
                self.execution["current"] = arm
            if mode != "pico":
                time.sleep(MOCK_SPRAY_S)
                with self.lock:
                    if not self._alive(run_id):
                        return
                    if self._estop_flag:
                        break
                    if arm not in self.execution["done"]:
                        self.execution["done"].append(arm)
                self.event("spray", "모의 살포 완료: %s" % arm)
                continue
            with self.lock:
                if not self._alive(run_id):
                    return
                self._spray_seq += 1
                seq = self._spray_seq
                self.execution["seq"] = seq
            line = "@@SPRAY " + json.dumps({"seq": seq, "arm": arm, "ms": 600},
                                           ensure_ascii=False, separators=(",", ":"))
            if not self.write_pico(line):
                with self.lock:
                    if not self._alive(run_id):
                        return
                    self.execution.update({"state": "failed", "message": "Pico 링크가 끊겼습니다",
                                           "finished": round(time.time(), 3)})
                self.event("dispatch", "출동 중단: Pico 링크 끊김")
                return
            self.event("spray", "살포 명령: %s (seq %d)" % (arm, seq))
            outcome = self._wait_spray(seq, run_id)
            if outcome == "stopped":
                return
            if outcome == "superseded":
                return
            if outcome != "done":
                self.write_pico("@@STOP {}")
                with self.lock:
                    if not self._alive(run_id):
                        return
                    self.execution.update({
                        "state": "failed", "current": arm, "seq": seq,
                        "message": "%s 살포 완료를 %.1f초 안에 받지 못했습니다(시간초과)" % (arm, SPRAY_TIMEOUT_S),
                        "finished": round(time.time(), 3)})
                self.event("dispatch", "출동 중단: %s 시간초과(%.1f초)" % (arm, SPRAY_TIMEOUT_S))
                return
        with self.lock:
            if not self._alive(run_id):
                return
            if self._estop_flag:
                self.execution.update({"state": "stopped", "current": None,
                                       "message": "비상 정지", "finished": round(time.time(), 3)})
            else:
                self.execution.update({"state": "done", "current": None,
                                       "message": "계획 실행 완료",
                                       "finished": round(time.time(), 3)})
            finished = self.execution["state"]
        if finished == "done":
            self.event("dispatch", "실행 완료 %s" % plan_id)
        self.write_pico("@@LED " + json.dumps({"arms": self.led_modes()},
                                              ensure_ascii=False, separators=(",", ":")))

    def _wait_spray(self, seq, run_id):
        deadline = time.time() + SPRAY_TIMEOUT_S
        with self.lock:
            while time.time() < deadline:
                if not self._alive(run_id):
                    return "superseded"
                if self._estop_flag:
                    return "stopped"
                if seq in self._done_seqs:
                    return "done"
                self.cond.wait(0.05)
        return "timeout"

    def estop(self):
        with self.lock:
            self._estop_flag = True
            running = self.execution.get("state") == "running"
            if running:
                self.execution.update({"state": "stopped", "current": None,
                                       "message": "비상 정지", "finished": round(time.time(), 3)})
            self.cond.notify_all()
        sent = self.write_pico("@@STOP {}")
        self.event("estop", "비상 정지%s" % ("" if sent else " (Pico 없음 — 화면만)"))
        return {"ok": True, "sent": sent, "was_running": running}

    def reset(self):
        with self.lock:
            self._estop_flag = True
            self._run_id += 1          # 진행 중이던 출동 스레드를 무효로 만든다
            self.reports = []
            self.pending = None
            self.approved = None
            self.plan_ack = None
            self.budget = DEFAULT_BUDGET
            self.use_sensor = False
            self.manual_t_bridge = None
            self.execution = self._blank_execution()
            self._done_seqs = set()
            self._estop_flag = False
            if self.timeline:
                self.index = 0
            self.refresh_step()
        self.write_pico("@@STOP {}")
        self.event("reset", "시연 초기화(제보·승인·실행·센서 보정)")
        return {"ok": True}

    # -- 스냅숏 ------------------------------------------------------------
    def snapshot(self):
        now = time.time()
        with self.lock:
            seen = self.pico_state["seen"]
            pico_age = round(now - seen, 1) if seen else None
            tel = self.pico_state["tel"]
            sensor = self.sensor_info()
            series = self.series.get(self.night or "")
            payload = {
                "now": round(now, 3),
                "time": time.strftime("%H:%M:%S"),
                "engine": {"ok": self.engine is not None and self.step is not None,
                           "present": self.engine is not None,
                           "error": self.engine_error},
                "step": self.step,
                "replay": {
                    "night": self.night,
                    "index": self.index,
                    "total": len(self.timeline),
                    "ts": self.current_ts(),
                    "auto": self.auto,
                    "sec_per_hour": self.sec_per_hour,
                    "nights": list(self.nights),
                    "timeline": list(self.timeline),
                },
                "series": ({"time": list(series["time"]),
                            "obs_ground": list(series["obs_ground"]),
                            "pred_h3": list(series["pred_h3"]),
                            "ready": True,
                            "note": "모델 예측(제보·센서 보정 전)"}
                           if series else {"ready": False, "note": "계산 중"}),
                "budget": self.budget,
                "reports": [dict(r) for r in self.reports],
                "pending_report": (json.loads(json.dumps(self.pending)) if self.pending else None),
                "proposal": self.proposal(),
                "approved": (dict(self.approved) if self.approved else None),
                "execution": json.loads(json.dumps(self.execution)),
                "sensor": {
                    "use_sensor": self.use_sensor,
                    "manual_t_bridge": self.manual_t_bridge,
                    "t_bridge": (sensor.get("payload") or {}).get("t_bridge"),
                    "wet": (sensor.get("payload") or {}).get("wet"),
                    "source": sensor.get("source") or "none",
                },
                "pico": {
                    "mode": self.pico_state["mode"],
                    "port": self.pico_state["port"],
                    "ok": bool(seen and now - seen <= PICO_FRESH_S),
                    "age": pico_age,
                    "tel": dict(tel) if tel else None,
                },
                "links": {
                    "pico": {"mode": self.pico_state["mode"],
                             "ok": bool(seen and now - seen <= PICO_FRESH_S),
                             "age": pico_age},
                    "llm": {"enabled": bool(not self.no_llm and llm.API_KEY),
                            "model": llm.TEXT_MODEL,
                            "engine": self.llm_last.get("engine"),
                            "error": self.llm_last.get("error"),
                            "latency_ms": self.llm_last.get("latency_ms")},
                },
                "events": list(self.events[-MAX_EVENT_LINES:]),
            }
        return payload


# ---------------------------------------------------------------------------
# Pico 링크(USB 시리얼)
# ---------------------------------------------------------------------------


class PicoLink(threading.Thread):
    """시리얼 115200. '@@TEL {..}'·'@@EVT {..}' 를 읽고 '@@LED {..}' 를 바뀔 때 + 2초마다 쓴다."""

    def __init__(self, model, port, path="", mode="serial"):
        threading.Thread.__init__(self, name="pico", daemon=True)
        self.model = model
        self.port = port
        self.path = path
        self.mode = mode
        self._stop = threading.Event()
        self._wlock = threading.Lock()   # LED 스레드와 출동 스레드가 같은 포트에 쓴다
        self._last_led = None
        self._last_tx = 0.0

    def write_line(self, line):
        with self._wlock:
            self.port.write((line + "\n").encode("utf-8"))
            self.port.flush()

    def run(self):
        if self.port is None:
            return
        while not self._stop.is_set():
            try:
                line = self.port.readline()
            except Exception as e:  # 케이블이 빠지면 링크만 끈다
                self.model.event("pico", "시리얼 읽기 실패: %s" % str(e)[:60])
                with self.model.lock:
                    self.model.pico_state["mode"] = "none"
                break
            if line:
                text = line.decode("utf-8", "replace").strip()
                if text.startswith("@@TEL"):
                    self.model.pico_telemetry(_json_tail(text, "@@TEL"))
                elif text.startswith("@@EVT"):
                    self.model.pico_event(_json_tail(text, "@@EVT"))
            else:
                time.sleep(0.02)
            self._maybe_send_led()
        try:
            self.port.close()
        except Exception:
            pass

    def _maybe_send_led(self):
        modes = self.model.led_modes()
        payload = json.dumps({"arms": modes}, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        if payload == self._last_led and now - self._last_tx < LED_RESEND_S:
            return
        try:
            self.write_line("@@LED " + payload)
            self._last_led = payload
            self._last_tx = now
        except Exception as e:
            self.model.event("pico", "LED 전송 실패: %s" % str(e)[:60])

    def stop(self):
        self._stop.set()


def open_pico_serial(spec):
    """--pico-serial auto|<포트>|none|fake. (port, path, mode) 를 돌려준다."""
    if spec in ("none", "", None):
        return None, "", "none"
    if spec == "fake":
        return FakePicoSerial(), "가짜 Pico", "fake"
    target = ""
    if spec == "auto":
        ports = find_serial_ports()
        if not ports:
            print("[Pico] 시리얼 포트를 찾지 못했습니다. 모의 실행으로 계속합니다.")
            return None, "", "none"
        if len(ports) > 1:
            print("[Pico] 시리얼 후보가 2개 이상이라 자동 연결을 끕니다:")
            for p in ports:
                print("   ", p)
            print("      원하는 포트를 --pico-serial <포트> 로 지정하세요.")
            return None, "", "none"
        target = ports[0]
    else:
        target = spec
    try:
        import serial
    except ImportError:
        print("[Pico] pyserial 이 없어 시리얼 연결을 끕니다.")
        return None, "", "none"
    try:
        ser = serial.Serial(target, 115200, timeout=0.2)
    except Exception as e:
        print("[Pico] 시리얼 열기 실패(%s): %s — 모의 실행으로 계속합니다." % (target, e))
        return None, "", "none"
    print("[Pico] 시리얼 연결:", target)
    return ser, target, "serial"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    model = None
    server_version = "icezero-cross/1.0"

    def log_message(self, fmt, *args):
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
            "/api/replay": self._replay,
            "/api/replay/step": self._step,
            "/api/replay/auto": self._auto,
            "/api/report": self._report,
            "/api/report/confirm": self._confirm,
            "/api/report/reject": self._reject,
            "/api/budget": self._budget,
            "/api/sensor": self._sensor,
            "/api/plan/approve": self._approve,
            "/api/dispatch": self._dispatch,
            "/api/estop": self._estop,
            "/api/reset": self._reset,
        }.get(path)
        if route is None:
            self._send(404, {"error": "없는 경로입니다: %s" % path})
            return
        try:
            status, payload = route(self._body())
        except HttpError as e:
            status, payload = e.status, {"error": e.message}
        except Exception as e:  # 마지막 그물
            status, payload = 500, {"error": "서버 오류: %s" % str(e)[:160]}
        self._send(status, payload)

    # -- 라우트 ------------------------------------------------------------
    def _replay(self, body):
        night = body.get("night")
        if not isinstance(night, str):
            raise HttpError(400, "night 필드가 필요합니다(YYYY-MM-DD)")
        result = self.model.set_night(night)
        return 200, dict(result, state=self.model.snapshot())

    def _step(self, body):
        hours = body.get("hours", 1)
        result = self.model.move(hours)
        return 200, dict(result, state=self.model.snapshot())

    def _auto(self, body):
        result = self.model.set_auto(body.get("on", False), body.get("sec_per_hour"))
        return 200, dict(result, state=self.model.snapshot())

    def _report(self, body):
        text = body.get("text")
        if not isinstance(text, str):
            raise HttpError(400, "text 필드가 필요합니다")
        return 200, self.model.submit_report(text)

    def _confirm(self, body):
        arms = body.get("arms")
        if arms is not None and not isinstance(arms, (list, tuple)):
            raise HttpError(400, "arms 는 갈래 ID 목록입니다")
        budget = body.get("budget")
        if budget is not None and (isinstance(budget, bool) or not isinstance(budget, (int, str))):
            raise HttpError(400, "budget 은 정수 또는 null 입니다")
        result = self.model.confirm_report(arms or [], budget)
        return 200, {"ok": True, "confirmed": result, "state": self.model.snapshot()}

    def _reject(self, body):
        return 200, self.model.reject_report()

    def _budget(self, body):
        value = body.get("budget")
        if value is None or isinstance(value, bool) or not isinstance(value, (int, str)):
            raise HttpError(400, "budget 은 0~4 정수입니다")
        result = self.model.set_budget(value)
        return 200, dict(result, state=self.model.snapshot())

    def _sensor(self, body):
        use = body.get("use_sensor")
        if use is not None and not isinstance(use, (bool, int, str)):
            raise HttpError(400, "use_sensor 는 true/false 입니다")
        result = self.model.set_sensor(use, body.get("t_bridge", "__keep__"))
        return 200, dict(result, state=self.model.snapshot())

    def _approve(self, body):
        result = self.model.approve_plan()
        return 200, dict(result, state=self.model.snapshot())

    def _dispatch(self, body):
        result = self.model.dispatch()
        return 200, {"ok": True, "result": result, "state": self.model.snapshot()}

    def _estop(self, body):
        result = self.model.estop()
        return 200, dict(result, state=self.model.snapshot())

    def _reset(self, body):
        result = self.model.reset()
        return 200, dict(result, state=self.model.snapshot())


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def load_engine():
    """Engine 을 불러온다. 실패해도 서버는 뜨고 상태에 오류를 남긴다."""
    import importlib
    try:
        module = importlib.import_module(ENGINE_MODULE)
    except Exception as e:
        return None, "엔진 모듈(%s)을 불러오지 못했습니다: %s" % (ENGINE_MODULE, str(e)[:160])
    cls = getattr(module, "Engine", None)
    if cls is None:
        return None, "엔진 모듈(%s)에 Engine 클래스가 없습니다" % ENGINE_MODULE
    try:
        engine = cls()
        engine.load()
        return engine, None
    except Exception as e:
        return None, "엔진 준비 실패: %s" % str(e)[:200]


def build_parser():
    p = argparse.ArgumentParser(description="ICE-ZERO 사거리 모형 서버(대시보드 + 재생 + Pico 링크)")
    p.add_argument("--host", default="0.0.0.0", help="HTTP 바인드 주소(기본 0.0.0.0)")
    p.add_argument("--port", type=int, default=HTTP_PORT, help="HTTP 포트(기본 8000)")
    p.add_argument("--pico-serial", default="auto", metavar="auto|PORT|none|fake",
                   help="Pico 시리얼 포트(기본 auto, fake 는 시험용 가짜 Pico)")
    p.add_argument("--no-llm", action="store_true", help="LLM 호출 없이 규칙 파서만 쓴다")
    p.add_argument("--events", default=None, help="이벤트 기록 파일(기본 server/events.jsonl)")
    p.add_argument("--night", default=None, help="처음 재생할 밤(YYYY-MM-DD)")
    return p


def serve(model, host, port):
    Handler.model = model
    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    args = build_parser().parse_args(argv)
    engine, error = load_engine()
    if error:
        print("[엔진]", error)
    model = Model(engine=engine, no_llm=args.no_llm, events_path=args.events,
                  night=args.night, engine_error=error)

    port, path, mode = open_pico_serial(args.pico_serial)
    link = None
    if port is not None:
        link = PicoLink(model, port, path, mode)
        model.pico = link
        link.start()
    model.pico_state["mode"] = mode
    model.pico_state["port"] = path

    httpd = serve(model, args.host, args.port)
    ip = local_ip()
    print("=" * 66)
    print("ICE-ZERO 사거리 모형 서버를 시작했습니다.")
    print("  대시보드(이 노트북): http://127.0.0.1:%d" % args.port)
    print("  같은 와이파이에서:   http://%s:%d" % (ip, args.port))
    print("  재생 밤: %s / 시각 %d/%d (%s)" % (
        model.night or "없음", model.index + 1 if model.timeline else 0,
        len(model.timeline), model.current_ts() or "—"))
    if model.nights:
        print("  후보 밤: %s" % ", ".join(model.nights[:5]))
    print("  Pico 링크: %s" % (path if port is not None else "없음(모의 실행)"))
    if args.no_llm:
        print("  LLM: 꺼짐(--no-llm) — 제보는 규칙 파서로만 해석합니다")
    elif llm.API_KEY:
        print("  LLM: %s (reasoning=%s)" % (llm.TEXT_MODEL, llm.TEXT_REASONING or "없음"))
    else:
        print("  LLM: 키 없음 — 규칙 파서로만 해석합니다(CMD_API_KEY 환경변수)")
    print("  예산 기본값: %d회분 / 이벤트 기록: %s" % (model.budget, model.events_path))
    print("=" * 66)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 멈춥니다.")
    finally:
        httpd.server_close()
        if link is not None:
            link.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
