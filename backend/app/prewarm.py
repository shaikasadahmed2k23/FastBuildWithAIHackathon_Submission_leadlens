"""Answer the demo questions once so they are cached before a demo.

Run from ``backend/``:
    python -m app.prewarm --reset --export             # recommended: build the demo cache seed (API stopped)
    python -m app.prewarm --api http://localhost:8000  # warm a running API's cache

--reset rebuilds the seed-42 database first; --export writes the cache to
data/answer_cache_seed.json, which "Reset demo data" reloads. In-process runs need
the API stopped (DuckDB allows a single writer process).
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

from app import ask, cache, llm
from app.config import settings
from app.demo import DEMO_QUESTIONS, reset_demo_data


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
    parser.add_argument("--reset", action="store_true", help="rebuild the seed-42 database first (in-process only)")
    parser.add_argument("--export", action="store_true", help="write the cache seed file (in-process only)")
    args = parser.parse_args()
    if args.api and (args.reset or args.export):
        parser.error("--reset and --export run in-process; stop the API and omit --api")
    if not args.api and not llm.available():
        print("No LLM key configured: nothing to pre-warm (offline answers are free).")
        return 1
    if args.reset:
        print(f"reset: {reset_demo_data().model_dump()}")

    total, problems = 0, 0
    for q in DEMO_QUESTIONS:
        r = _via_api(args.api, q) if args.api else ask.ask(q).model_dump()
        total += int(r["tokens"])
        ok = r["valid"] and r["source"] == "llm" and r["fallback"] == "none"
        problems += not ok
        state = "cached" if r["cached"] else ("ok" if ok else f"NOT CACHED ({r['source']}/{r['fallback']})")
        print(f"{state:<28} {r['tokens']:>6} tokens  {q}")
    print(f"\n{len(DEMO_QUESTIONS)} questions, {total} tokens spent, {problems} not cacheable")
    if args.export:
        n = cache.export_entries(Path(settings.answer_cache_seed_path))
        print(f"exported {n} cache entries -> {settings.answer_cache_seed_path}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
