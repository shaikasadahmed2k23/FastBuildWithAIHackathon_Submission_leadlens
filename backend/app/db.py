"""DuckDB connection management and schema."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any

import duckdb

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    company_id  VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    domain      VARCHAR,
    industry    VARCHAR,
    employees   INTEGER,
    country     VARCHAR,
    created_at  TIMESTAMP
);
CREATE TABLE IF NOT EXISTS leads (
    lead_id            VARCHAR PRIMARY KEY,
    company_id         VARCHAR,
    first_name         VARCHAR,
    last_name          VARCHAR,
    email              VARCHAR,
    phone              VARCHAR,
    title              VARCHAR,
    seniority          VARCHAR,
    source             VARCHAR,
    stage              VARCHAR,
    deal_value         DOUBLE,
    owner              VARCHAR,
    created_at         TIMESTAMP,
    last_contacted_at  TIMESTAMP,
    updated_at         TIMESTAMP
);
CREATE TABLE IF NOT EXISTS activities (
    activity_id  VARCHAR PRIMARY KEY,
    lead_id      VARCHAR NOT NULL,
    type         VARCHAR NOT NULL,
    occurred_at  TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS data_issues (
    issue_id         VARCHAR PRIMARY KEY,
    lead_id          VARCHAR NOT NULL,
    issue_type       VARCHAR NOT NULL,
    details          VARCHAR,
    related_lead_id  VARCHAR
);
CREATE TABLE IF NOT EXISTS lead_scores (
    lead_id    VARCHAR PRIMARY KEY,
    score      DOUBLE NOT NULL,
    fit        DOUBLE NOT NULL,
    intent     DOUBLE NOT NULL,
    recency    DOUBLE NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    action_id     VARCHAR PRIMARY KEY,
    type          VARCHAR NOT NULL,
    lead_ids      VARCHAR[] NOT NULL,
    payload_json  VARCHAR NOT NULL,
    status        VARCHAR NOT NULL,
    created_at    TIMESTAMP NOT NULL,
    decided_at    TIMESTAMP,
    decided_by    VARCHAR,
    note          VARCHAR
);
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY,
    action_id  VARCHAR NOT NULL,
    event      VARCHAR NOT NULL,
    "at"       TIMESTAMP NOT NULL,
    actor      VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key    VARCHAR PRIMARY KEY,
    value  VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_cache (
    kind        VARCHAR NOT NULL,
    key         VARCHAR NOT NULL,
    payload     VARCHAR NOT NULL,
    created_at  TIMESTAMP NOT NULL,
    hits        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS idx_activities_lead ON activities(lead_id);
CREATE INDEX IF NOT EXISTS idx_issues_lead ON data_issues(lead_id);
"""

# Tables the text-to-SQL path is allowed to read.
QUERYABLE_TABLES = ("companies", "leads", "activities", "data_issues", "lead_scores")

_conn: duckdb.DuckDBPyConnection | None = None
_conn_path: Path | None = None
_write_lock = Lock()


def connect(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Return the process-wide connection, opening it on first use."""
    global _conn, _conn_path
    target = path or settings.db_path
    if _conn is None or _conn_path != target:
        if _conn is not None:
            _conn.close()
        target.parent.mkdir(parents=True, exist_ok=True)
        _conn = duckdb.connect(str(target))
        _conn.execute(SCHEMA)
        # Sandbox: generated SQL can never read files, URLs or attach databases.
        _conn.execute("SET enable_external_access = false")
        _conn_path = target
    return _conn


def close() -> None:
    global _conn, _conn_path
    if _conn is not None:
        _conn.close()
    _conn, _conn_path = None, None


@contextmanager
def cursor() -> Iterator[duckdb.DuckDBPyConnection]:
    """A per-call cursor on the shared connection (safe across threads)."""
    cur = connect().cursor()
    try:
        yield cur
    finally:
        cur.close()


@contextmanager
def write_cursor() -> Iterator[duckdb.DuckDBPyConnection]:
    """Serialize writes so read-modify-write sequences don't interleave."""
    with _write_lock, cursor() as cur:
        yield cur


def fetch_dicts(cur: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    rel = cur.execute(sql, params or [])
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row)) for row in rel.fetchall()]
