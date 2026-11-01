"""피코 WH ↔ Command Code API 중계 서버 (Python 3.8+ 표준 라이브러리만 사용).

실행:
    export CMD_API_KEY=...         # Command Code Studio에서 만든 키. 코드·파일에 적지 않는다.
    export RELAY_TOKEN=team-secret # 팀 토큰. 피코(Wi-Fi 모드)·대시보드·초안 버튼이 모두 이 값을 쓴다
    HOST=127.0.0.1 python3 server.py   # USB 모드(기본, serial_bridge.py 사용): 노트북 안에서만 연다
    python3 server.py                  # Wi-Fi 모드: 0.0.0.0:8000
    대시보드: http://127.0.0.1:8000/?token=team-secret
    AGENT=1 TTS=1 python3 server.py    # LLM 에이전트 제안(조치가 바뀔 때만 chat 호출) → 대시보드 승인 → 명령·음성

엔드포인트:
    POST /decide  {"device", "profile", "state", "seq", "k", "pos"[, "poll": true]}
                  ⇒ {"action", "level", "p", "seq", "latency_ms"[, "cmd", "cmd_id"]}   (poll은 jev 없이 cmd만)
    POST /report  (대시보드 버튼) 선택한 이벤트로 관리자용 요청서 초안 생성. 자동 제출 없음
    POST /approve (대시보드 버튼) 에이전트 제안 승인. 낡은 제안은 폐기
    GET  /        대시보드(노드 지도·제안·이벤트)      GET /events  최근 이벤트 JSON      (GET은 ?token= 필요)
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_BASE = os.environ.get("CMD_API_BASE", "https://api.commandcode.ai/provider/v1")
API_KEY = os.environ.get("CMD_API_KEY", "")
RELAY_TOKEN = os.environ.get("RELAY_TOKEN", "")
DECISION_MODEL = os.environ.get("CMD_DECISION_MODEL", "typesafe/jev")
TEXT_MODEL = os.environ.get("CMD_TEXT_MODEL", "deepseek/deepseek-v4.1-flash")
# deepseek-v4.1-flash는 추론 모델이라 max_tokens를 추론에 다 쓰면 본문이 빈다(실호출 확인).
# off|low|medium|high|xhigh|max. 빈 문자열이면 보내지 않는다(이 옵션을 받지 않는 모델용).
TEXT_REASONING = os.environ.get("CMD_TEXT_REASONING", "low")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
AGENT = os.environ.get("AGENT", "0") == "1"          # LLM 에이전트 제안(노드 조치가 바뀔 때만 chat 호출)
AGENT_MAX_CALLS = int(os.environ.get("AGENT_MAX_CALLS", "300"))  # 실행 한 번당 호출 상한(비용 상한)
AGENT_MIN_GAP_S = 8                                   # 에이전트 호출 최소 간격(간격 중 변화는 최신 1건만 미뤄 처리)
CMD_TTL_S = 15                                        # 승인된 명령이 유효한 시간
PROPOSAL_TTL_S = 60                                   # 승인 대기 제안의 유효 시간
NODE_FRESH_S = 15                                     # 승인할 때 관련 노드가 이 시간 안에 보고했어야 함
TTS = os.environ.get("TTS", "0") == "1"              # 승인된 안내 문장을 노트북 스피커로 읽기
HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES = json.load(open(os.path.join(HERE, "profiles.json"), encoding="utf-8"))
LOG_PATH = os.path.join(HERE, "events.jsonl")

events = []  # 최근 이벤트(대시보드용). 전체 기록은 events.jsonl
next_id = [1]
nodes = {}         # 기기별 최신 상태 {device: {profile, state, action, level, pos, time, rev, seen}}
pending_cmd = {}   # 승인된 명령 {device: (level, 만료시각, cmd_id)}. 만료 전까지 poll마다 다시 보낸다
agent_log = []     # 최근 에이전트 제안
agent_state = {"calls": 0, "last": 0.0, "next_id": 1, "deferred": None}
lock = threading.Lock()
speech_lock = threading.Lock()  # 음성이 겹쳐 재생되지 않게

AGENT_SYSTEM = (
    "너는 피코 센서 노드들의 상태를 보고 현장 안내를 제안하는 에이전트다. 노드 상태만 근거로 JSON 객체 하나만 출력한다. "
    '형식: {"speech": "현장 사람에게 들려줄 쉬운 한국어 한두 문장(60자 이내), 필요 없으면 빈 문자열", '
    '"target": "경고 단계를 잠시 올릴 노드ID 하나, 없으면 빈 문자열", "level": 0~3 정수, '
    '"reason": "근거 한 문장", "map_note": "지도에 남길 20자 이내 메모"}. '
    "제안은 사람이 승인한 뒤에만 실행된다. 단계는 올리기만 하고 내리지 않는다. 차량·사람의 위반이나 신원은 추정하지 않는다.")


def speak(text):
    """승인된 안내 문장을 노트북 스피커로 읽는다(한 번에 하나씩). 실패하면 화면 안내만 남는다.
    macOS: say(한국어 음성 Yuna, 없으면 기본 음성), Windows: System.Speech(문장은 환경변수로 넘겨 인코딩 문제를 피함)."""
    import subprocess
    import sys
    with speech_lock:
        try:
            if sys.platform == "darwin":
                if subprocess.run(["say", "-v", os.environ.get("TTS_VOICE", "Yuna"), text], timeout=60).returncode:
                    subprocess.run(["say", text], timeout=60)
            elif os.name == "nt":
                ps = ("Add-Type -AssemblyName System.Speech; "
                      "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:TTS_TEXT)")
                subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=dict(os.environ, TTS_TEXT=text),
                               timeout=60)
            else:
                print("[TTS]", text)
        except Exception as e:
            print("[TTS 실패]", e)


def valid_cmd(dev):
    """만료되지 않은 승인 명령 (단계, cmd_id) 또는 None. lock 안에서 부른다."""
    c = pending_cmd.get(dev)
    if c and c[1] > time.time():
        return c[0], c[2]
    pending_cmd.pop(dev, None)
    return None


def approve(eid):
    """대시보드에서 사람이 고른 제안 하나를 승인한다. 시간이 지났거나, 제안 뒤 관련 노드의 상태(rev)가
    바뀌었거나, 관련 노드가 최근에 보고하지 않았으면 실행하지 않고 폐기한다. 검사와 명령 등록은 한 잠금 안에서 한다."""
    with lock:
        e = next((a for a in agent_log if a["id"] == eid), None)
        if e is None or e["status"] != "승인 대기":
            return
        now = time.time()
        stale = [d for d, rev in e["revs"].items()
                 if nodes.get(d, {}).get("rev") != rev or now - nodes.get(d, {}).get("seen", 0) > NODE_FRESH_S]
        if now - e["created"] > PROPOSAL_TTL_S:
            e["status"] = "폐기: 시간 초과"
        elif stale:
            e["status"] = "폐기: 제안 뒤 상황이 바뀌었거나 보고가 끊김(%s)" % ", ".join(stale)
        else:
            e["status"] = "승인됨"
            if e["target"]:
                old = valid_cmd(e["target"])
                level = max(e["level"], old[0]) if old else e["level"]  # 유효한 기존 명령보다 낮추지 않는다
                pending_cmd[e["target"]] = (level, now + CMD_TTL_S, e["id"])
        approved = e["status"] == "승인됨"
    append_log({"kind": "approve", "id": e["id"], "status": e["status"]})
    if approved and e["speech"] and TTS:
        threading.Thread(target=speak, args=(e["speech"],), daemon=True).start()


def agent_step(trigger):
    """노드 조치가 바뀌면 전체 노드 상태로 '승인 대기' 제안 하나를 만든다(음성 문장, 대상 노드 하나와 단계, 이유).
    최소 간격 안의 변화는 버리지 않고 가장 최근 1건만 간격이 끝난 뒤 처리한다."""
    with lock:
        wait = AGENT_MIN_GAP_S - (time.time() - agent_state["last"])
        if agent_state["calls"] >= AGENT_MAX_CALLS:
            return
        if wait > 0:
            if agent_state["deferred"] is None:
                threading.Timer(wait, run_deferred).start()
            agent_state["deferred"] = trigger
            return
        agent_state["calls"] += 1
        agent_state["last"] = time.time()
        snap = {d: {k: n[k] for k in ("profile", "state", "action", "level", "pos")} for d, n in nodes.items()}
        revs_now = {d: n["rev"] for d, n in nodes.items()}
    prompt = "방금 조치가 바뀐 노드: %s\n전체 노드 상태: %s" % (trigger, json.dumps(snap, ensure_ascii=False))
    try:
        text = chat_text(AGENT_SYSTEM, prompt, timeout=30)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("JSON 없음: " + text[:40])
        plan = json.loads(text[start:end + 1])
        if not isinstance(plan, dict):
            raise ValueError("JSON 객체가 아님")
    except Exception as e:
        plan = {"map_note": "(에이전트 실패: %s)" % str(e)[:60]}
    target, level = plan.get("target") or "", plan.get("level")
    if (not isinstance(target, str) or target not in snap or not isinstance(level, int)
            or isinstance(level, bool) or not 0 <= level <= 3):
        target, level = "", 0  # 허용 범위 밖의 명령은 버리고 음성·메모만 남긴다
    speech = str(plan.get("speech") or "")[:80]
    with lock:
        entry = {"id": agent_state["next_id"], "time": time.strftime("%H:%M:%S"), "created": time.time(),
                 "trigger": trigger, "speech": speech, "target": target, "level": level,
                 "reason": str(plan.get("reason") or "")[:80], "map_note": str(plan.get("map_note") or "")[:40],
                 "revs": {d: revs_now[d] for d in {trigger, target} if d in revs_now},
                 "status": "승인 대기" if (target or speech) else "할 일 없음"}
        agent_state["next_id"] += 1
        agent_log.append(entry)
        del agent_log[:-20]
    append_log(dict(entry, kind="agent"))


def run_deferred():
    with lock:
        trigger, agent_state["deferred"] = agent_state["deferred"], None
    if trigger:
        agent_step(trigger)


def call_api(path, payload, timeout):
    req = urllib.request.Request(
        API_BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        # 기본 Python-urllib User-Agent는 Cloudflare가 1010 오류로 차단하므로 직접 지정한다
        headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json",
                 "User-Agent": "suwon-pico-relay/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def chat_text(system, user, timeout):
    """chat 모델 응답 본문. 추론에 토큰을 다 써서 본문이 비면 이유와 함께 실패로 올린다."""
    body = {"model": TEXT_MODEL, "max_tokens": 2000,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if TEXT_REASONING:
        body["reasoning_effort"] = TEXT_REASONING
    choice = call_api("/chat/completions", body, timeout=timeout)["choices"][0]
    text = (choice["message"].get("content") or "").strip()
    if not text:
        raise ValueError("빈 응답(finish_reason=%s)" % choice.get("finish_reason"))
    return text


def state_text(profile, state):
    labels = profile.get("labels", {})
    parts = ["%s=%s" % (labels.get(k, k), v) for k, v in state.items()]
    parts.append("현재 시각=" + time.strftime("%H:%M"))  # 피코는 시계가 없으므로 중계 서버가 붙인다
    return profile["context"] + "\n현재 센서 상태: " + ", ".join(parts)


def decide(profile, state):
    """jev의 'action' 선택지 확률이 min_p 미만이면 'review'(사람 확인)로 내린다."""
    res = call_api("/systemone", {"model": DECISION_MODEL, "state": state_text(profile, state),
                                  "questions": profile["questions"]}, timeout=6)
    answers = res["answers"]
    act = answers["action"]
    action = act["choice"]
    p = act["probabilities"][action]
    if p < profile.get("min_p", 0.8):
        action = "review"
    return {"action": action, "level": profile["levels"][action], "p": round(p, 3), "answers": answers}


def write_report(event, profile):
    prompt = (profile["report_prompt"] + "\n\n장소: " + profile.get("place", "시연 부스") +
              "\n발생 시각: " + event["time"] + "\n센서 상태: " + json.dumps(event["state"], ensure_ascii=False) +
              "\nAI 판단(확률): " + json.dumps(event["answers"], ensure_ascii=False))
    try:
        text = chat_text("너는 수원시 생활민원 기록을 돕는 보조원이다. 주어진 센서 기록만 사실로 쓰고, "
                         "위반·책임 판단은 하지 않는다. 한국어 300자 이내.", prompt, timeout=60)
    except Exception as e:  # 초안 실패가 현장 동작을 막지 않게 한다
        text = "(초안 생성 실패: %s)" % e
    with lock:
        event["report"] = text
    append_log({"kind": "report", "id": event["id"], "report": text})


def append_log(obj):
    with lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")

    def do_POST(self):
        if self.path == "/report":
            return self._report()
        if self.path == "/approve":
            return self._approve()
        if self.path != "/decide":
            return self._send(404, {"error": "not found"})
        if RELAY_TOKEN and self.headers.get("X-Relay-Token") != RELAY_TOKEN:
            return self._send(401, {"error": "bad token"})
        try:
            req = json.loads(self._body())
            profile = PROFILES[req["profile"]]
            state = req["state"]
        except Exception as e:
            return self._send(400, {"error": "bad request: %s" % e})
        dev = str(req.get("device", "?"))[:32]
        pos = req.get("pos")  # 노드 지도 좌표(0~100). 숫자 두 개가 아니면 버린다
        pos = ([max(0, min(100, int(v))) for v in pos] if isinstance(pos, list) and len(pos) == 2
               and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in pos) else None)
        with lock:  # 어떤 요청이든 '마지막 보고 시각'과 피코의 상황 키(k)를 갱신한다. k가 바뀌면 rev를 올린다
            n = nodes.setdefault(dev, {"profile": req["profile"], "state": state, "action": None, "level": 0,
                                       "pos": pos, "time": "", "rev": 0, "seen": 0.0, "k": None})
            n["seen"] = time.time()
            if req.get("k") != n["k"]:
                n["k"] = req.get("k")
                n["rev"] += 1
            c = valid_cmd(dev) if req.get("poll") else None
        if req.get("poll"):  # AI 판단 없이 승인된 명령만 확인(API를 부르지 않음)
            resp = {"seq": req.get("seq")}
            if c:
                resp["cmd"], resp["cmd_id"] = c
            return self._send(200, resp)
        t0 = time.time()
        try:
            out = decide(profile, state)
        except urllib.error.HTTPError as e:
            return self._send(502, {"error": "api %s: %s" % (e.code, e.read()[:300].decode("utf-8", "replace")),
                                    "seq": req.get("seq")})
        except Exception as e:
            return self._send(502, {"error": "api: %s" % e, "seq": req.get("seq")})
        with lock:
            event = {"id": next_id[0], "time": time.strftime("%Y-%m-%d %H:%M:%S"), "device": dev,
                     "profile": req["profile"], "state": state, "local_level": req.get("local_level"),
                     "action": out["action"], "level": out["level"], "p": out["p"], "answers": out["answers"],
                     "latency_ms": int((time.time() - t0) * 1000), "report": None}
            next_id[0] += 1
            events.append(event)
            del events[:-50]
            n = nodes[dev]
            changed = n["action"] != out["action"]
            if changed or n["level"] != out["level"]:
                n["rev"] += 1
            n.update(profile=req["profile"], state=state, action=out["action"], level=out["level"], pos=pos,
                     time=event["time"])
            c = valid_cmd(dev)
        append_log(event)
        if AGENT and changed:
            threading.Thread(target=agent_step, args=(dev,), daemon=True).start()
        resp = {"action": out["action"], "level": out["level"], "p": out["p"],
                "seq": req.get("seq"), "latency_ms": event["latency_ms"]}
        if c:  # 승인된 명령은 만료 전까지 응답마다 다시 싣는다(피코는 cmd_id로 중복 적용을 막는다)
            resp["cmd"], resp["cmd_id"] = c
        self._send(200, resp)

    def _report(self):
        """대시보드에서 사람이 누를 때만 chat 모델을 부른다(호출 수·비용 상한을 사람이 쥔다).
        폼에 팀 토큰이 들어 있어야 한다(다른 사람·다른 사이트가 유료 생성을 대신 누르지 못하게)."""
        form = urllib.parse.parse_qs(self._body())
        if RELAY_TOKEN and form.get("token", [""])[0] != RELAY_TOKEN:
            return self._send(401, {"error": "bad token"})
        try:
            eid = int(form["id"][0])
        except (KeyError, ValueError):
            return self._send(400, {"error": "id 필요"})
        with lock:
            ev = next((e for e in events if e["id"] == eid), None)
            if ev is not None and ev["report"] is None:
                ev["report"] = "(초안 작성 중…)"
            else:
                ev = None
        if ev is not None:
            threading.Thread(target=write_report, args=(ev, PROFILES[ev["profile"]]), daemon=True).start()
        self.send_response(303)
        self.send_header("Location", "/?" + urllib.parse.urlencode({"token": RELAY_TOKEN}))
        self.end_headers()

    def _approve(self):
        """대시보드의 '승인' 버튼. 시간이 지났거나 상황이 바뀐 제안은 approve()가 폐기한다."""
        form = urllib.parse.parse_qs(self._body())
        if RELAY_TOKEN and form.get("token", [""])[0] != RELAY_TOKEN:
            return self._send(401, {"error": "bad token"})
        try:
            approve(int(form["id"][0]))
        except (KeyError, ValueError):
            return self._send(400, {"error": "id 필요"})
        self.send_response(303)
        self.send_header("Location", "/?" + urllib.parse.urlencode({"token": RELAY_TOKEN}))
        self.end_headers()

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if RELAY_TOKEN and urllib.parse.parse_qs(url.query).get("token", [""])[0] != RELAY_TOKEN:
            return self._send(401, {"error": "대시보드 주소 끝에 ?token=팀토큰 을 붙이세요"})
        if url.path == "/events":
            with lock:
                return self._send(200, events[-50:])
        if url.path != "/":
            return self._send(404, {"error": "not found"})
        tok = escape(RELAY_TOKEN, quote=True)
        colors = {0: "#2e7d32", 1: "#f9a825", 2: "#c62828", 3: "#6a1b9a"}
        with lock:
            dots = "".join(  # 노드 지도: 피코가 보낸 pos(0~100 좌표). 없으면 순서대로 놓는다
                "<circle cx='%d' cy='%d' r='5' fill='%s'/><text x='%d' y='%d' font-size='4'>%s · %s</text>" % (
                    x, y, colors.get(n["level"], "#555"), x + 6, y + 1, escape(d), escape(str(n["action"])))
                for i, (d, n) in enumerate(sorted(nodes.items()))
                for x, y in [tuple(n["pos"]) if n.get("pos") else (15 + 25 * i, 50)])
            alog = "".join("<li>#%d %s [%s] 「%s」 대상=%s 단계=%s — %s <i>%s</i> — <b>%s</b>%s</li>" % (
                a["id"], escape(a["time"]), escape(a["trigger"]), escape(a["speech"]), escape(a["target"] or "-"),
                a["level"], escape(a["reason"]), escape(a["map_note"]), escape(a["status"]),
                "" if a["status"] != "승인 대기" else
                " <form style='display:inline' method='post' action='/approve'><input type='hidden' name='id' value='%d'>"
                "<input type='hidden' name='token' value='%s'><button>승인</button></form>" % (a["id"], tok))
                for a in reversed(agent_log))
            rows = "".join(
                "<tr><td>%d<br>%s</td><td>%s<br>%s</td><td>%s</td><td><b>%s</b><br>p=%s, %sms</td><td><pre>%s</pre></td>"
                "<td>%s</td></tr>" % (
                    e["id"], escape(e["time"]), escape(e["device"]), escape(e["profile"]),
                    escape(json.dumps(e["state"], ensure_ascii=False)), escape(e["action"]), e["p"], e["latency_ms"],
                    escape(json.dumps(e["answers"], ensure_ascii=False, indent=1)),
                    escape(e["report"]) if e["report"] else
                    "<form method='post' action='/report'><input type='hidden' name='id' value='%d'>"
                    "<input type='hidden' name='token' value='%s'><button>요청서 초안 만들기</button></form>" % (e["id"], tok))
                for e in reversed(events))
        html = ("<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='5'>"
                "<title>Pico × Command Code</title><style>body{font-family:sans-serif}td,th{border:1px solid #ccc;"
                "padding:4px;vertical-align:top;font-size:13px}pre{margin:0;font-size:11px}</style>"
                "<h2>노드 지도</h2><svg viewBox='0 0 100 100' width='420' height='420' style='border:1px solid #ccc'>"
                + dots + "</svg><h3>에이전트 (%s, 호출 %d회)</h3><ul>%s</ul>" % (
                    "켜짐" if AGENT else "꺼짐", agent_state["calls"], alog) +
                "<h2>피지컬 AI 이벤트 (5초마다 새로고침)</h2><table><tr><th>#/시각</th><th>기기/프로필</th>"
                "<th>센서 상태</th><th>AI 조치</th><th>jev 확률</th><th>초안(사람 확인 후 제출)</th></tr>" + rows + "</table>")
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("CMD_API_KEY 환경변수가 없습니다.")
    for name, prof in PROFILES.items():  # 프로필 실수(선택지·단계 불일치)를 시작할 때 잡는다
        crit = set(prof["questions"]["action"]["criteria"])
        if crit | {"review"} != set(prof["levels"]):
            raise SystemExit("profiles.json '%s': action 선택지와 levels 키가 다릅니다" % name)
    print("relay on %s:%d, profiles=%s" % (HOST, PORT, ", ".join(PROFILES)))
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
