"""Data-quality detection: duplicates, stale records, missing fields.

Results are written to ``data_issues``. Detection is pure Python/SQL; nothing here
depends on an LLM.
"""

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
    df = leads.assign(
        norm_email=leads["email"].map(normalize_email),
        norm_name=[normalize_name(f, l) for f, l in zip(leads["first_name"], leads["last_name"])],
    ).sort_values(["created_at", "lead_id"])
    rank = {lead_id: i for i, lead_id in enumerate(df["lead_id"])}
    pairs: dict[frozenset[str], DuplicatePair] = {}

    def add(a: str, b: str, reason: str) -> None:
        key = frozenset((a, b))
        if key in pairs:
            return
        newer, older = (a, b) if rank[a] > rank[b] else (b, a)
        pairs[key] = DuplicatePair(newer, older, reason)

    for _, group in df.dropna(subset=["norm_email"]).groupby("norm_email"):
        ids = list(group["lead_id"])
        for a, b in combinations(ids, 2):
            add(a, b, f"same email ({group['norm_email'].iloc[0]})")

    for _, group in df.groupby("company_id"):
        if len(group) < 2:
            continue
        rows = list(group[["lead_id", "norm_name", "norm_email"]].itertuples(index=False))
        for a, b in combinations(rows, 2):
            name_score = fuzz.ratio(a.norm_name, b.norm_name)
            if name_score < NAME_THRESHOLD:
                continue
            if a.norm_email and b.norm_email:
                email_score = fuzz.ratio(a.norm_email.split("@")[0], b.norm_email.split("@")[0])
                if email_score < EMAIL_LOCAL_THRESHOLD:
                    continue
                reason = f"similar name ({name_score:.0f}) and email ({email_score:.0f}) at same company"
            elif name_score == 100:
                reason = "same name at same company"
            else:
                continue
            add(a.lead_id, b.lead_id, reason)

    return sorted(pairs.values(), key=lambda p: p.lead_id)


def detect_issues(conn: duckdb.DuckDBPyConnection) -> int:
    """Recompute ``data_issues`` from scratch. Returns the number of issues."""
    leads = conn.execute(
        "SELECT lead_id, company_id, first_name, last_name, email, created_at FROM leads"
    ).df()
    rows: list[tuple[str, str, str, str | None]] = []

    for pair in find_duplicates(leads):
        rows.append((pair.lead_id, "duplicate", f"Likely duplicate of {pair.related_lead_id}: {pair.reason}",
                     pair.related_lead_id))

    cutoff = AS_OF - timedelta(days=STALE_DAYS)
    stage_list = ", ".join(f"'{s}'" for s in OPEN_STAGES)
    stale = conn.execute(
        f"""
        SELECT lead_id, stage, last_contacted_at, created_at FROM leads
        WHERE stage IN ({stage_list})
          AND coalesce(last_contacted_at, created_at) < ?
        ORDER BY lead_id
        """,
        [cutoff],
    ).fetchall()
    for lead_id, stage, contacted, created in stale:
        ref = contacted or created
        days = (AS_OF - ref).days
        what = f"last contacted {days} days ago" if contacted else f"never contacted, created {days} days ago"
        rows.append((lead_id, "stale", f"Open lead in stage '{stage}', {what}", None))

    for fld in REQUIRED_FIELDS:
        missing = conn.execute(
            f"SELECT lead_id FROM leads WHERE {fld} IS NULL OR trim({fld}) = '' ORDER BY lead_id"
        ).fetchall()
        rows.extend((lead_id, "missing_field", f"Missing {fld}", None) for (lead_id,) in missing)

    conn.execute("DELETE FROM data_issues")
    if rows:
        issues = pd.DataFrame(rows, columns=["lead_id", "issue_type", "details", "related_lead_id"])
        issues.insert(0, "issue_id", [f"ISS-{i:05d}" for i in range(1, len(issues) + 1)])
        conn.register("issues_df", issues)
        conn.execute("INSERT INTO data_issues SELECT * FROM issues_df")
        conn.unregister("issues_df")
    return len(rows)
