"""Validate and run untrusted (LLM-written) SQL as a bounded, read-only query."""

import json
import re
import threading
from dataclasses import dataclass
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
    _check_tables(cleaned, cur)
    return cleaned


def _walk(node: Any, visit: Any) -> None:
    if isinstance(node, dict):
        visit(node)
        for value in node.values():
            _walk(value, visit)
    elif isinstance(node, list):
        for value in node:
            _walk(value, visit)


@dataclass
class _Refs:
    tables: list[tuple[str, str]]  # (schema, table) for every base-table reference
    functions: list[str]  # table functions (read_csv, range, ...)
    ctes: list[str]


def _parse_refs(sql: str, cur: duckdb.DuckDBPyConnection) -> _Refs:
    """Table references from DuckDB's parse tree (no binding needed)."""
    tree = json.loads(cur.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])
    if tree.get("error"):
        raise UnsafeSQL(f"syntax error: {tree.get('error_message', 'could not parse')}")
    refs = _Refs([], [], [])

    def visit(node: dict[str, Any]) -> None:
        if node.get("type") == "BASE_TABLE":
            refs.tables.append((node.get("schema_name") or "", node.get("table_name", "")))
        elif node.get("type") == "TABLE_FUNCTION":
            refs.functions.append(str(node.get("function", {}).get("function_name", "?")))
        if isinstance(node.get("cte_map"), dict):
            refs.ctes.extend(entry["key"] for entry in node["cte_map"].get("map", []))

    _walk(tree, visit)
    return refs


def referenced_tables(sql: str) -> set[str]:
    """Real tables a (validated) query reads; CTE names are excluded."""
    with db.cursor() as cur:
        refs = _parse_refs(sql, cur)
    return {t for _, t in refs.tables if t not in refs.ctes}


def _check_tables(sql: str, cur: duckdb.DuckDBPyConnection) -> None:
    """Allow only queryable tables, found from the parse tree.

    ``get_table_names`` is not used: in DuckDB 1.5 it binds the query and wrongly
    fails on valid ``JOIN ... USING`` clauses. Parsing needs no binding; column
    errors surface at execution with a precise message for the model to fix.
    """
    refs = _parse_refs(sql, cur)
    if refs.functions:
        raise UnsafeSQL(f"table functions are not allowed: {', '.join(sorted(set(refs.functions)))}")
    protected = {r[0] for r in cur.execute("SELECT table_name FROM duckdb_tables()").fetchall()} - set(db.QUERYABLE_TABLES)
    shadowing = sorted(set(refs.ctes) & protected)
    if shadowing:
        raise UnsafeSQL(f"CTE name not allowed: {', '.join(shadowing)}")
    disallowed = sorted({f"{s}.{t}" if s else t for s, t in refs.tables
                         if t not in refs.ctes and (s not in ("", "main") or t not in db.QUERYABLE_TABLES)})
    if disallowed:
        raise UnsafeSQL(f"table not allowed: {', '.join(disallowed)}")


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
