"""Build ``golden.jsonl`` by running each reference query on a fresh seeded database.

Run: ``python -m evals.build_golden`` (from ``backend/``).
"""

import json
import tempfile
from pathlib import Path

from app import db
from app.config import settings
from app.seed import write_database
from evals.grading import extract
from evals.questions import QUESTIONS

GOLDEN_PATH = Path(__file__).parent / "golden.jsonl"


def build() -> list[dict[str, object]]:
    entries = []
    with db.cursor() as cur:
        for n, (category, kind, question, sql) in enumerate(QUESTIONS, start=1):
            rows = db.fetch_dicts(cur, sql)
            expected = extract(kind, rows)
            if expected in (None, [], {}):
                raise ValueError(f"Q{n} has an empty expected answer: {question}")
            entries.append({"id": f"Q{n:02d}", "category": category, "kind": kind, "question": question,
                            "reference_sql": sql, "expected": expected})
    return entries


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        original = settings.leadlens_db_path
        settings.leadlens_db_path = str(Path(tmp) / "golden.duckdb")
        try:
            write_database(settings.db_path)
            entries = build()
        finally:
            db.close()
            settings.leadlens_db_path = original
    GOLDEN_PATH.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    print(f"Wrote {len(entries)} golden questions -> {GOLDEN_PATH}")


if __name__ == "__main__":
    main()
