"""Build the expected answers by running each reference query on a fresh seeded database.

Run from ``backend/``:
    python -m evals.build_golden                 # golden.jsonl  (questions.py)
    python -m evals.build_golden --set heldout   # heldout.jsonl (heldout_questions.py)
    python -m evals.build_golden --set decline_check   # decline_check.jsonl
"""

import argparse
import json
import tempfile
from pathlib import Path

from app import db
from app.config import settings
from app.seed import write_database
from evals.grading import extract
from evals.decline_check_questions import DECLINE_CHECK
from evals.heldout_questions import HELDOUT
from evals.questions import QUESTIONS

EVALS_DIR = Path(__file__).parent
SETS = {
    "golden": (QUESTIONS, EVALS_DIR / "golden.jsonl", "Q"),
    "heldout": (HELDOUT, EVALS_DIR / "heldout.jsonl", "H"),
    "decline_check": (DECLINE_CHECK, EVALS_DIR / "decline_check.jsonl", "D"),
}


def build(name: str = "golden") -> list[dict[str, object]]:
    questions, _, prefix = SETS[name]
    entries = []
    with db.cursor() as cur:
        for n, (category, kind, question, sql) in enumerate(questions, start=1):
            if kind == "decline":
                expected = None
            else:
                expected = extract(kind, db.fetch_dicts(cur, sql))
                if expected in (None, [], {}):
                    raise ValueError(f"{prefix}{n} has an empty expected answer: {question}")
            entries.append({"id": f"{prefix}{n:02d}", "category": category, "kind": kind, "question": question,
                            "reference_sql": sql, "expected": expected})
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=sorted(SETS), default="golden")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        original = settings.leadlens_db_path
        settings.leadlens_db_path = str(Path(tmp) / "golden.duckdb")
        try:
            write_database(settings.db_path)
            entries = build(args.set)
        finally:
            db.close()
            settings.leadlens_db_path = original
    path = SETS[args.set][1]
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8", newline="\n")
    print(f"Wrote {len(entries)} {args.set} questions -> {path}")


if __name__ == "__main__":
    main()
