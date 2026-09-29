"""Persistent cache for LLM-backed results, so repeat requests cost zero tokens.

Keys combine the normalized input, a fingerprint of the prompts/model that produced
the result, and the data version. Any change to CRM data (approved actions,
imports) bumps the data version, so a cached answer can never describe stale data.
"""

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

import duckdb

from app import db


def normalize_question(question: str) -> str:
    """Case, whitespace, quotes and trailing punctuation don't change the question."""
    text = unicodedata.normalize("NFKC", question).lower().strip().strip("\"'")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"[\s?.!]+$", "", text)


def fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def data_version(cur: duckdb.DuckDBPyConnection) -> int:
    row = cur.execute("SELECT value FROM meta WHERE key = 'data_version'").fetchone()
    return int(row[0]) if row else 1


def bump_data_version(cur: duckdb.DuckDBPyConnection) -> int:
    version = data_version(cur) + 1
    cur.execute("INSERT OR REPLACE INTO meta VALUES ('data_version', ?)", [str(version)])
    return version


def make_key(kind: str, text: str, prompt_fingerprint: str) -> str:
    with db.cursor() as cur:
        version = data_version(cur)
    return fingerprint(kind, prompt_fingerprint, f"v{version}", text)


def get(kind: str, key: str) -> dict[str, Any] | None:
    with db.write_cursor() as cur:
        row = cur.execute("SELECT payload FROM llm_cache WHERE kind = ? AND key = ?", [kind, key]).fetchone()
        if row is None:
            return None
        cur.execute("UPDATE llm_cache SET hits = hits + 1 WHERE kind = ? AND key = ?", [kind, key])
    return json.loads(row[0])


def put(kind: str, key: str, payload: dict[str, Any]) -> None:
    with db.write_cursor() as cur:
        cur.execute(
            "INSERT OR REPLACE INTO llm_cache (kind, key, payload, created_at, hits) VALUES (?, ?, ?, ?, 0)",
            [kind, key, json.dumps(payload, default=str), datetime.now(UTC).replace(tzinfo=None)],
        )
