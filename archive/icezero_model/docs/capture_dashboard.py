#!/usr/bin/env python3
"""가이드 PDF용 대시보드 화면을 만든다(실제 엔진, LLM 없이, 가짜 Pico).

    python3 icezero_model/docs/capture_dashboard.py   → docs/dashboard.png

서버를 임시 포트에 --no-llm --pico-serial fake로 띄운다. 기본 밤을 '일반 갈래 첫 후보' 시각까지 넘기고
제보 확인 → 계획 승인 → 출동을 실행한 뒤, 모호한 제보 하나를 남긴 상태를 Chrome headless로 찍는다.
진행 중 상태 값을 출력하므로 서버 전체 흐름의 스모크 확인도 겸한다. API 키를 쓰지 않는다.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 8766
OUT = os.path.join(HERE, "dashboard.png")

PORT = 8766
HEIGHT = 2600


def call(path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=data,
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    from night_data import replay
    _, night, rows, summary = replay()
    target = summary["first_general"] or summary["first_rec"]
    hours = rows.index(target)
    events = os.path.join(tempfile.mkdtemp(), "events.jsonl")
    env = dict(os.environ)
    env.pop("CMD_API_KEY", None)
    srv = subprocess.Popen([sys.executable, "server/icezero_server.py", "--no-llm", "--pico-serial", "fake",
                            "--host", "127.0.0.1", "--port", str(PORT), "--events", events, "--night", night],
                           cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        st = None
        for _ in range(150):
            try:
                st = call("/api/state")
                if st["engine"]["ok"] and st["series"].get("ready"):
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.2)
        print("engine.ok", st["engine"]["ok"], "| night", st["replay"]["night"], "| pico", st["pico"]["mode"], st["pico"]["ok"])
        call("/api/replay/step", {"hours": hours})
        st = call("/api/state")
        print("시각", st["replay"]["ts"], "| 제안", st["proposal"])
        call("/api/report", {"text": "그늘진 테헤란로에 살얼음, 제설제 2회분 남았어요"})
        st = call("/api/state")
        pend = st["pending_report"] or {}
        print("제보 해석(규칙)", json.dumps(pend.get("rule") or pend, ensure_ascii=False)[:200])
        call("/api/report/confirm", {"arms": ["W"], "budget": 2})
        call("/api/plan/approve", {})
        st = call("/api/state")
        print("승인 계획", st["approved"])
        call("/api/dispatch", {})
        for _ in range(60):
            st = call("/api/state")
            ex = st["execution"] or {}
            if ex.get("state") in ("done", "failed", "stopped", "aborted"):
                break
            time.sleep(0.25)
        print("실행", json.dumps(st["execution"], ensure_ascii=False)[:400])
        call("/api/report", {"text": "테헤란로가 미끄럽습니다"})
        st = call("/api/state")
        print("남긴 제보", json.dumps(st["pending_report"], ensure_ascii=False)[:200])
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1600,%d" % HEIGHT,
                        "--virtual-time-budget=5000", "--screenshot=" + OUT, "http://127.0.0.1:%d/" % PORT],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("저장:", OUT)
        split_panels(OUT)
        with open(events, encoding="utf-8") as f:
            lines = f.read().splitlines()
        print("events", len(lines), "줄 | 마지막:", lines[-1][:160] if lines else "")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()


def split_panels(path):
    """패널 사이 빈 줄을 찾아 위(사거리·예보)와 아래(제보·센서·계획·실행)로 잘라 저장한다."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(int)
    busy = (np.abs(a - a[:, :1, :]).sum(axis=2) > 30).mean(axis=1)
    spans, start = [], None
    for y in range(60, a.shape[0]):
        if busy[y] < 0.01:
            start = y if start is None else start
        elif start is not None:
            if y - start >= 5:
                spans.append((start, y))
            start = None
    if len(spans) < 4:
        raise SystemExit("패널 경계를 찾지 못했다: %s" % spans)
    top = im.crop((0, 0, im.width, spans[0][0]))
    bottom = im.crop((0, spans[1][1] - 6, im.width, spans[3][0]))
    top.save(os.path.join(HERE, "dashboard_top.png"))
    bottom.save(os.path.join(HERE, "dashboard_bottom.png"))
    print("잘라 저장: dashboard_top.png", top.size, "· dashboard_bottom.png", bottom.size)


if __name__ == "__main__":
    main()
