"""제보 해석 정확도 평가 — 규칙(rule_parse) vs LLM(실호출).

    CMD_API_KEY="$(omp token commandcode)" python3 tests/eval_reports.py
    python3 tests/eval_reports.py --no-llm        # 규칙 기준선만

reports_eval.json 의 12개 제보를 해석해
  · 칸 완전 일치(ambiguous=false 항목만)
  · 모호 판정 일치(전체)
  · 예산 일치(전체)
  · 평균 지연(ms)
을 계산해 tests/eval_result.json 에 저장한다. 키는 출력·파일에 쓰지 않는다.
LLM 호출은 제보 1건당 1회(총 12회)다.
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(os.path.dirname(HERE), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import llm  # noqa: E402
import plan  # noqa: E402

DATA_PATH = os.path.join(HERE, "reports_eval.json")
OUT_PATH = os.path.join(HERE, "eval_result.json")


def load_items():
    with open(DATA_PATH, encoding="utf-8") as f:
        items = json.load(f)
    for item in items:
        exp = item["expect"]
        exp["cells"] = plan.cells_of(exp["cells"])
    return items


def flags(result, expect):
    return {
        "cells_ok": sorted(result.get("cells") or []) == sorted(expect["cells"]),
        "ambiguous_ok": bool(result.get("ambiguous")) == bool(expect["ambiguous"]),
        "budget_ok": result.get("budget") == expect["budget"],
    }


def summarize(rows, field):
    """rows: [{"expect": {...}, "flags": {field: {...}}, field: {"latency_ms": ...}}]"""
    cell_scope = [r for r in rows if not r["expect"]["ambiguous"]]
    cells_ok = sum(1 for r in cell_scope if r["flags"][field]["cells_ok"])
    amb_ok = sum(1 for r in rows if r["flags"][field]["ambiguous_ok"])
    budget_ok = sum(1 for r in rows if r["flags"][field]["budget_ok"])
    latencies = [r[field]["latency_ms"] for r in rows if r.get(field)]
    return {
        "items": len(rows),
        "cells_ok": cells_ok,
        "cells_total": len(cell_scope),
        "cells_accuracy": round(cells_ok / len(cell_scope), 3) if cell_scope else 0.0,
        "ambiguous_ok": amb_ok,
        "ambiguous_accuracy": round(amb_ok / len(rows), 3) if rows else 0.0,
        "budget_ok": budget_ok,
        "budget_accuracy": round(budget_ok / len(rows), 3) if rows else 0.0,
        "mean_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
    }


def evaluate_rule(items):
    rows = []
    for item in items:
        started = time.time()
        result = llm.rule_parse(item["text"])
        latency = round((time.time() - started) * 1000.0, 2)
        rows.append({
            "text": item["text"],
            "expect": item["expect"],
            "rule": {"cells": result["cells"], "ambiguous": result["ambiguous"],
                     "budget": result["budget"], "latency_ms": latency},
            "flags": {"rule": flags(result, item["expect"])},
        })
    return rows


def evaluate_llm(items, rows, timeout):
    """rows 에 llm 결과를 채운다. 실패한 호출은 engine=rule 로 남고 실패 수를 센다."""
    failures = 0
    for item, row in zip(items, rows):
        out = llm.interpret(item["text"], use_llm=True, timeout=timeout)
        result = out["result"]
        row["llm"] = {"cells": result["cells"], "ambiguous": result["ambiguous"],
                      "budget": result["budget"], "engine": out["engine"],
                      "latency_ms": out["latency_ms"], "error": out["error"]}
        row["flags"]["llm"] = flags(result, item["expect"]) if out["engine"] == "llm" else \
            {"cells_ok": False, "ambiguous_ok": False, "budget_ok": False}
        if out["engine"] != "llm":
            failures += 1
            row["flags"]["llm_failed"] = True
        print("  [%02d] llm=%-4s %5.0fms cells=%s amb=%s bud=%s%s" % (
            items.index(item) + 1, out["engine"], out["latency_ms"],
            result["cells"], result["ambiguous"], result["budget"],
            "" if out["engine"] == "llm" else "  (실패: %s)" % out["error"]))
    return failures


def print_summary(label, summary):
    print("%-5s 칸 %d/%d (%.1f%%) · 모호 %d/%d (%.1f%%) · 예산 %d/%d (%.1f%%) · 평균 %.0fms" % (
        label,
        summary["cells_ok"], summary["cells_total"], summary["cells_accuracy"] * 100,
        summary["ambiguous_ok"], summary["items"], summary["ambiguous_accuracy"] * 100,
        summary["budget_ok"], summary["items"], summary["budget_accuracy"] * 100,
        summary["mean_latency_ms"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description="제보 해석 정확도 평가(규칙 vs LLM)")
    parser.add_argument("--no-llm", action="store_true", help="LLM 실호출 없이 규칙만 평가")
    parser.add_argument("--timeout", type=float, default=llm.TIMEOUT_S, help="호출 제한 시간(초)")
    args = parser.parse_args(argv)

    items = load_items()
    rows = evaluate_rule(items)
    rule_summary = summarize(rows, "rule")

    llm_summary = None
    llm_info = {"available": False, "model": llm.TEXT_MODEL, "reasoning": llm.TEXT_REASONING}
    if args.no_llm:
        llm_info["note"] = "--no-llm 으로 실행해 실호출을 건너뛰었습니다"
    elif not llm.API_KEY:
        llm_info["note"] = "CMD_API_KEY 가 없어 실호출을 건너뛰었습니다"
    else:
        print("LLM 실호출 시작: %s (reasoning=%s, %d건)" % (
            llm.TEXT_MODEL, llm.TEXT_REASONING or "없음", len(items)))
        failures = evaluate_llm(items, rows, args.timeout)
        llm_summary = summarize(rows, "llm")
        llm_info.update({"available": True, "failures": failures})

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "items": len(items),
        "cell_scope_note": "칸 완전 일치는 ambiguous=false 항목만 집계(모호한 제보는 모호 판정으로 따로 봄)",
        "llm": llm_info,
        "rule": rule_summary,
        "llm_scores": llm_summary,
        "details": rows,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("─" * 64)
    print_summary("규칙", rule_summary)
    if llm_summary:
        print_summary("LLM", llm_summary)
    print("저장:", OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
