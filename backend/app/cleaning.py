"""Data-quality detection: duplicates, stale records, missing fields.

Results are written to ``data_issues``. Detection is pure Python/SQL; nothing here
depends on an LLM.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from itertools import combinations

import duckdb
import pandas as pd
from rapidfuzz import fuzz

from app.config import AS_OF, OPEN_STAGES, STALE_DAYS

NAME_THRESHOLD = 88.0
EMAIL_LOCAL_THRESHOLD = 85.0
REQUIRED_FIELDS = ("email", "phone", "title")
GMAIL_DOMAINS = ("gmail.com", "googlemail.com")


def normalize_email(email: object) -> str | None:
    """Lowercase, trim, and apply Gmail's dot/plus-insensitivity."""
    if not isinstance(email, str) or not email.strip():
        return None
    local, _, domain = email.strip().lower().partition("@")
    if domain in GMAIL_DOMAINS:
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def normalize_name(first: object, last: object) -> str:
    parts = [p for p in (first, last) if isinstance(p, str)]
    return " ".join(" ".join(parts).lower().split())


@dataclass(frozen=True)
class DuplicatePair:
    lead_id: str  # the newer record
    related_lead_id: str  # the record it duplicates
    reason: str


def find_duplicates(leads: pd.DataFrame) -> list[DuplicatePair]:
    """Match leads by normalized email, then fuzzy name+email within each company."""
    records = sorted(
        (
            (created, lead_id, company, normalize_name(first, last), normalize_email(email))
            for lead_id, company, first, last, email, created in leads[
                ["lead_id", "company_id", "first_name", "last_name", "email", "created_at"]
            ].itertuples(index=False)
        ),
        key=lambda r: (r[0], r[1]),
    )
    rank = {r[1]: i for i, r in enumerate(records)}
    by_email: dict[str, list[str]] = defaultdict(list)
    by_company: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
    for _, lead_id, company, name, email in records:
        if email:
            by_email[email].append(lead_id)
        by_company[company].append((lead_id, name, email))

    pairs: dict[frozenset[str], DuplicatePair] = {}

    def add(a: str, b: str, reason: str) -> None:
        key = frozenset((a, b))
        if key not in pairs:
            newer, older = (a, b) if rank[a] > rank[b] else (b, a)
            pairs[key] = DuplicatePair(newer, older, reason)

    for email, ids in by_email.items():
        for a, b in combinations(ids, 2):
            add(a, b, f"same email ({email})")

    for rows in by_company.values():
        for (id_a, name_a, email_a), (id_b, name_b, email_b) in combinations(rows, 2):
            name_score = fuzz.ratio(name_a, name_b)
            if name_score < NAME_THRESHOLD:
                continue
            if email_a and email_b:
                email_score = fuzz.ratio(email_a.split("@")[0], email_b.split("@")[0])
                if email_score < EMAIL_LOCAL_THRESHOLD:
                    continue
                reason = f"similar name ({name_score:.0f}) and email ({email_score:.0f}) at same company"
            elif name_score == 100:
                reason = "same name at same company"
            else:
                continue
            add(id_a, id_b, reason)

    return sorted(pairs.values(), key=lambda p: p.lead_id)


IssueRow = tuple[str, str, str, str | None]  # lead_id, issue_type, details, related_lead_id


def _scope(lead_ids: list[str] | None) -> tuple[str, list[object]]:
    return ("AND lead_id IN (SELECT unnest(?))", [lead_ids]) if lead_ids is not None else ("", [])


def _stale_rows(conn: duckdb.DuckDBPyConnection, lead_ids: list[str] | None = None) -> list[IssueRow]:
    scope, params = _scope(lead_ids)
    stage_list = ", ".join(f"'{s}'" for s in OPEN_STAGES)
    stale = conn.execute(
        f"""
        SELECT lead_id, stage, last_contacted_at, created_at FROM leads
        WHERE stage IN ({stage_list}) AND coalesce(last_contacted_at, created_at) < ? {scope}
        ORDER BY lead_id
        """,
        [AS_OF - timedelta(days=STALE_DAYS), *params],
    ).fetchall()
    rows: list[IssueRow] = []
    for lead_id, stage, contacted, created in stale:
        days = (AS_OF - (contacted or created)).days
        what = f"last contacted {days} days ago" if contacted else f"never contacted, created {days} days ago"
        rows.append((lead_id, "stale", f"Open lead in stage '{stage}', {what}", None))
    return rows


def _missing_rows(conn: duckdb.DuckDBPyConnection, lead_ids: list[str] | None = None) -> list[IssueRow]:
    scope, params = _scope(lead_ids)
    rows: list[IssueRow] = []
    for fld in REQUIRED_FIELDS:
        missing = conn.execute(
            f"SELECT lead_id FROM leads WHERE ({fld} IS NULL OR trim({fld}) = '') {scope} ORDER BY lead_id", params
        ).fetchall()
        rows.extend((lead_id, "missing_field", f"Missing {fld}", None) for (lead_id,) in missing)
    return rows


def _insert(conn: duckdb.DuckDBPyConnection, rows: list[IssueRow]) -> None:
    if not rows:
        return
    start = conn.execute(
        "SELECT coalesce(max(CAST(substr(issue_id, 5) AS INTEGER)), 0) FROM data_issues"
    ).fetchone()[0]
    issues = pd.DataFrame(rows, columns=["lead_id", "issue_type", "details", "related_lead_id"])
    issues.insert(0, "issue_id", [f"ISS-{i:05d}" for i in range(start + 1, start + len(issues) + 1)])
    conn.register("issues_df", issues)
    conn.execute("INSERT INTO data_issues SELECT * FROM issues_df")
    conn.unregister("issues_df")


def detect_issues(conn: duckdb.DuckDBPyConnection) -> int:
    """Recompute ``data_issues`` from scratch. Returns the number of issues."""
    leads = conn.execute(
        "SELECT lead_id, company_id, first_name, last_name, email, created_at FROM leads"
    ).df()
    rows: list[IssueRow] = [
        (p.lead_id, "duplicate", f"Likely duplicate of {p.related_lead_id}: {p.reason}", p.related_lead_id)
        for p in find_duplicates(leads)
    ]
    rows += _stale_rows(conn) + _missing_rows(conn)
    conn.execute("DELETE FROM data_issues")
    _insert(conn, rows)
    return len(rows)


def refresh_issues(conn: duckdb.DuckDBPyConnection, lead_ids: list[str]) -> None:
    """Cheap incremental update after edits to ``lead_ids``.

    Stale/missing issues are recomputed for those leads; duplicate issues that
    point at deleted leads are dropped. (Edits here never create new duplicates.)
    """
    conn.execute(
        "DELETE FROM data_issues WHERE issue_type IN ('stale', 'missing_field') AND lead_id IN (SELECT unnest(?))",
        [lead_ids],
    )
    conn.execute(
        """
        DELETE FROM data_issues WHERE lead_id NOT IN (SELECT lead_id FROM leads)
           OR (related_lead_id IS NOT NULL AND related_lead_id NOT IN (SELECT lead_id FROM leads))
        """
    )
    _insert(conn, _stale_rows(conn, lead_ids) + _missing_rows(conn, lead_ids))
