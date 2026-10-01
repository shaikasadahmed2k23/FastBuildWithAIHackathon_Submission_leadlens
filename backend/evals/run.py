"""Run the golden set through /ask and score data cleaning against ground truth.

Run from ``backend/``:
    python -m evals.run                      # auto: live if an LLM key is set, else offline
    python -m evals.run --mode offline       # force the rule-based path
    python -m evals.run --mode live --runs 3 # repeat to measure run-to-run variance

Uses a fresh seeded database so results are reproducible, and writes
``evals/latest.json`` (served at /evals/latest) unless ``--out`` is given.
"""

import argparse
import json
import math
import statistics
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import ask, db, llm
from app.config import settings
from app.seed import GroundTruth, write_database
from evals.grading import extract, grade

EVALS_DIR = Path(__file__).parent
GOLDEN_PATH = EVALS_DIR / "golden.jsonl"
LATEST_PATH = EVALS_DIR / "latest.json"


def load_golden(path: Path = GOLDEN_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _prf(found: set[Any], truth: set[Any]) -> dict[str, float]:
    tp = len(found & truth)
    p = tp / len(found) if found else 0.0
    r = tp / len(truth) if truth else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
            "found": len(found), "expected": len(truth)}


def cleaning_metrics(truth: GroundTruth) -> dict[str, dict[str, float]]:
    with db.cursor() as cur:
        issues = cur.execute("SELECT issue_type, lead_id, related_lead_id, details FROM data_issues").fetchall()
    dups = {frozenset((lid, rel)) for t, lid, rel, _ in issues if t == "duplicate"}
    stale = {lid for t, lid, _, _ in issues if t == "stale"}
    missing = {(lid, d.removeprefix("Missing ")) for t, lid, _, d in issues if t == "missing_field"}
    return {
        "duplicate": _prf(dups, {frozenset((d["lead_id"], d["original_id"])) for d in truth.duplicates}),
        "stale": _prf(stale, set(truth.stale)),
        "missing_field": _prf(missing, {(m["lead_id"], m["field"]) for m in truth.missing}),
    }


def run_questions(golden: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for g in golden:
        tokens_before, limited_before = llm.stats["tokens"], llm.stats["rate_limited"]
        backoff_before = llm.stats["backoff_ms"]
        started = time.perf_counter()
        r = ask.ask(g["question"], use_cache=False)  # measure the model, not the cache
        latency_ms = round((time.perf_counter() - started) * 1000)
        got = extract(g["kind"], r.rows) if r.sql else None
        results.append({
            "id": g["id"], "category": g["category"], "kind": g["kind"], "question": g["question"],
            # A decline question passes only if nothing was queried: any answer is a confident wrong answer.
            "passed": r.sql is None if g["kind"] == "decline" else grade(g["kind"], g["expected"], got),
            "valid": r.valid, "source": r.source,
            "fallback": r.fallback, "sql_attempts": r.attempts, "answer_attempts": r.answer_attempts,
            "latency_ms": latency_ms,
            # Time spent sleeping on provider rate limits (a quota effect, not model speed).
            "backoff_ms": llm.stats["backoff_ms"] - backoff_before,
            "tokens": llm.stats["tokens"] - tokens_before,
            "rate_limited": llm.stats["rate_limited"] - limited_before,
            "sql": r.sql, "answer": r.answer, "citations": r.citations, "notes": r.notes,
            "expected": g["expected"] if g["kind"] != "id_set" else f"{len(g['expected'])} ids",
            "got": got if g["kind"] != "id_set" or got is None else f"{len(got)} ids",
        })
    return results


def _percentile(values: list[int], pct: float) -> int:
    """Nearest-rank percentile."""
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["passed"])
    n = len(results)
    answered = [r for r in results if r["sql"]]
    latencies = [r["latency_ms"] for r in results]
    unthrottled = [r["latency_ms"] - r.get("backoff_ms", 0) for r in results]
    retried = [r for r in results if r["sql_attempts"] > 1 or r["answer_attempts"] > 1]
    fell_back = [r for r in results if r["fallback"] != "none"]
    return {
        "total": n,
        "passed": sum(r["passed"] for r in results),
        "accuracy": round(sum(r["passed"] for r in results) / n, 4) if n else 0.0,
        "answered": len(answered),
        "declined": n - len(answered),
        "citation_valid_rate": round(sum(r["valid"] for r in answered) / len(answered), 4) if answered else 0.0,
        "hallucinated_citations": sum(1 for r in answered if not r["valid"]),
        "retry_rate": round(len(retried) / n, 4) if n else 0.0,
        "sql_retries": sum(r["sql_attempts"] - 1 for r in results if r["sql_attempts"] > 1),
        "answer_retries": sum(r["answer_attempts"] - 1 for r in results if r["answer_attempts"] > 1),
        "fallback_rate": round(len(fell_back) / n, 4) if n else 0.0,
        "fallbacks": {k: sum(1 for r in fell_back if r["fallback"] == k) for k in ("template", "rules")},
        "avg_latency_ms": round(sum(latencies) / n) if n else 0,
        "p50_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
        "max_latency_ms": max(latencies, default=0),
        "p50_latency_ex_backoff_ms": _percentile(unthrottled, 50),
        "p95_latency_ex_backoff_ms": _percentile(unthrottled, 95),
        "backoff_ms": sum(r.get("backoff_ms", 0) for r in results),
        "tokens": sum(r["tokens"] for r in results),
        "rate_limited": sum(r["rate_limited"] for r in results),
        "by_category": {c: {"passed": sum(v), "total": len(v)} for c, v in sorted(by_cat.items())},
        "by_source": {s: sum(1 for r in results if r["source"] == s) for s in ("llm", "rules", "none")},
    }


def variance(runs: list[list[dict[str, Any]]], summaries: list[dict[str, Any]]) -> dict[str, Any]:
    def spread(key: str) -> dict[str, float]:
        vals = [s[key] for s in summaries]
        return {"mean": round(statistics.mean(vals), 4), "stdev": round(statistics.pstdev(vals), 4),
                "min": min(vals), "max": max(vals)}

    pass_counts: dict[str, int] = defaultdict(int)
    for results in runs:
        for r in results:
            pass_counts[r["id"]] += r["passed"]
    return {
        "runs": len(runs),
        **{k: spread(k) for k in ("accuracy", "citation_valid_rate", "retry_rate", "fallback_rate",
                                  "p50_latency_ms", "p95_latency_ms", "p50_latency_ex_backoff_ms",
                                  "p95_latency_ex_backoff_ms")},
        "unstable_questions": sorted(q for q, c in pass_counts.items() if 0 < c < len(runs)),
        "always_failing": sorted(q for q, c in pass_counts.items() if c == 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["auto", "offline", "live"], default="auto")
    parser.add_argument("--runs", type=int, default=1, help="repeat the golden set N times")
    parser.add_argument("--set", choices=["golden", "heldout", "decline_check"], default="golden")
    parser.add_argument("--limit", type=int, default=None, help="only run the first N questions")
    parser.add_argument("--out", type=Path, default=LATEST_PATH)
    args = parser.parse_args()

    if args.mode == "offline":
        settings.groq_api_key = settings.gemini_api_key = ""
    elif args.mode == "live" and not llm.available():
        parser.error("--mode live needs GROQ_API_KEY or GEMINI_API_KEY (backend/.env)")
    mode = "live" if llm.available() else "offline"

    golden = load_golden(EVALS_DIR / f"{args.set}.jsonl")[: args.limit]
    runs: list[list[dict[str, Any]]] = []
    with tempfile.TemporaryDirectory() as tmp:
        original = settings.leadlens_db_path
        settings.leadlens_db_path = str(Path(tmp) / "eval.duckdb")
        try:
            truth = write_database(settings.db_path)
            cleaning = cleaning_metrics(truth)
            for i in range(args.runs):
                runs.append(run_questions(golden))
                s = summarize(runs[-1])
                print(f"run {i + 1}/{args.runs}: accuracy={s['passed']}/{s['total']}  "
                      f"citation_valid={s['citation_valid_rate']:.0%}  retry={s['retry_rate']:.0%}  "
                      f"fallback={s['fallback_rate']:.0%}  p50={s['p50_latency_ms']}ms  p95={s['p95_latency_ms']}ms  "
                      f"(ex-backoff p50={s['p50_latency_ex_backoff_ms']}ms p95={s['p95_latency_ex_backoff_ms']}ms)")
        finally:
            db.close()
            settings.leadlens_db_path = original

    summaries = [summarize(r) for r in runs]
    report: dict[str, Any] = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "full" if mode == "live" else "offline",
        "set": args.set,
        "model": (settings.groq_model if settings.groq_api_key else settings.gemini_model) if mode == "live" else None,
        "summary": summaries[-1],
        "cleaning": cleaning,
        "results": runs[-1],
    }
    if len(runs) > 1:
        report["run_summaries"] = summaries
        report["variance"] = variance(runs, summaries)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")

    for kind, m in cleaning.items():
        print(f"cleaning {kind:<14} P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f}")
    for r in runs[-1]:
        if not r["passed"]:
            print(f"  FAIL {r['id']} [{r['source']}/{r['fallback']}] {r['question']}  expected={r['expected']} got={r['got']}")
    if "variance" in report:
        print("variance:", json.dumps(report["variance"]))


if __name__ == "__main__":
    main()
