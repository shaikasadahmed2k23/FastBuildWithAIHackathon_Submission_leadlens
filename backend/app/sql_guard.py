"""Validate and run untrusted (LLM-written) SQL as a bounded, read-only query."""

import re
import threading
from typing import Any

import duckdb

from app import db

MAX_ROWS = 200
TIMEOUT_S = 5.0
# Defense in depth: the connection already disables external access.
_BLOCKED_FUNCTIONS = re.compile(
    r"\b(read_\w+|glob|sniff_csv|parquet_\w+|query_table|query|getvariable|duckdb_\w+|pg_\w+)\s*\(",
    re.IGNORECASE,
)
_BLOCKED_CATALOGS = re.compile(r"\b(information_schema|pg_catalog|sqlite_master)\b", re.IGNORECASE)


class UnsafeSQL(ValueError):
    pass


def validate(sql: str, cur: duckdb.DuckDBPyConnection) -> str:
    """Return the cleaned statement or raise ``UnsafeSQL`` explaining why."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeSQL("empty query")
    try:
        statements = duckdb.extract_statements(cleaned)
    except duckdb.Error as exc:
        raise UnsafeSQL(f"syntax error: {exc}") from exc
    if len(statements) != 1:
        raise UnsafeSQL("exactly one statement is allowed")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise UnsafeSQL(f"only SELECT queries are allowed, got {statements[0].type.name}")
    blocked = _BLOCKED_FUNCTIONS.search(cleaned) or _BLOCKED_CATALOGS.search(cleaned)
    if blocked:
        raise UnsafeSQL(f"function or catalog not allowed: {blocked.group(1)}")
    try:
        tables = cur.get_table_names(cleaned)
    except duckdb.Error as exc:
        raise UnsafeSQL(f"invalid query: {str(exc).splitlines()[0]}") from exc
    disallowed = sorted(t for t in tables if t.split(".")[-1] not in db.QUERYABLE_TABLES)
    if disallowed:
        raise UnsafeSQL(f"table not allowed: {', '.join(disallowed)}")
    return cleaned


def run(sql: str) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Validate then execute with a row cap and timeout. Returns (sql, columns, rows)."""
    with db.cursor() as cur:
        cleaned = validate(sql, cur)
        timer = threading.Timer(TIMEOUT_S, cur.interrupt)
        timer.start()
        try:
            cur.execute("BEGIN TRANSACTION")
            rel = cur.execute(cleaned)
            columns = [d[0] for d in rel.description]
            rows = [dict(zip(columns, r)) for r in rel.fetchmany(MAX_ROWS)]
        except duckdb.InterruptException as exc:
            raise UnsafeSQL(f"query exceeded {TIMEOUT_S:.0f}s") from exc
        except duckdb.Error as exc:
            raise UnsafeSQL(f"query failed: {str(exc).splitlines()[0]}") from exc
        finally:
            timer.cancel()
            try:
                cur.execute("ROLLBACK")
            except duckdb.Error:
                pass
    return cleaned, columns, rows
