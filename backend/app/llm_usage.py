"""Summarize the LLM call ledger.

Run from ``backend/``:  python -m app.llm_usage [--since 2026-09-29T11:30]   (UTC prefix)
"""

import argparse
from collections import Counter

from app import llm


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", help="ISO date/time prefix in UTC, e.g. 2026-09-29 or 2026-09-29T11:30")
    args = parser.parse_args()
    entries = llm.read_log(args.since)
    ok = [e for e in entries if e["ok"]]
    tokens = sum(e.get("total_tokens", 0) for e in ok)
    by_purpose: Counter[str] = Counter()
    for e in ok:
        by_purpose[e["purpose"] or "other"] += e.get("total_tokens", 0)
    errors = Counter(e["error"] for e in entries if not e["ok"])
    print(f"calls: {len(entries)} ({len(ok)} ok, {len(entries) - len(ok)} failed)   tokens: {tokens}")
    for purpose, n in by_purpose.most_common():
        calls = sum(1 for e in ok if (e["purpose"] or "other") == purpose)
        print(f"  {purpose:<12} {n:>8} tokens  {calls:>4} calls  {n // max(calls, 1):>5}/call")
    for error, n in errors.most_common(5):
        print(f"  error x{n}: {error}")


if __name__ == "__main__":
    main()
