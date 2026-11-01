#!/usr/bin/env python3
"""가이드 PDF용 대시보드 화면을 만든다(LLM·보드·제설차 없이).

    python3 icezero_model/docs/capture_dashboard.py   → docs/dashboard.png

서버를 임시 포트에 --no-llm --board-serial none으로 띄우고, 수동 관측 → 제보 확인 → 계획 승인 →
모호한 제보 하나를 남긴 상태에서 Chrome headless로 찍은 뒤 서버를 끈다. API 키를 쓰지 않는다.
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
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT, UDP = 8765, 9765
OUT = os.path.join(HERE, "dashboard.png")


def post(path, body):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    events = os.path.join(tempfile.mkdtemp(), "events.jsonl")
    env = dict(os.environ)
    env.pop("CMD_API_KEY", None)
    srv = subprocess.Popen([sys.executable, "server/icezero_server.py", "--no-llm", "--board-serial", "none",
                            "--host", "127.0.0.1", "--port", str(PORT), "--udp-port", str(UDP), "--events", events],
                           cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/api/state" % PORT, timeout=1).read()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        post("/api/observe", {"caution": True})
        post("/api/report", {"text": "그늘 구간 하행 쪽에서 차가 미끄러졌대요, 제설제는 3회분 남았어요"})
        post("/api/report/confirm", {"cells": ["D3"], "budget": 3, "lane1_closed": []})
        post("/api/plan/approve", {})
        post("/api/report", {"text": "그늘진 데 미끄럽대요"})
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1600,1250",
                        "--virtual-time-budget=4000", "--screenshot=" + OUT, "http://127.0.0.1:%d/" % PORT],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("저장:", OUT)
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    main()
