"""Persistent cache for LLM-backed results, so repeat requests cost zero tokens.

Keys combine the normalized input with a fingerprint of the prompts/model that
produced the result. Each entry also records a content hash of every table its
answer read. An entry is served only while those tables are unchanged, so an
approved stage change invalidates lead questions but not questions that only read
``companies`` or ``activities``. Hashes are checked on read (about 3 ms per table),
so no write path can forget to invalidate. Because they hash content, the entries
exported from a fresh seed-42 database stay valid after any reset to that seed.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from app import db

TableHashes = dict[str, str]


def normalize_question(question: str) -> str:
    """Case, whitespace, quotes and trailing punctuation don't change the question."""
    text = unicodedata.normalize("NFKC", question).lower().strip().strip("\"'")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"[\s?.!]+$", "", text)


def fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def make_key(kind: str, text: str, prompt_fingerprint: str) -> str:
    return fingerprint(kind, prompt_fingerprint, text)


def table_hashes(cur: duckdb.DuckDBPyConnection, tables: Iterable[str] = db.QUERYABLE_TABLES) -> TableHashes:
    """Content hash per table. Only queryable tables are hashed; others can't affect answers."""
    names = [t for t in tables if t in db.QUERYABLE_TABLES]
    return {t: str(cur.execute(f"SELECT bit_xor(hash({t})) FROM {t}").fetchone()[0]) for t in names}


def snapshot() -> TableHashes:
    """Hashes of all queryable tables, taken *before* computing an answer.

    If data changes while the LLM is working, the entry is stored against the old
    hashes and simply misses next time, instead of pinning a stale answer.
    """
    with db.cursor() as cur:
        return table_hashes(cur)


def get(kind: str, key: str) -> dict[str, Any] | None:
    with db.write_cursor() as cur:
        row = cur.execute("SELECT payload, deps FROM llm_cache WHERE kind = ? AND key = ?", [kind, key]).fetchone()
        if row is None:
            return None
        deps: TableHashes = json.loads(row[1])
        if table_hashes(cur, deps) != deps:  # a table this answer read has changed
            cur.execute("DELETE FROM llm_cache WHERE kind = ? AND key = ?", [kind, key])
            return None
        cur.execute("UPDATE llm_cache SET hits = hits + 1 WHERE kind = ? AND key = ?", [kind, key])
    return json.loads(row[0])


def put(kind: str, key: str, payload: dict[str, Any], snap: TableHashes, tables: Iterable[str]) -> None:
    deps = {t: snap[t] for t in tables if t in snap}
    with db.write_cursor() as cur:
        _insert(cur, kind, key, json.dumps(payload, default=str), json.dumps(deps))


def _insert(cur: duckdb.DuckDBPyConnection, kind: str, key: str, payload: str, deps: str) -> None:
    cur.execute(
        "INSERT OR REPLACE INTO llm_cache (kind, key, payload, deps, created_at, hits) VALUES (?, ?, ?, ?, ?, 0)",
        [kind, key, payload, deps, datetime.now(UTC).replace(tzinfo=None)],
    )


def export_entries(path: Path) -> int:
    """Write every currently-valid cache entry to a JSON file (the demo cache seed)."""
    with db.cursor() as cur:
        rows = cur.execute("SELECT kind, key, payload, deps FROM llm_cache ORDER BY kind, key").fetchall()
        current = table_hashes(cur)
    entries = [{"kind": k, "key": key, "payload": json.loads(p), "deps": json.loads(d)}
               for k, key, p, d in rows if all(current.get(t) == h for t, h in json.loads(d).items())]
    path.write_text(json.dumps(entries, indent=1) + "\n", encoding="utf-8", newline="\n")
    return len(entries)


def load_entries(path: Path) -> int:
    """Load a cache seed. Entries whose tables don't match the current data are skipped."""
    if not path.exists():
        return 0
    entries = json.loads(path.read_text(encoding="utf-8"))
    loaded = 0
    with db.write_cursor() as cur:
        current = table_hashes(cur)
        for e in entries:
            if all(current.get(t) == h for t, h in e["deps"].items()):
                _insert(cur, e["kind"], e["key"], json.dumps(e["payload"]), json.dumps(e["deps"]))
                loaded += 1
    return loaded
