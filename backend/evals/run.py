"""Run the golden set through /ask and score data cleaning against ground truth.

Run: ``python -m evals.run`` (from ``backend/``). Uses a fresh seeded database so
results are reproducible, and writes ``evals/latest.json`` (served at /evals/latest).
"""

import argparse
import json
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
        started = time.perf_counter()
        r = ask.ask(g["question"])
        latency_ms = round((time.perf_counter() - started) * 1000)
        got = extract(g["kind"], r.rows) if r.sql else None
        results.append({
            "id": g["id"], "category": g["category"], "kind": g["kind"], "question": g["question"],
            "passed": grade(g["kind"], g["expected"], got), "valid": r.valid, "source": r.source,
            "latency_ms": latency_ms, "sql": r.sql, "answer": r.answer, "citations": r.citations,
            "expected": g["expected"] if g["kind"] != "id_set" else f"{len(g['expected'])} ids",
            "got": got if g["kind"] != "id_set" or got is None else f"{len(got)} ids",
        })
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["passed"])
    n = len(results)
    answered = [r for r in results if r["sql"]]
    return {
        "total": n,
        "passed": sum(r["passed"] for r in results),
        "accuracy": round(sum(r["passed"] for r in results) / n, 4) if n else 0.0,
        "answered": len(answered),
        "citation_valid_rate": round(sum(r["valid"] for r in answered) / len(answered), 4) if answered else 0.0,
        "hallucinated_citations": sum(1 for r in results if r["valid"] is False and r["sql"]),
        "avg_latency_ms": round(sum(r["latency_ms"] for r in results) / n) if n else 0,
        "by_category": {c: {"passed": sum(v), "total": len(v)} for c, v in sorted(by_cat.items())},
        "by_source": {s: sum(1 for r in results if r["source"] == s) for s in ("llm", "rules", "none")},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only run the first N questions")
    parser.add_argument("--out", type=Path, default=LATEST_PATH)
    args = parser.parse_args()

    golden = load_golden()[: args.limit]
    with tempfile.TemporaryDirectory() as tmp:
        original = settings.leadlens_db_path
        settings.leadlens_db_path = str(Path(tmp) / "eval.duckdb")
        try:
            truth = write_database(settings.db_path)
            cleaning = cleaning_metrics(truth)
            results = run_questions(golden)
        finally:
            db.close()
            settings.leadlens_db_path = original

    report = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "full" if llm.available() else "offline",
        "model": settings.groq_model if settings.groq_api_key else settings.gemini_model if settings.gemini_api_key else None,
        "summary": summarize(results),
        "cleaning": cleaning,
        "results": results,
    }
    args.out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8", newline="
")
    s = report["summary"]
    print(f"mode={report['mode']}  accuracy={s['passed']}/{s['total']} ({s['accuracy']:.0%})  "
          f"citation_valid={s['citation_valid_rate']:.0%}  avg_latency={s['avg_latency_ms']}ms")
    for kind, m in cleaning.items():
        print(f"cleaning {kind:<14} P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f}")
    for r in results:
        if not r["passed"]:
            print(f"  FAIL {r['id']} [{r['source']}] {r['question']}  expected={r['expected']} got={r['got']}")


if __name__ == "__main__":
    main()
