"""CSV import for CRM exports (HubSpot, Salesforce and similar).

Two steps: ``preview`` proposes a header mapping the user confirms; ``run_import``
validates every row, rejects bad ones with reasons, then inserts the rest and re-runs
cleaning and scoring. Nothing is written until the user confirms the mapping.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel

from app import cache, db
from app.cleaning import detect_issues
from app.config import ALL_STAGES, AS_OF, ICP
from app.scoring import rescore

MAX_BYTES = 5_000_000
MAX_ROWS = 5_000

# Target field -> normalized header spellings, most specific first.
SYNONYMS: dict[str, list[str]] = {
    "first_name": ["firstname", "first", "givenname", "fname"],
    "last_name": ["lastname", "last", "surname", "familyname", "lname"],
    "email": ["email", "emailaddress", "workemail", "primaryemail", "businessemail"],
    "phone": ["phonenumber", "phone", "mobilephone", "mobile", "workphone", "businessphone"],
    "title": ["jobtitle", "title", "position", "role"],
    "company": ["companyname", "company", "accountname", "account", "organization", "organisation"],
    "domain": ["companydomainname", "website", "companywebsite", "domain", "websiteurl"],
    "industry": ["industry", "companyindustry"],
    "employees": ["numberofemployees", "employees", "companysize", "employeecount", "headcount"],
    "country": ["countryregion", "country", "companycountry", "mailingcountry"],
    "stage": ["leadstatus", "status", "lifecyclestage", "stage", "dealstage", "leadstage"],
    "source": ["originalsource", "leadsource", "source", "originalsourcetype"],
    "owner": ["contactowner", "leadowner", "owner", "hubspotowner", "ownername", "salesrep"],
    "deal_value": ["amount", "dealamount", "dealvalue", "opportunityamount", "expectedrevenue"],
    "created_at": ["createdate", "createddate", "datecreated", "created", "createdat"],
    "last_contacted_at": ["lastcontacted", "lastcontacteddate", "lastactivitydate", "lastactivity",
                          "lastcontact", "lastengagementdate"],
}
FIELD_LABELS = {
    "first_name": "First name", "last_name": "Last name", "email": "Email", "phone": "Phone", "title": "Job title",
    "company": "Company", "domain": "Company domain", "industry": "Industry", "employees": "Employees",
    "country": "Country", "stage": "Stage", "source": "Source", "owner": "Owner", "deal_value": "Deal value",
    "created_at": "Created", "last_contacted_at": "Last contacted",
}
REQUIRED = ("company",)  # plus a name or an email, checked per row

STAGE_MAP = {
    **{s: s for s in ALL_STAGES},
    # HubSpot lead status
    "open": "new", "inprogress": "contacted", "attemptedtocontact": "contacted", "connected": "contacted",
    "opendeal": "proposal", "unqualified": "lost", "badtiming": "lost",
    # HubSpot lifecycle stage
    "subscriber": "new", "lead": "new", "marketingqualifiedlead": "contacted", "mql": "contacted",
    "salesqualifiedlead": "qualified", "sql": "qualified", "opportunity": "proposal", "customer": "won",
    "evangelist": "won", "other": "new",
    # Salesforce
    "opennotcontacted": "new", "workingcontacted": "contacted", "closedconverted": "won",
    "closednotconverted": "lost", "prospecting": "new", "closedwon": "won", "closedlost": "lost",
}
SOURCE_MAP = {
    "organicsearch": "website", "directtraffic": "website", "website": "website", "web": "website",
    "paidsearch": "website", "referral": "referral", "referrals": "referral", "employeereferral": "referral",
    "socialmedia": "linkedin", "organicsocial": "linkedin", "linkedin": "linkedin", "event": "event",
    "events": "event", "tradeshow": "event", "offlinesources": "event", "emailmarketing": "cold_outbound",
    "outbound": "cold_outbound", "coldcall": "cold_outbound", "coldoutbound": "cold_outbound",
    "partner": "partner", "partnerreferral": "partner",
}
COUNTRY_MAP = {
    "unitedstates": "US", "usa": "US", "us": "US", "unitedstatesofamerica": "US", "unitedkingdom": "GB",
    "uk": "GB", "gb": "GB", "greatbritain": "GB", "england": "GB", "germany": "DE", "deutschland": "DE",
    "de": "DE", "india": "IN", "in": "IN", "canada": "CA", "ca": "CA", "australia": "AU", "au": "AU",
    "france": "FR", "fr": "FR",
}
INDUSTRY_MAP = {
    **{re.sub(r"[^a-z]", "", i.lower()): i for i in ICP["industry_points"]},
    "computersoftware": "Software", "informationtechnologyandservices": "Software", "internet": "Software",
    "saas": "Software", "financialservices": "Fintech", "banking": "Fintech", "hospitalhealthcare": "Healthcare",
    "healthcare": "Healthcare", "medicaldevices": "Healthcare", "retail": "E-commerce", "ecommerce": "E-commerce",
    "logisticsandsupplychain": "Logistics", "transportation": "Logistics", "educationmanagement": "Education",
    "highereducation": "Education", "mediaproduction": "Media", "onlinemedia": "Media",
}
SENIORITY_RULES = [
    (r"\b(chief|ceo|cto|cfo|coo|cro|cmo|cio|founder|co-founder|president|owner)\b", "c_level"),
    (r"\b(vp|svp|evp|vice president)\b", "vp"),
    (r"\b(director|head of)\b", "director"),
    (r"\b(manager|lead|supervisor)\b", "manager"),
]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                "%m/%d/%Y", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p")


class ImportRejected(ValueError):
    """The file itself can't be imported (not CSV, too large, missing required mapping)."""


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def read_csv(content: bytes) -> pd.DataFrame:
    if len(content) > MAX_BYTES:
        raise ImportRejected(f"file is larger than {MAX_BYTES // 1_000_000} MB")
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False, encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise ImportRejected(f"not a readable CSV file: {exc}") from exc
    if df.empty or len(df.columns) < 2:
        raise ImportRejected("the CSV has no data rows or fewer than two columns")
    if len(df) > MAX_ROWS:
        raise ImportRejected(f"at most {MAX_ROWS} rows per import (file has {len(df)})")
    return df


def propose_mapping(headers: list[str]) -> dict[str, str | None]:
    by_norm = {norm(h): h for h in headers}
    used: set[str] = set()
    mapping: dict[str, str | None] = {}
    for target, spellings in SYNONYMS.items():
        match = next((by_norm[s] for s in spellings if s in by_norm and by_norm[s] not in used), None)
        mapping[target] = match
        if match:
            used.add(match)
    return mapping


# ---------------------------------------------------------------- value parsing

def parse_date(value: str) -> datetime | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(value)


def parse_number(value: str) -> float:
    cleaned = re.sub(r"[,$€£₹\s]", "", value)
    range_match = re.fullmatch(r"(\d+)-(\d+)", cleaned)
    if range_match:  # headcount bands like "51-200": use the midpoint
        low, high = map(int, range_match.groups())
        return (low + high) / 2
    return float(cleaned.rstrip("+"))


def seniority_from_title(title: str) -> str:
    lowered = title.lower()
    return next((level for pattern, level in SENIORITY_RULES if re.search(pattern, lowered)), "individual")


@dataclass
class RowOutcome:
    record: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def transform_row(raw: dict[str, str], mapping: dict[str, str | None]) -> RowOutcome:
    """Validate and normalize one CSV row. Rejects never write partial data."""
    out = RowOutcome()
    get = {t: (raw.get(h, "") if h else "").strip() for t, h in mapping.items()}
    rec: dict[str, Any] = {}

    rec["first_name"], rec["last_name"] = get["first_name"] or None, get["last_name"] or None
    email = get["email"]
    if email and not EMAIL_RE.match(email):
        out.reasons.append(f"invalid email '{email}'")
    rec["email"] = email or None
    if not email and not (rec["first_name"] or rec["last_name"]):
        out.reasons.append("no name and no email")
    if not get["company"]:
        out.reasons.append("no company")
    rec["company"] = get["company"]
    rec["domain"] = re.sub(r"^(https?://)?(www\.)?", "", get["domain"].lower()).strip("/") or None
    rec["phone"] = get["phone"] or None
    rec["title"] = get["title"] or None
    rec["seniority"] = seniority_from_title(get["title"])
    rec["industry"] = INDUSTRY_MAP.get(norm(get["industry"]), get["industry"] or None)
    rec["country"] = COUNTRY_MAP.get(norm(get["country"]), get["country"] or None)
    rec["owner"] = get["owner"] or "Unassigned"
    rec["source"] = SOURCE_MAP.get(norm(get["source"]), norm(get["source"]) or "import") or "import"

    stage_raw = get["stage"]
    rec["stage"] = STAGE_MAP.get(norm(stage_raw), "new")
    if stage_raw and norm(stage_raw) not in STAGE_MAP:
        out.warnings.append(f"unknown stage '{stage_raw}', imported as 'new'")

    for target, cast in (("employees", int), ("deal_value", float)):
        value = get[target]
        rec[target] = None
        if value:
            try:
                rec[target] = cast(parse_number(value))
            except ValueError:
                out.reasons.append(f"{FIELD_LABELS[target].lower()} '{value}' is not a number")

    for target in ("created_at", "last_contacted_at"):
        value = get[target]
        rec[target] = None
        if value:
            try:
                rec[target] = parse_date(value)
            except ValueError:
                out.reasons.append(f"{FIELD_LABELS[target].lower()} date '{value}' is not recognized")
                continue
            if rec[target] > AS_OF:
                out.reasons.append(f"{FIELD_LABELS[target].lower()} date '{value}' is after the data as-of date")
    if not get["created_at"]:
        rec["created_at"] = AS_OF
        out.warnings.append("no create date; using the import date")

    if not out.reasons:
        out.record = rec
    return out


# ---------------------------------------------------------------- preview / import

class Preview(BaseModel):
    filename: str
    rows: int
    headers: list[str]
    mapping: dict[str, str | None]
    labels: dict[str, str]
    required: list[str]
    unmapped_headers: list[str]
    sample: list[dict[str, Any]]
    will_reject: int
    rejections: list[dict[str, Any]]


class ImportResult(BaseModel):
    batch_id: str
    filename: str
    imported: int
    rejected: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    new_companies: int
    matched_companies: int
    lead_ids: list[str]
    issues: dict[str, int]


def _check_mapping(mapping: dict[str, str | None], headers: list[str]) -> dict[str, str | None]:
    unknown_targets = set(mapping) - set(SYNONYMS)
    if unknown_targets:
        raise ImportRejected(f"unknown fields: {', '.join(sorted(unknown_targets))}")
    missing_headers = sorted({h for h in mapping.values() if h and h not in headers})
    if missing_headers:
        raise ImportRejected(f"columns not in the file: {', '.join(missing_headers)}")
    full = {t: mapping.get(t) for t in SYNONYMS}
    if not full["company"]:
        raise ImportRejected("map a column to Company")
    if not (full["email"] or full["first_name"] or full["last_name"]):
        raise ImportRejected("map a column to Email or to a name field")
    return full


def _outcomes(df: pd.DataFrame, mapping: dict[str, str | None]) -> list[tuple[int, RowOutcome]]:
    # Row numbers match what a spreadsheet shows: the header is row 1.
    return [(i + 2, transform_row(row, mapping)) for i, row in enumerate(df.to_dict("records"))]


def preview(content: bytes, filename: str) -> Preview:
    df = read_csv(content)
    headers = [str(h) for h in df.columns]
    mapping = propose_mapping(headers)
    sample = []
    outcomes = _outcomes(df, mapping) if mapping["company"] else []
    for _, o in outcomes[:5]:
        if o.record:
            sample.append({k: (v.isoformat(sep=" ", timespec="minutes") if isinstance(v, datetime) else v)
                           for k, v in o.record.items()})
    rejections = [{"row": n, "reasons": o.reasons} for n, o in outcomes if o.reasons]
    return Preview(
        filename=filename, rows=len(df), headers=headers, mapping=mapping, labels=FIELD_LABELS,
        required=["company", "email or name"], unmapped_headers=[h for h in headers if h not in mapping.values()],
        sample=sample, will_reject=len(rejections), rejections=rejections[:50],
    )


def _next_id(cur: Any, table: str, column: str, prefix: str) -> int:
    start = len(prefix) + 2
    return cur.execute(f"SELECT coalesce(max(CAST(substr({column}, {start}) AS INTEGER)), 0) FROM {table}").fetchone()[0]


def run_import(content: bytes, filename: str, mapping: dict[str, str | None], actor: str) -> ImportResult:
    df = read_csv(content)
    mapping = _check_mapping(mapping, [str(h) for h in df.columns])
    outcomes = _outcomes(df, mapping)
    rejected = [{"row": n, "reasons": o.reasons} for n, o in outcomes if o.reasons]
    warnings = [{"row": n, "message": w} for n, o in outcomes for w in o.warnings if o.record]
    records = [o.record for _, o in outcomes if o.record]

    with db.write_cursor() as cur:
        batch_n = cur.execute("SELECT count(*) + 1 FROM audit_log WHERE action_id LIKE 'IMP-%'").fetchone()[0]
        batch_id = f"IMP-{batch_n:05d}"
        # Match companies by domain, then by case-insensitive name; create the rest.
        existing = cur.execute("SELECT company_id, lower(name), lower(domain) FROM companies").fetchall()
        by_domain = {d: cid for cid, _, d in existing if d}
        by_name = {n: cid for cid, n, _ in existing}
        next_co = _next_id(cur, "companies", "company_id", "CO")
        new_companies: list[dict[str, Any]] = []
        matched: set[str] = set()
        for rec in records:
            # A domain is the stronger identity: two "Moore LLC"s with different domains are different companies.
            cid = by_domain.get(rec["domain"]) if rec["domain"] else by_name.get(rec["company"].lower())
            if cid and not any(c["company_id"] == cid for c in new_companies):
                matched.add(cid)
            if not cid:
                next_co += 1
                cid = f"CO-{next_co:05d}"
                new_companies.append({"company_id": cid, "name": rec["company"], "domain": rec["domain"],
                                      "industry": rec["industry"], "employees": rec["employees"],
                                      "country": rec["country"], "created_at": AS_OF})
                by_name[rec["company"].lower()] = cid
                if rec["domain"]:
                    by_domain[rec["domain"]] = cid
            rec["company_id"] = cid

        next_ld = _next_id(cur, "leads", "lead_id", "LD")
        leads = []
        for offset, rec in enumerate(records, start=1):
            created, contacted = rec["created_at"], rec["last_contacted_at"]
            leads.append({
                "lead_id": f"LD-{next_ld + offset:05d}", "company_id": rec["company_id"],
                "first_name": rec["first_name"], "last_name": rec["last_name"], "email": rec["email"],
                "phone": rec["phone"], "title": rec["title"], "seniority": rec["seniority"], "source": rec["source"],
                "stage": rec["stage"], "deal_value": rec["deal_value"], "owner": rec["owner"],
                "created_at": created, "last_contacted_at": contacted,
                "updated_at": max(created, contacted) if contacted else created,
            })
        lead_ids = [lead["lead_id"] for lead in leads]

        cur.execute("BEGIN TRANSACTION")
        try:
            if new_companies:
                cur.register("import_companies", pd.DataFrame(new_companies))
                cur.execute("INSERT INTO companies SELECT * FROM import_companies")
            if leads:
                cols = ["lead_id", "company_id", "first_name", "last_name", "email", "phone", "title", "seniority",
                        "source", "stage", "deal_value", "owner", "created_at", "last_contacted_at", "updated_at"]
                cur.register("import_leads", pd.DataFrame(leads)[cols])
                cur.execute("INSERT INTO leads SELECT * FROM import_leads")
            next_audit = cur.execute("SELECT coalesce(max(id), 0) + 1 FROM audit_log").fetchone()[0]
            cur.execute('INSERT INTO audit_log (id, action_id, event, "at", actor) VALUES (?, ?, ?, ?, ?)',
                        [next_audit, batch_id, f"imported {len(leads)} leads from {filename} "
                                               f"({len(rejected)} rows rejected)",
                         datetime.now(UTC).replace(tzinfo=None, microsecond=0), actor])
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.unregister("import_companies")
            cur.unregister("import_leads")
        # Derived data: duplicates can span old and new leads, so cleaning runs over everything.
        detect_issues(cur)
        rescore(cur, lead_ids)
        cache.bump_data_version(cur)
        # Imported leads involved in each issue; for duplicates an imported lead may be either side of the pair.
        issues = dict(cur.execute(
            """SELECT issue_type, count(DISTINCT imported) FROM (
                   SELECT issue_type, lead_id AS imported FROM data_issues
                   UNION ALL
                   SELECT issue_type, related_lead_id FROM data_issues WHERE related_lead_id IS NOT NULL
               ) WHERE imported IN (SELECT unnest(?)) GROUP BY 1""",
            [lead_ids]).fetchall()) if lead_ids else {}

    return ImportResult(
        batch_id=batch_id, filename=filename, imported=len(leads), rejected=rejected, warnings=warnings[:200],
        new_companies=len(new_companies), matched_companies=len(matched), lead_ids=lead_ids,
        issues={k: int(issues.get(k, 0)) for k in ("duplicate", "stale", "missing_field")},
    )
