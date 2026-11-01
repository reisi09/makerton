"""제보 해석 평가 — 규칙 파서 vs LLM 실호출. tests/eval_cross_result.json 에 결과를 쓴다.

실행
    python3 tests/eval_reports_cross.py                 # 키가 있으면 LLM 도 부른다(최대 12회)
    python3 tests/eval_reports_cross.py --rule-only      # 규칙만(네트워크 없음)
    CMD_API_KEY="$(omp token commandcode)" python3 tests/eval_reports_cross.py

채점 기준(둘 다 같은 정답 파일을 쓴다)
- arms 정확도: 갈래 집합이 정답과 정확히 같은가
- ambiguous 정확도: 모호 판정이 정답과 같은가
- budget 정확도: 정답에 budget 이 있을 때만 센다
- exact: arms·ambiguous·budget 세 가지가 모두 맞는가
"""

import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, "server")
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import llm  # noqa: E402

REPORTS = os.path.join(HERE, "reports_cross.json")
RESULT = os.path.join(HERE, "eval_cross_result.json")


def load_reports(path=REPORTS):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("reports") or []


def score_one(result, gold):
    arms_ok = sorted(result.get("arms") or []) == sorted(gold.get("gold_arms") or [])
    amb_ok = bool(result.get("ambiguous")) == bool(gold.get("gold_ambiguous"))
    gold_budget = gold.get("gold_budget")
    if gold_budget is None:
        budget_ok = None
    else:
        budget_ok = result.get("budget") == gold_budget
    exact = arms_ok and amb_ok and (budget_ok is not False)
    return {"arms_ok": arms_ok, "ambiguous_ok": amb_ok, "budget_ok": budget_ok, "exact": exact}


def summarize(items):
    total = len(items)
    if not total:
        return {"count": 0}
    arms = sum(1 for i in items if i["score"]["arms_ok"])
    amb = sum(1 for i in items if i["score"]["ambiguous_ok"])
    exact = sum(1 for i in items if i["score"]["exact"])
    budget_items = [i for i in items if i["score"]["budget_ok"] is not None]
    summary = {
        "count": total,
        "arms_correct": arms,
        "arms_accuracy": round(arms / float(total), 3),
        "ambiguous_correct": amb,
        "ambiguous_accuracy": round(amb / float(total), 3),
        "exact_correct": exact,
        "exact_accuracy": round(exact / float(total), 3),
    }
    if budget_items:
        ok = sum(1 for i in budget_items if i["score"]["budget_ok"])
        summary["budget_count"] = len(budget_items)
        summary["budget_accuracy"] = round(ok / float(len(budget_items)), 3)
    return summary


def run_rule(reports):
    items = []
    for gold in reports:
        result = llm.rule_parse(gold["text"])
        items.append({"text": gold["text"], "gold": gold, "result": result,
                      "score": score_one(result, gold)})
    return items


def reuse_llm(reports, path):
    """저장된 평가 결과의 LLM 해석을 다시 채점한다(네트워크 없음)."""
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    by_text = {}
    for item in (saved.get("items") or {}).get("llm") or []:
        by_text[item["text"]] = item
    items = []
    for gold in reports:
        item = by_text.get(gold["text"])
        if item is None:
            return None
        result = item["result"]
        items.append({"text": gold["text"], "gold": gold, "result": result,
                      "engine": item.get("engine"), "error": item.get("error"),
                      "latency_ms": item.get("latency_ms"),
                      "score": score_one(result, gold)})
    return items


def run_llm(reports, indexes=None):
    """indexes 가 있으면 그 번호의 제보만 LLM 으로 부른다(호출 예산 조절)."""
    items = []
    for i, gold in enumerate(reports):
        if indexes is not None and i not in indexes:
            continue
        out = llm.interpret(gold["text"], use_llm=True)
        result = out["result"]
        item = {"text": gold["text"], "gold": gold, "result": result,
                "engine": out["engine"], "error": out["error"],
                "latency_ms": out["latency_ms"],
                "score": score_one(result, gold)}
        items.append(item)
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description="제보 해석 규칙 vs LLM 평가")
    parser.add_argument("--rule-only", action="store_true", help="LLM 호출 없이 규칙만 평가")
    parser.add_argument("--reports", default=REPORTS)
    parser.add_argument("--out", default=RESULT)
    parser.add_argument("--llm-from", default=None,
                        help="이미 저장한 결과 파일의 LLM 해석을 다시 채점한다(네트워크 없음)")
    parser.add_argument("--llm-ids", default=None,
                        help="LLM 으로 부를 제보 번호(0부터, 쉼표 구분). 호출 예산을 지킬 때 쓴다")
    args = parser.parse_args(argv)

    reports = load_reports(args.reports)
    if not reports:
        print("평가할 제보가 없습니다:", args.reports)
        return 2

    rule_items = run_rule(reports)
    rule_summary = summarize(rule_items)

    llm_items = None
    llm_summary = None
    llm_note = None
    if args.rule_only:
        llm_note = "규칙만 평가했습니다(--rule-only)"
    elif args.llm_from:
        llm_items = reuse_llm(reports, args.llm_from)
        if llm_items is None:
            llm_note = "저장된 결과에 없는 제보가 있어 LLM 재채점을 건너뛰었습니다"
        else:
            llm_summary = summarize(llm_items)
            llm_note = "저장된 LLM 해석을 정답에 맞춰 다시 채점했습니다(새 호출 없음)"
    elif not llm.API_KEY:
        llm_note = "CMD_API_KEY 가 없어 LLM 평가를 건너뛰었습니다"
    else:
        ids = None
        if args.llm_ids:
            ids = set(int(x) for x in args.llm_ids.replace(" ", "").split(",") if x != "")
            llm_note = "LLM 은 지정한 %d건만 실호출했습니다(호출 예산). 규칙은 %d건 전체." % (
                len(ids), len(reports))
        llm_items = run_llm(reports, ids)
        llm_summary = summarize(llm_items)
        errors = [i for i in llm_items if i["error"]]
        if errors and all(i["engine"] == "rule" for i in llm_items):
            llm_note = "LLM 호출이 모두 실패해 규칙 결과로 대체됐습니다: %s" % errors[0]["error"]
        elif errors:
            llm_note = "%d건이 규칙으로 대체됐습니다: %s" % (len(errors), errors[0]["error"])

    payload = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "model": llm.TEXT_MODEL,
        "reports_path": os.path.relpath(args.reports, ROOT),
        "rule": rule_summary,
        "llm": llm_summary,
        "llm_note": llm_note,
        "llm_ids": args.llm_ids,
        "differences": [],
        "items": {
            "rule": [{"text": i["text"], "gold": i["gold"], "result": i["result"],
                      "score": i["score"]} for i in rule_items],
            "llm": ([{"text": i["text"], "gold": i["gold"], "result": i["result"],
                      "score": i["score"], "engine": i["engine"], "error": i["error"],
                      "latency_ms": i["latency_ms"]} for i in llm_items]
                    if llm_items else None),
        },
    }
    if llm_items:
        diff = []
        rule_by_text = dict((r["text"], r) for r in rule_items)
        for m in llm_items:
            r = rule_by_text.get(m["text"])
            if r is None:
                continue
            if r["score"]["exact"] != m["score"]["exact"]:
                diff.append({
                    "text": r["text"],
                    "rule": {"arms": r["result"].get("arms"), "exact": r["score"]["exact"]},
                    "llm": {"arms": m["result"].get("arms"), "exact": m["score"]["exact"],
                            "engine": m["engine"]},
                })
        payload["differences"] = diff

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")

    print("제보 %d건 평가" % len(reports))
    print("  규칙: arms %.2f / 모호 %.2f / 완전 %.2f" % (
        rule_summary["arms_accuracy"], rule_summary["ambiguous_accuracy"],
        rule_summary["exact_accuracy"]))
    if llm_summary:
        print("  LLM : arms %.2f / 모호 %.2f / 완전 %.2f" % (
            llm_summary["arms_accuracy"], llm_summary["ambiguous_accuracy"],
            llm_summary["exact_accuracy"]))
    if llm_note:
        print("  참고:", llm_note)
    wrong = [i for i in rule_items if not i["score"]["exact"]]
    if wrong:
        print("  규칙 오답:")
        for i in wrong:
            print("   -", i["text"], "→", i["result"].get("arms"), i["result"].get("ambiguous"),
                  "(정답", i["gold"]["gold_arms"], i["gold"]["gold_ambiguous"], ")")
    print("  결과 파일:", os.path.relpath(args.out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
