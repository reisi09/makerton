"""제보 해석(4갈래판): Command Code LLM 호출 + 응답 검증 + 규칙 기반 기준선(rule_parse).

계약 4절을 옮긴다.
- LLM은 기기를 조종하지 않는다. 결과는 pending 에 저장만 하고, 사람이 확인해야 반영된다.
- LLM이 실패하면 rule_parse 결과를 쓰고 실패 이유를 남긴다.
- API 키는 환경변수 CMD_API_KEY 로만 읽고 출력·파일에 쓰지 않는다.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

API_BASE = os.environ.get("CMD_API_BASE", "https://api.commandcode.ai/provider/v1")
API_KEY = os.environ.get("CMD_API_KEY", "")
TEXT_MODEL = os.environ.get("CMD_TEXT_MODEL", "deepseek/deepseek-v4.1-flash")
# deepseek-v4.1-flash는 추론 모델이라 max_tokens를 추론에 다 써 버리면 본문이 빈다.
# 허용값: off|low|medium|high|xhigh|max ("none"/"minimal"은 400 오류). 빈 문자열이면 보내지 않는다.
TEXT_REASONING = os.environ.get("CMD_TEXT_REASONING", "low")
ZDR = os.environ.get("CMD_ZDR", "1") != "0"
TIMEOUT_S = 20
USER_AGENT = "icezero-model/1.0"

# 갈래 순서는 계약 2절(N·E·S·W)을 따른다.
ARMS = ("N", "E", "S", "W")
ARM_ROADS = {"N": "테헤란로115길", "E": "올림픽로", "S": "역삼로107길", "W": "테헤란로"}
ARM_LABEL_KR = {"N": "북쪽(일반)", "E": "동쪽(교량)", "S": "남쪽(일반)", "W": "서쪽(그늘)"}
BUDGET_MIN = 0
BUDGET_MAX = 4

CONDITIONS = ("slippery", "ice_suspected", "snow", "accident", "clear", "other")
CONDITION_KR = {"slippery": "미끄럼", "ice_suspected": "얼음 의심", "snow": "눈",
                "accident": "사고", "clear": "이상 없음", "other": "기타"}

DEFAULT_QUESTION = "어느 갈래인가요? 테헤란로115길(북)·올림픽로(동, 교량)·역삼로107길(남)·테헤란로(서, 그늘) 중에서 알려주세요."
TEHERAN_QUESTION = "테헤란로인가요, 테헤란로115길인가요? (테헤란로는 서쪽 그늘 갈래, 테헤란로115길은 북쪽 갈래입니다)"
PLACE_QUESTION = ("어느 갈래인가요? 테헤란로115길(북)/올림픽로(동, 교량)/"
                  "역삼로107길(남)/테헤란로(서, 그늘) 중에서 알려주세요.")

SYSTEM = (
    "너는 우드락 사거리 모형의 현장 제보를 구조화하는 도우미다. 너는 기기를 조종하지 않는다. "
    "사람이 확인하기 전에는 아무것도 실행되지 않는다.\n"
    "모형 설명\n"
    "- 강남구 실제 교차로(노드 1220041600)를 옮긴 십자 사거리다. 보드 위쪽이 북쪽이다. "
    "네 갈래는 N·E·S·W 이고 표시 순서도 N, E, S, W 다.\n"
    "- N 갈래: 테헤란로115길(북쪽, 일반 도로).\n"
    "- E 갈래: 올림픽로(동쪽). 이 갈래만 교량이다. 모형에서는 은박·난간·아래 하천 띠로 표시한다.\n"
    "- S 갈래: 역삼로107길(남쪽, 일반 도로).\n"
    "- W 갈래: 테헤란로(서쪽). 이 갈래만 그늘이다. 모형에서는 북서·남서 높은 건물 그림자로 표시한다.\n"
    "- 같은 말: 다리·교량·물 위·은박·동쪽·동측 = E, 테헤란로115길·115길·북쪽·북측 = N, "
    "역삼로107길·107길·남쪽·남측 = S, 테헤란로·그늘·응달·서쪽·서측 = W.\n"
    "- '테헤란로'라고만 하면 테헤란로(W)와 테헤란로115길(N) 사이에서 모호하다. "
    "이때는 arms를 비우고 ambiguous=true로 두고 되묻는다.\n"
    "- 예산 표현: '남은 제설제 3회분', '예산 2'처럼 횟수가 있으면 budget 정수다.\n"
    "출력은 JSON 객체 하나만 쓴다. 설명, 인사, 코드블록을 붙이지 않는다.\n"
    '스키마: {"arms":["E"], "condition":"slippery|ice_suspected|snow|accident|clear|other", '
    '"budget":2, "ambiguous":false, "question":"", "summary":"한 줄 요약"}\n'
    "규칙\n"
    "- arms는 N, E, S, W 중에서만 고른다. 다른 글자나 없는 갈래를 만들지 않는다.\n"
    "- 갈래가 모호하면 ambiguous=true로 두고 question에 되물을 한국어 문장 하나를 쓴다. "
    "갈래를 하나도 못 정했으면 '어느 갈래인가요? ...'처럼 묻는다.\n"
    "- budget은 제설제 횟수 이야기가 있을 때만 0~4 정수, 없으면 null이다.\n"
    "- 결빙을 확정하지 않는다. '결빙 확정', '빙판 확정' 같은 단정은 쓰지 않는다. "
    "없는 사실, 사람의 신원·과실을 만들지 않는다."
)


def call_api(path, payload, timeout=TIMEOUT_S, key=None, api_base=None):
    """스타터와 같은 방식. 기본 urllib UA는 Cloudflare 1010으로 막힌다."""
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
    choice = call_api("/chat/completions", body, timeout=timeout, key=key,
                      api_base=api_base)["choices"][0]
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


def _arms(value):
    """갈래 목록을 N·E·S·W 로 제한하고 계약 순서로 정리한다."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    if isinstance(value, dict):
        value = list(value.keys())
    if not isinstance(value, (list, tuple, set)):
        return []
    roads = dict((name, arm) for arm, name in ARM_ROADS.items())
    found = set()
    for item in value:
        if not isinstance(item, str):
            continue
        raw = item.strip()
        a = raw.upper()
        if a in ARMS:
            found.add(a)
        elif raw in roads:
            found.add(roads[raw])
    return [a for a in ARMS if a in found]


def _budget(value):
    """0~4 정수 또는 None. 문자열 '3회분'도 받아 준다."""
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
    if n < BUDGET_MIN:
        return BUDGET_MIN
    if n > BUDGET_MAX:
        return BUDGET_MAX
    return n


def _summary(arms, condition):
    if not arms:
        return "갈래 확인이 필요합니다"
    return "후보 갈래 %s / %s" % (", ".join(arms), CONDITION_KR.get(condition, "기타"))


def normalize(obj):
    """LLM 응답을 스키마에 맞게 고치거나 버린다. dict가 아니면 ValueError."""
    if not isinstance(obj, dict):
        raise ValueError("JSON 객체가 아님")
    arms = _arms(obj.get("arms"))
    condition = _text(obj.get("condition"), 20).lower()
    if condition not in CONDITIONS:
        condition = "other"
    ambiguous = bool(obj.get("ambiguous"))
    question = _text(obj.get("question"), 160)
    if ambiguous and not question:
        question = DEFAULT_QUESTION
    if not ambiguous:
        question = ""
    summary = _text(obj.get("summary"), 200)
    if not summary:
        summary = _summary(arms, condition)
    return {
        "arms": arms,
        "condition": condition,
        "budget": _budget(obj.get("budget")),
        "ambiguous": ambiguous,
        "question": question,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 규칙 기반 기준선
# ---------------------------------------------------------------------------

# 이름·동의어(계약 4절). 긴 표현을 먼저 본다.
N_WORDS = ("테헤란로115길", "115길", "북쪽", "북측", "북단", "북방면", "위쪽")
E_WORDS = ("올림픽로", "교량", "다리", "물 위", "은박", "교각", "동쪽", "동측", "동방면")
S_WORDS = ("역삼로107길", "107길", "남쪽", "남측", "남단", "남방면", "아래쪽")
W_WORDS = ("그늘", "응달", "방음벽", "해 안 드는", "서쪽", "서측", "서방면")
ALL_WORDS = ("사거리 전체", "네 갈래", "4갈래", "모든 갈래", "전체", "전부", "모두")
TEH_WORD = "테헤란로"


def _has(text, words):
    return any(w in text for w in words)


def _arm_order(arms):
    return [a for a in ARMS if a in set(arms)]


def rule_parse(text):
    """키워드 규칙 파서. LLM 실패 시 대체로 쓰고 정확도 비교의 기준선이 된다."""
    raw = (text or "").strip()
    if not raw:
        return normalize({"arms": [], "ambiguous": True, "question": PLACE_QUESTION,
                          "summary": "제보가 비어 있습니다", "condition": "other"})
    upper = raw.upper()

    # 1) 알파벳 갈래 표기(N, E, S, W)를 먼저 본다.
    explicit = []
    for m in re.findall(r"(?<![A-Z])([NESW])(?![A-Z])", upper):
        if m not in explicit:
            explicit.append(m)
    # 'S'는 문장에 흔하다. 갈래 표기로 보기 어려운 경우(예: 'S'만 덩그러니)는 살린다.
    explicit = _arm_order(explicit)

    arms = []
    ambiguous = False
    question = ""

    # 2) 도로 이름·동의어.
    has_115 = "115길" in raw
    explicit_w = _has(raw, W_WORDS)
    hits = set()
    if _has(raw, N_WORDS):
        hits.add("N")
    if _has(raw, E_WORDS):
        hits.add("E")
    if _has(raw, S_WORDS):
        hits.add("S")
    if explicit_w or (TEH_WORD in raw and not has_115):
        hits.add("W")

    # '테헤란로'만 있고 115길·그늘/서쪽 표기가 없으면 W/N 사이에서 모호하다.
    teheran_only = (TEH_WORD in raw) and not has_115 and not explicit_w
    if teheran_only:
        hits.discard("W")
        hits.discard("N")

    all_arms = _has(raw, ALL_WORDS)

    if explicit:
        arms = explicit
    elif all_arms:
        arms = list(ARMS)
    elif teheran_only:
        arms = []
        ambiguous = True
        question = TEHERAN_QUESTION
    elif hits:
        arms = _arm_order(hits)
    else:
        ambiguous = True
        question = PLACE_QUESTION

    budget = None
    m = re.search(r"(\d{1,2})\s*회분", raw) or re.search(r"예산[^0-9]{0,6}(\d{1,2})", raw)
    if m:
        budget = _budget(m.group(1))

    if _has(raw, ("사고", "전복", "추돌", "충돌")):
        condition = "accident"
    elif _has(raw, ("얼음", "얼었", "얼어", "빙판", "결빙", "살얼음")):
        condition = "ice_suspected"
    elif _has(raw, ("눈", "적설", "폭설")):
        condition = "snow"
    elif _has(raw, ("미끄", "젖", "물기", "물이 고")):
        condition = "slippery"
    elif _has(raw, ("깨끗", "이상 없", "건조")):
        condition = "clear"
    else:
        condition = "other"

    return {
        "arms": arms,
        "condition": condition,
        "budget": budget,
        "ambiguous": ambiguous,
        "question": question,
        "summary": _summary(arms, condition),
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
           "SYSTEM", "CONDITIONS", "ARMS", "ARM_ROADS"]
