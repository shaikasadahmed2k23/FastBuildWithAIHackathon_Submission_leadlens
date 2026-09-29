"""Demo support: the example questions and a one-click reset to a clean, cached state."""

import time
from pathlib import Path

from pydantic import BaseModel

from app import cache, db
from app.config import settings
from app.seed import write_database

DEMO_QUESTIONS = [
    "Top 10 open leads in Fintech",
    "How many stale leads does each owner have?",
    "Which Healthcare leads had a meeting in the last 2 days?",
    "Average lead score by industry",
    "How many leads are missing a phone number?",
    "Total open pipeline deal value by owner",
    "Which leads requested a demo in the last 7 days?",
    "Top 5 C-level leads at Software companies",
    "How many leads are flagged as duplicates?",
]


class ResetResult(BaseModel):
    leads: int
    cached_answers_loaded: int
    cache_seed_found: bool
    seconds: float


def reset_demo_data() -> ResetResult:
    """Rebuild the seed-42 database (discarding approvals, imports and cached answers),
    then load the pre-computed answer cache so the demo questions cost no tokens.

    Seed entries carry content hashes of the tables they read; a fresh seed-42
    database has identical contents, so they are valid again immediately.
    """
    started = time.perf_counter()
    with db.exclusive():  # no write may interleave while the database file is replaced
        write_database(settings.db_path)
    seed = Path(settings.answer_cache_seed_path)
    loaded = cache.load_entries(seed)
    with db.cursor() as cur:
        leads = cur.execute("SELECT count(*) FROM leads").fetchone()[0]
    return ResetResult(leads=leads, cached_answers_loaded=loaded, cache_seed_found=seed.exists(),
                       seconds=round(time.perf_counter() - started, 1))
