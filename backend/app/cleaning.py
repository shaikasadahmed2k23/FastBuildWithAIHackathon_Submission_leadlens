"""Data-quality detection: duplicates, stale records, missing fields.

Results are written to ``data_issues``. Detection is pure Python/SQL; nothing here
depends on an LLM.
"""

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from itertools import combinations

import duckdb
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import OSA

from app.config import AS_OF, OPEN_STAGES, STALE_DAYS

EMAIL_LOCAL_THRESHOLD = 85.0
REQUIRED_FIELDS = ("email", "phone", "title")
GMAIL_DOMAINS = ("gmail.com", "googlemail.com")
# Legal-form words that don't distinguish companies ("Acme Labs Inc" == "Acme Labs Ltd").
COMPANY_SUFFIXES = {
    "inc", "incorporated", "ltd", "limited", "llc", "llp", "lp", "plc", "corp", "corporation", "co", "company",
    "gmbh", "ag", "sa", "sas", "sarl", "srl", "spa", "bv", "nv", "pvt", "private", "pty", "oy", "ab", "kk",
}
# Common English nicknames -> formal name. Deliberately one-directional and exact: "dan" maps to "daniel",
# so Dan and Daniel match but Dan and Danielle do not.
NICKNAMES = {
    "bob": "robert", "bobby": "robert", "rob": "robert", "robbie": "robert", "bert": "robert",
    "bill": "william", "billy": "william", "will": "william", "willy": "william", "liam": "william",
    "liz": "elizabeth", "lizzie": "elizabeth", "beth": "elizabeth", "betty": "elizabeth", "libby": "elizabeth",
    "eliza": "elizabeth", "mike": "michael", "mikey": "michael", "mick": "michael", "kate": "katherine",
    "katie": "katherine", "kathy": "katherine", "kat": "katherine", "cathy": "catherine", "jim": "james",
    "jimmy": "james", "jamie": "james", "tom": "thomas", "tommy": "thomas", "dave": "david", "davey": "david",
    "jen": "jennifer", "jenny": "jennifer", "jenn": "jennifer", "chris": "christopher", "topher": "christopher",
    "alex": "alexander", "xander": "alexander", "sam": "samuel", "sammy": "samuel", "dan": "daniel",
    "danny": "daniel", "matt": "matthew", "matty": "matthew", "nick": "nicholas", "nicky": "nicholas",
    "tony": "anthony", "joe": "joseph", "joey": "joseph", "steve": "steven", "stevie": "steven",
    "peggy": "margaret", "maggie": "margaret", "meg": "margaret", "marge": "margaret", "dick": "richard",
    "rick": "richard", "ricky": "richard", "rich": "richard", "ed": "edward", "eddie": "edward", "ted": "edward",
    "andy": "andrew", "drew": "andrew", "greg": "gregory", "jeff": "jeffrey", "jon": "jonathan",
    "johnny": "john", "jack": "john", "ken": "kenneth", "kenny": "kenneth", "larry": "lawrence",
    "len": "leonard", "pat": "patrick", "patty": "patricia", "trish": "patricia", "pete": "peter",
    "phil": "philip", "ron": "ronald", "ronnie": "ronald", "russ": "russell", "sue": "susan", "suzy": "susan",
    "tim": "timothy", "timmy": "timothy", "vicky": "victoria", "vince": "vincent", "abby": "abigail",
    "barb": "barbara", "becky": "rebecca", "ben": "benjamin", "benny": "benjamin", "charlie": "charles",
    "chuck": "charles", "debbie": "deborah", "deb": "deborah", "don": "donald", "donnie": "donald",
    "doug": "douglas", "fred": "frederick", "freddie": "frederick", "gabe": "gabriel", "hank": "henry",
    "harry": "henry", "jake": "jacob", "josh": "joshua", "kim": "kimberly", "max": "maximilian",
    "mandy": "amanda", "manny": "manuel", "nate": "nathan", "pam": "pamela", "ray": "raymond",
    "sandy": "sandra", "tina": "christina", "val": "valerie", "zach": "zachary", "zack": "zachary",
    "pepe": "jose", "paco": "francisco", "nacho": "ignacio", "lupe": "guadalupe", "cesc": "francesc",
}


def fold(text: object) -> str:
    """Lowercase, strip accents and collapse whitespace; non-strings become ''."""
    if not isinstance(text, str):
        return ""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(ascii_text.lower().split())


def canonical_first(name: str) -> str:
    return NICKNAMES.get(name, name)


def normalize_email(email: object) -> str | None:
    """Lowercase, trim, and apply Gmail's dot/plus-insensitivity."""
    if not isinstance(email, str) or not email.strip():
        return None
    local, _, domain = email.strip().lower().partition("@")
    if domain in GMAIL_DOMAINS:
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def email_local_key(email: str) -> str:
    """Local part with its first token nickname-canonicalized: bob.smith -> robert.smith."""
    tokens = re.split(r"[._-]+", fold(email.split("@")[0]))
    return ".".join([canonical_first(tokens[0]), *tokens[1:]]) if tokens else ""


def normalize_company(name: object) -> str:
    """Company blocking key: accents, punctuation and legal-form suffixes removed."""
    # Drop periods first so dotted legal forms stay one token: "S.A." -> "sa", "B.V." -> "bv".
    tokens = re.sub(r"[^a-z0-9 ]", " ", fold(name).replace(".", "")).split()
    while tokens and tokens[-1] in COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_phone(phone: object) -> str | None:
    """Last 10 digits, so '+1 (415) 555-0134' == '415.555.0134'. Too-short numbers are ignored."""
    digits = re.sub(r"\D", "", phone) if isinstance(phone, str) else ""
    return digits[-10:] if len(digits) >= 7 else None


def _typo_close(a: str, b: str) -> bool:
    """One keystroke apart: a single insertion, deletion, substitution or adjacent swap (Gary/Gayr).

    Two short names (both < 4 letters) must match exactly: one edit turns "Ann" into "Dan".
    A dropped letter may leave a short name ("John" -> "Jon"), so only the longer one needs 4+.
    """
    return max(len(a), len(b)) >= 4 and OSA.distance(a, b) <= 1


def first_names_match(a: str, b: str) -> bool:
    return bool(a and b) and (a == b or canonical_first(a) == canonical_first(b) or _typo_close(a, b))


def last_names_match(a: str, b: str) -> bool:
    return bool(a and b) and (a == b or _typo_close(a, b))


def same_person_name(first_a: str, last_a: str, first_b: str, last_b: str) -> str | None:
    """Why two names refer to the same person, or None. Handles nicknames, typos and swapped fields."""
    if first_names_match(first_a, first_b) and last_names_match(last_a, last_b):
        return "same name" if (first_a, last_a) == (first_b, last_b) else "matching name"
    if first_names_match(first_a, last_b) and last_names_match(last_a, first_b):
        return "swapped first/last name"
    return None


@dataclass(frozen=True)
class DuplicatePair:
    lead_id: str  # the newer record
    related_lead_id: str  # the record it duplicates
    reason: str


@dataclass(frozen=True)
class _Person:
    lead_id: str
    first: str
    last: str
    email: str | None
    phone: str | None


def find_duplicates(leads: pd.DataFrame) -> list[DuplicatePair]:
    """Match leads by normalized email; then, within each company, by name plus corroborating evidence.

    Optional columns ``company_name`` (for suffix-insensitive company blocking) and ``phone`` are used
    when present. A matching name alone is not enough when both records have dissimilar emails:
    it must be backed by a similar email, the same phone number, or a missing email on one side.
    """
    has_company_name = "company_name" in leads.columns
    has_phone = "phone" in leads.columns
    ordered = leads.sort_values(["created_at", "lead_id"])
    rank = {lead_id: i for i, lead_id in enumerate(ordered["lead_id"])}
    by_email: dict[str, list[str]] = defaultdict(list)
    blocks: dict[str, list[_Person]] = defaultdict(list)
    for row in ordered.itertuples(index=False):
        email = normalize_email(row.email)
        if email:
            by_email[email].append(row.lead_id)
        company_key = normalize_company(row.company_name) if has_company_name else ""
        blocks[company_key or f"id:{row.company_id}"].append(_Person(
            row.lead_id, fold(row.first_name), fold(row.last_name), email,
            normalize_phone(row.phone) if has_phone else None,
        ))

    pairs: dict[frozenset[str], DuplicatePair] = {}

    def add(a: str, b: str, reason: str) -> None:
        key = frozenset((a, b))
        if key not in pairs:
            newer, older = (a, b) if rank[a] > rank[b] else (b, a)
            pairs[key] = DuplicatePair(newer, older, reason)

    for email, ids in by_email.items():
        for a, b in combinations(ids, 2):
            add(a, b, f"same email ({email})")

    for people in blocks.values():
        for pa, pb in combinations(people, 2):
            name_reason = same_person_name(pa.first, pa.last, pb.first, pb.last)
            if name_reason is None:
                continue
            if pa.email and pb.email:
                email_score = fuzz.ratio(email_local_key(pa.email), email_local_key(pb.email))
                if email_score >= EMAIL_LOCAL_THRESHOLD:
                    add(pa.lead_id, pb.lead_id, f"{name_reason} and similar email ({email_score:.0f}) at same company")
                    continue
            if pa.phone and pa.phone == pb.phone:
                add(pa.lead_id, pb.lead_id, f"{name_reason} and same phone at same company")
            elif not (pa.email and pb.email):
                add(pa.lead_id, pb.lead_id, f"{name_reason} at same company, email missing on one record")

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
        """SELECT l.lead_id, l.company_id, c.name AS company_name, l.first_name, l.last_name, l.email, l.phone,
                  l.created_at
           FROM leads l LEFT JOIN companies c ON c.company_id = l.company_id"""
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
