"""제보 해석: Command Code LLM 호출 + 응답 검증 + 규칙 기반 기준선(rule_parse).

계약 5절을 그대로 옮긴다.
- LLM은 차를 조종하지 않는다. 결과는 pending 에 저장만 하고, 사람이 확인해야 반영된다.
- LLM이 실패하면 rule_parse 결과를 쓰고 실패 이유를 남긴다.
- API 키는 환경변수 CMD_API_KEY 로만 읽고 출력·파일에 쓰지 않는다.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

from plan import CELLS, LOOP, SECTION_OF

API_BASE = os.environ.get("CMD_API_BASE", "https://api.commandcode.ai/provider/v1")
API_KEY = os.environ.get("CMD_API_KEY", "")
TEXT_MODEL = os.environ.get("CMD_TEXT_MODEL", "deepseek/deepseek-v4.1-flash")
# deepseek-v4.1-flash는 추론 모델이라 max_tokens를 추론에 다 써 버리면 본문이 빈다.
# 허용값: off|low|medium|high|xhigh|max ("none"/"minimal"은 400 오류). 빈 문자열이면 보내지 않는다.
TEXT_REASONING = os.environ.get("CMD_TEXT_REASONING", "low")
ZDR = os.environ.get("CMD_ZDR", "1") != "0"
TIMEOUT_S = 20
USER_AGENT = "icezero-model/1.0"

CONDITIONS = ("slippery", "ice_suspected", "snow", "accident", "clear", "other")
CONDITION_KR = {"slippery": "미끄럼", "ice_suspected": "얼음 의심", "snow": "눈",
                "accident": "사고", "clear": "이상 없음", "other": "기타"}

DEFAULT_QUESTION = "상행(동쪽 방향)인가요, 하행(서쪽 방향)인가요?"
SECTION_QUESTION = "어느 구간인가요? S1 일반(서쪽)·S2 교량·S3 그늘·S4 일반(동쪽) 중에서 알려주세요."
PLACE_QUESTION = ("어느 방향·구간인가요? 상행(동쪽)/하행(서쪽)과 "
                  "S1 일반·S2 교량·S3 그늘·S4 일반 중에서 알려주세요.")

SYSTEM = (
    "너는 우드락 도로 모형의 제보를 구조화하는 도우미다. 너는 차를 조종하지 않는다. "
    "사람이 확인하기 전에는 아무것도 실행되지 않는다.\n"
    "모형 설명\n"
    "- 왕복 4차로 직선 도로(1800x600mm). 상행은 동쪽(→) 아래 차로, 하행은 서쪽(←) 위 차로다.\n"
    "- 칸 8개: 상행 U1 U2 U3 U4, 하행 D1 D2 D3 D4. U1/D1이 서쪽 끝, U4/D4가 동쪽 끝이다.\n"
    "- 구간: S1 일반(서쪽), S2 교량(은박), S3 그늘(양옆 방음벽), S4 일반(동쪽). "
    "그래서 U1/D1=S1, U2/D2=S2(교량), U3/D3=S3(그늘), U4/D4=S4다.\n"
    "- 같은 말: 물 위 지나는 구간·다리·교량·은박 = S2, 해 안 드는 벽 옆·그늘·방음벽 = S3, "
    "동쪽으로 가는 쪽·동측·동쪽 방면 = 상행(U), 서쪽 방면·서측·서쪽으로 가는 쪽 = 하행(D), "
    "양방향·왕복·양쪽·둘 다 = U와 D 모두.\n"
    "- 예산 표현: '남은 제설제 3회분', '예산 5'처럼 횟수가 있으면 budget 정수다.\n"
    "출력은 JSON 객체 하나만 쓴다. 설명, 인사, 코드블록을 붙이지 않는다.\n"
    '스키마: {"cells":["D3"], "condition":"slippery|ice_suspected|snow|accident|clear|other", '
    '"budget":3, "lane1_closed":["U3"], "ambiguous":false, "question":"", "summary":"한 줄 요약"}\n'
    "규칙\n"
    "- cells는 위 8개 ID 중에서만 고른다. 다른 글자나 없는 칸을 만들지 않는다.\n"
    "- 위치가 모호하면 ambiguous=true로 두고 question에 되물을 한국어 문장 하나를 쓴다. "
    "방향이 없으면 '상행(동쪽 방향)인가요, 하행(서쪽 방향)인가요?'처럼 묻는다.\n"
    "- budget은 제설제 횟수 이야기가 있을 때만 0~8 정수, 없으면 null이다.\n"
    "- lane1_closed는 화면 표시용 목록이다. 1차로는 제설차가 쓰지 않는다.\n"
    "- 결빙을 확정하지 않는다. 없는 사실, 사람의 신원·과실을 만들지 않는다."
)


def call_api(path, payload, timeout=TIMEOUT_S, key=None, api_base=None):
    """스타터(relay/server.py)와 같은 방식. 기본 urllib UA는 Cloudflare 1010으로 막힌다."""
    headers = {"Authorization": "Bearer " + (key if key is not None else API_KEY),
               "Content-Type": "application/json",
               "User-Agent": USER_AGENT}
    if ZDR:
        headers["x-cmd-zdr"] = "1"
    req = urllib.request.Request((api_base or API_BASE) + path,
                                 data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def chat_text(system, user, timeout=TIMEOUT_S, key=None, api_base=None,
              model=None, reasoning=None):
    """chat 응답 본문. 추론에 토큰을 다 써 본문이 비면 이유와 함께 실패로 올린다."""
    body = {"model": model or TEXT_MODEL, "max_tokens": 2000,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    effort = TEXT_REASONING if reasoning is None else reasoning
    if effort:
        body["reasoning_effort"] = effort
    choice = call_api("/chat/completions", body, timeout=timeout, key=key, api_base=api_base)["choices"][0]
    text = (choice.get("message") or {}).get("content") or ""
    text = text.strip()
    if not text:
        raise ValueError("빈 응답(finish_reason=%s)" % choice.get("finish_reason"))
    return text


def extract_json(text):
    """응답 문자열의 첫 '{'부터 마지막 '}'까지 잘라 JSON 객체로 만든다."""
    if not isinstance(text, str):
        raise ValueError("응답이 문자열이 아님")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON 없음")
    try:
        obj = json.loads(text[start:end + 1])
    except ValueError as e:
        raise ValueError("JSON 해석 실패: %s" % str(e)[:60])
    if not isinstance(obj, dict):
        raise ValueError("JSON 객체가 아님")
    return obj


def _text(value, limit):
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _cells(value):
    """칸 목록을 8개 ID로 제한하고 루프 순서로 정리한다."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    if isinstance(value, dict):
        value = list(value.keys())
    if not isinstance(value, (list, tuple, set)):
        return []
    found = set()
    for item in value:
        if isinstance(item, str):
            c = item.strip().upper()
            if c in CELLS:
                found.add(c)
    return [c for c in LOOP if c in found]


def _budget(value):
    """0~8 정수 또는 None. 문자열 '3회분'도 받아 준다."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        m = re.search(r"\d{1,2}", value)
        if not m:
            return None
        value = int(m.group(0))
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return 0
    if n > 8:
        return 8
    return n


def _summary(cells, condition):
    if not cells:
        return "위치 확인이 필요합니다"
    return "후보 칸 %s / %s" % (", ".join(cells), CONDITION_KR.get(condition, "기타"))


def normalize(obj):
    """LLM 응답을 스키마에 맞게 고치거나 버린다. dict가 아니면 ValueError."""
    if not isinstance(obj, dict):
        raise ValueError("JSON 객체가 아님")
    cells = _cells(obj.get("cells"))
    condition = _text(obj.get("condition"), 20).lower()
    if condition not in CONDITIONS:
        condition = "other"
    ambiguous = bool(obj.get("ambiguous"))
    question = _text(obj.get("question"), 160)
    if ambiguous and not question:
        question = DEFAULT_QUESTION if not cells else SECTION_QUESTION
    if not ambiguous:
        question = ""
    summary = _text(obj.get("summary"), 200)
    if not summary:
        summary = _summary(cells, condition)
    return {
        "cells": cells,
        "condition": condition,
        "budget": _budget(obj.get("budget")),
        "lane1_closed": _cells(obj.get("lane1_closed")),
        "ambiguous": ambiguous,
        "question": question,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 규칙 기반 기준선
# ---------------------------------------------------------------------------

BRIDGE_WORDS = ("교량", "다리", "물 위", "은박", "교각", "다리 위", "다리 밑")
SHADE_WORDS = ("그늘", "방음벽", "응달", "해 안 드는", "햇빛이 안", "그늘진")
UP_WORDS = ("상행", "동쪽", "동측", "동방면", "오른쪽")
DOWN_WORDS = ("하행", "서쪽", "서측", "서방면", "왼쪽")
BOTH_WORDS = ("양방향", "왕복", "양쪽", "둘 다", "both")
LANE1_WORDS = ("1차로",)
CLOSE_WORDS = ("통제", "막", "닫", "폐쇄", "공사", "사고")


def _has(text, words):
    return any(w in text for w in words)


def _cells_of(sections, dirs):
    return [c for c in LOOP if SECTION_OF[c] in sections and (not dirs or c[0] in dirs)]


def rule_parse(text):
    """키워드 규칙 파서. LLM 실패 시 대체로 쓰고 정확도 비교의 기준선이 된다."""
    raw = (text or "").strip()
    if not raw:
        return normalize({"cells": [], "ambiguous": True, "question": PLACE_QUESTION,
                          "summary": "제보가 비어 있습니다", "condition": "other"})
    upper = raw.upper()

    explicit = []
    for m in re.findall(r"[UD][1-4]", upper):
        if m not in explicit:
            explicit.append(m)
    explicit = _cells(explicit)

    sections = []
    if _has(raw, BRIDGE_WORDS):
        sections.append("S2")
    if _has(raw, SHADE_WORDS):
        sections.append("S3")

    dirs = []
    if _has(raw, BOTH_WORDS) or (_has(raw, UP_WORDS) and _has(raw, DOWN_WORDS)):
        dirs = ["U", "D"]
    elif _has(raw, UP_WORDS):
        dirs = ["U"]
    elif _has(raw, DOWN_WORDS):
        dirs = ["D"]

    cells = []
    ambiguous = False
    question = ""
    if explicit:
        cells = explicit
    elif sections and dirs:
        cells = _cells_of(sections, dirs)
    elif sections:
        cells = _cells_of(sections, None)
        ambiguous = True
        question = DEFAULT_QUESTION
    elif dirs:
        ambiguous = True
        question = SECTION_QUESTION
    else:
        ambiguous = True
        question = PLACE_QUESTION

    budget = None
    m = re.search(r"(\d{1,2})\s*회분", raw) or re.search(r"예산[^0-9]{0,6}(\d{1,2})", raw)
    if m:
        budget = _budget(m.group(1))

    if _has(raw, ("사고", "전복", "추돌")):
        condition = "accident"
    elif _has(raw, ("얼음", "빙판", "결빙", "살얼음")):
        condition = "ice_suspected"
    elif _has(raw, ("눈", "적설", "폭설")):
        condition = "snow"
    elif _has(raw, ("미끄러", "미끄럼", "젖", "물기", "물이 고")):
        condition = "slippery"
    elif _has(raw, ("깨끗", "이상 없", "건조")):
        condition = "clear"
    else:
        condition = "other"

    lane1 = []
    if _has(raw, LANE1_WORDS) and _has(raw, CLOSE_WORDS):
        lane1 = _cells_of(("S1", "S2", "S3", "S4"), dirs) if dirs else []

    return {
        "cells": cells,
        "condition": condition,
        "budget": budget,
        "lane1_closed": lane1,
        "ambiguous": ambiguous,
        "question": question,
        "summary": _summary(cells, condition),
    }


def interpret(text, use_llm=True, key=None, timeout=TIMEOUT_S, api_base=None,
              model=None, reasoning=None):
    """제보 문장 하나를 해석한다. LLM이 실패하면 rule_parse 결과로 대체하고 이유를 남긴다.

    반환: {"engine": "llm"|"rule", "result": 스키마, "rule": rule_parse 결과,
           "error": None|문자열, "latency_ms": float}
    """
    rule = rule_parse(text)
    if not use_llm:
        return {"engine": "rule", "result": rule, "rule": rule, "error": None, "latency_ms": 0.0}
    started = time.time()
    try:
        raw = chat_text(SYSTEM, "제보: " + (text or "").strip(), timeout=timeout,
                        key=key, api_base=api_base, model=model, reasoning=reasoning)
        result = normalize(extract_json(raw))
        return {"engine": "llm", "result": result, "rule": rule, "error": None,
                "latency_ms": round((time.time() - started) * 1000.0, 1)}
    except Exception as e:  # 어떤 실패든 현장 동작을 막지 않는다
        return {"engine": "rule", "result": rule, "rule": rule,
                "error": "LLM 실패: %s" % str(e)[:120],
                "latency_ms": round((time.time() - started) * 1000.0, 1)}


__all__ = ["call_api", "chat_text", "extract_json", "normalize", "rule_parse", "interpret",
           "SYSTEM", "CONDITIONS"]
