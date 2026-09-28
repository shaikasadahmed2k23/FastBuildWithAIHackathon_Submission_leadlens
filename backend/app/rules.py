"""Keyword-based question -> SQL mapping used when no LLM is available.

Deliberately small: it covers the common questions a sales team asks so the app
stays useful in degraded mode. Anything it can't parse returns ``None``.
"""

import re
from dataclasses import dataclass

from app.config import ALL_STAGES, AS_OF_SQL, ICP, OWNERS

LEAD_COLUMNS = (
    "l.lead_id, l.first_name || ' ' || l.last_name AS name, c.name AS company, "
    "l.stage, l.owner, s.score"
)
JOINS = "JOIN companies c ON c.company_id = l.company_id JOIN lead_scores s ON s.lead_id = l.lead_id"
LEAD_FROM = f"leads l {JOINS}"
ISSUE_WORDS = {
    "stale": "stale", "duplicate": "duplicate", "duplicates": "duplicate", "dupes": "duplicate",
    "missing": "missing_field", "incomplete": "missing_field",
}
ACTIVITY_WORDS = {
    "demo": "demo_request", "pricing": "pricing_page_visit", "meeting": "meeting",
    "replied": "email_reply", "reply": "email_reply", "call": "call",
}
FIELDS = ("email", "phone", "title")


@dataclass(frozen=True)
class RuleMatch:
    sql: str
    rule: str


def _filters(q: str) -> list[str]:
    conds: list[str] = []
    for industry in ICP["industry_points"]:
        if industry.lower() in q:
            conds.append(f"c.industry = '{industry}'")
            break
    for owner in OWNERS:
        first = owner.split()[0].lower()
        if re.search(rf"\b{first}\b", q):
            conds.append(f"l.owner = '{owner}'")
            break
    for stage in ALL_STAGES:
        if re.search(rf"\b{stage}\b", q):
            conds.append(f"l.stage = '{stage}'")
            break
    if re.search(r"\bopen\b", q):
        conds.append("l.stage NOT IN ('won', 'lost')")
    return conds


def _where(conds: list[str]) -> str:
    return f" WHERE {' AND '.join(conds)}" if conds else ""


def match(question: str) -> RuleMatch | None:
    q = question.lower().strip()
    conds = _filters(q)
    limit_m = re.search(r"\b(?:top|best|first|highest)\s+(\d{1,3})\b", q) or re.search(r"\b(\d{1,3})\s+(?:best|top|hottest)\b", q)
    limit = min(int(limit_m.group(1)), 200) if limit_m else 10
    counting = bool(re.search(r"\bhow many\b|\bcount\b|\bnumber of\b", q))
    days_m = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days?\b", q)
    days = int(days_m.group(1)) if days_m else 30

    issue = next((v for k, v in ISSUE_WORDS.items() if re.search(rf"\b{k}\b", q)), None)
    if issue:
        field = next((f for f in FIELDS if f in q), None) if issue == "missing_field" else None
        issue_cond = [f"i.issue_type = '{issue}'"] + ([f"i.details = 'Missing {field}'"] if field else [])
        where = _where(issue_cond + conds)
        base = f"FROM data_issues i JOIN leads l ON l.lead_id = i.lead_id {JOINS}{where}"
        if counting:
            return RuleMatch(f"SELECT count(DISTINCT i.lead_id) AS lead_count {base}", f"count_{issue}")
        return RuleMatch(f"SELECT DISTINCT {LEAD_COLUMNS}, i.details {base} ORDER BY s.score DESC, l.lead_id LIMIT {limit}", f"list_{issue}")

    activity = next((v for k, v in ACTIVITY_WORDS.items() if re.search(rf"\b{k}\b", q)), None)
    if activity:
        act_cond = [f"a.type = '{activity}'", f"a.occurred_at >= {AS_OF_SQL} - INTERVAL {days} DAY"]
        base = f"FROM activities a JOIN leads l ON l.lead_id = a.lead_id {JOINS}{_where(act_cond + conds)}"
        if counting:
            return RuleMatch(f"SELECT count(DISTINCT a.lead_id) AS lead_count {base}", f"count_{activity}")
        return RuleMatch(
            f"SELECT {LEAD_COLUMNS}, max(a.occurred_at) AS last_{activity}, arg_max(a.activity_id, a.occurred_at) AS activity_id "
            f"{base} GROUP BY ALL ORDER BY s.score DESC, l.lead_id LIMIT {limit}", f"list_{activity}")

    if re.search(r"\b(pipeline|deal value|revenue)\b", q):
        return RuleMatch(f"SELECT round(sum(l.deal_value), 2) AS total_deal_value, count(*) AS lead_count FROM {LEAD_FROM}{_where(conds)}", "pipeline")

    by_m = re.search(r"\b(?:by|per|for each)\s+(owner|industry|stage|source|country)\b", q)
    if by_m:
        col = {"owner": "l.owner", "industry": "c.industry", "stage": "l.stage", "source": "l.source", "country": "c.country"}[by_m.group(1)]
        return RuleMatch(
            f"SELECT {col} AS {by_m.group(1)}, count(*) AS lead_count, round(avg(s.score), 1) AS avg_score "
            f"FROM {LEAD_FROM}{_where(conds)} GROUP BY 1 ORDER BY lead_count DESC", f"group_by_{by_m.group(1)}")

    if counting and re.search(r"\bleads?\b", q):
        return RuleMatch(f"SELECT count(*) AS lead_count FROM {LEAD_FROM}{_where(conds)}", "count_leads")

    if re.search(r"\b(leads?|prospects?|who)\b", q):
        return RuleMatch(f"SELECT {LEAD_COLUMNS} FROM {LEAD_FROM}{_where(conds)} ORDER BY s.score DESC, l.lead_id LIMIT {limit}", "top_leads")
    return None
