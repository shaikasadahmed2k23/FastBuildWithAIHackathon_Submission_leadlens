"""Answer the demo questions once so they are cached before a demo.

Run from ``backend/``:
    python -m app.prewarm                            # in-process (stop the API first: DuckDB is single-writer)
    python -m app.prewarm --api http://localhost:8000  # through a running API

Cached answers stay valid until the data changes (approved actions, imports).
"""

import argparse
import sys
import time

import httpx

from app import ask, llm
from app.demo import DEMO_QUESTIONS


def _via_api(base: str, question: str) -> dict[str, object]:
    for _ in range(3):
        resp = httpx.post(f"{base.rstrip('/')}/ask", json={"question": question}, timeout=120)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp.json()
        time.sleep(float(resp.headers.get("retry-after", "10")))  # respect our own rate limit
    raise RuntimeError(f"still rate limited: {question}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", help="base URL of a running API; default runs in-process")
    args = parser.parse_args()
    if not args.api and not llm.available():
        print("No LLM key configured: nothing to pre-warm (offline answers are free).")
        return 1

    total, problems = 0, 0
    for q in DEMO_QUESTIONS:
        r = _via_api(args.api, q) if args.api else ask.ask(q).model_dump()
        total += int(r["tokens"])
        ok = r["valid"] and r["source"] == "llm" and r["fallback"] == "none"
        problems += not ok
        state = "cached" if r["cached"] else ("ok" if ok else f"NOT CACHED ({r['source']}/{r['fallback']})")
        print(f"{state:<28} {r['tokens']:>6} tokens  {q}")
    print(f"\n{len(DEMO_QUESTIONS)} questions, {total} tokens spent, {problems} not cacheable")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
