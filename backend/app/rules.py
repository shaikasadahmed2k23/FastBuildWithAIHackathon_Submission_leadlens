"""Keyword slot-filling question -> SQL, used when no LLM is available.

Precision over coverage: if the question contains a content word the parser
doesn't understand, it returns ``None`` rather than answering a different
question.
"""

import re
from dataclasses import dataclass, field

from app.config import ALL_STAGES, AS_OF_SQL, ICP, OWNERS

LEAD_JOINS = "JOIN companies c ON c.company_id = l.company_id JOIN lead_scores s ON s.lead_id = l.lead_id"
LEAD_LIST_COLUMNS = "l.lead_id, l.first_name || ' ' || l.last_name AS name, c.name AS company, l.stage, l.owner, s.score"

COUNTRIES = {"germany": "DE", "german": "DE", "uk": "GB", "britain": "GB", "british": "GB", "england": "GB",
             "us": "US", "usa": "US", "america": "US", "american": "US", "india": "IN", "indian": "IN",
             "canada": "CA", "canadian": "CA", "australia": "AU", "australian": "AU", "france": "FR", "french": "FR"}
SENIORITY = {"c_level": "c_level", "executive": "c_level", "executives": "c_level", "vp": "vp", "vps": "vp",
             "director": "director", "directors": "director", "manager": "manager", "managers": "manager",
             "individual": "individual", "contributor": "individual"}
SOURCES = {"referral": "referral", "referrals": "referral", "website": "website", "linkedin": "linkedin",
           "event": "event", "events": "event", "outbound": "cold_outbound", "cold": "cold_outbound",
           "partner": "partner", "partners": "partner"}
ACTIVITIES = {"demo": "demo_request", "demos": "demo_request", "pricing": "pricing_page_visit",
              "meeting": "meeting", "meetings": "meeting", "replied": "email_reply", "reply": "email_reply",
              "replies": "email_reply", "call": "call", "calls": "call", "opened": "email_open",
              "opens": "email_open", "visited": "website_visit", "visit": "website_visit", "visits": "website_visit"}
ISSUES = {"stale": "stale", "duplicate": "duplicate", "duplicates": "duplicate", "dupes": "duplicate",
          "duplicated": "duplicate", "missing": "missing_field", "incomplete": "missing_field"}
GROUPS = {"owner": "l.owner", "owners": "l.owner", "rep": "l.owner", "industry": "c.industry",
          "stage": "l.stage", "source": "l.source", "country": "c.country", "seniority": "l.seniority"}
STOPWORDS = set("""
a an the of in at on by for to from with and or is are was were be been being have has had do does did
what which who whom how many much show me list give find get there their them that this these those all any
each per our my we i you it its as than more over above under below less greater fewer number count total
top best highest hottest leads lead prospects prospect people contacts value values based work working
please currently right now level levels across
""".split())
RECOGNIZED = set("""
open closed never contacted score scores average avg mean max maximum lowest sum pipeline deal
deals revenue companies company activities activity recorded requested request requests page site issues
issue data field fields email address phone title job employees days day last past recent recently
owned owns own belong belongs belonging came come industry industries stage stages type types new
""".split())


@dataclass
class Parsed:
    entity: str = "leads"  # leads | companies | activities | issues
    metric: str = "list"  # list | count | avg_score | max_score | sum_deal | avg_deal
    group: str | None = None
    limit: int = 200
    conds: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuleMatch:
    sql: str
    rule: str


def _parse(question: str) -> Parsed | None:
    q = question.lower().replace("c-level", "c_level").replace("e-commerce", "ecommerce")
    words = re.findall(r"[a-z][a-z_]*|\d+", q)
    p = Parsed()
    known: set[str] = set()

    for industry in ICP["industry_points"]:
        key = industry.lower().replace("-", "")
        if key in words:
            p.conds.append(f"c.industry = '{industry}'")
            known.add(key)
    for owner in OWNERS:
        first, last = owner.lower().split()
        if first in words:
            p.conds.append(f"l.owner = '{owner}'")
            known.update((first, last))
    never_contacted = "never" in words and "contacted" in words
    for stage in ALL_STAGES:
        if stage in words and not (stage == "contacted" and never_contacted):
            p.conds.append(f"l.stage = '{stage}'")
    if "open" in words:
        p.conds.append("l.stage NOT IN ('won', 'lost')")
    if never_contacted:
        p.conds.append("l.last_contacted_at IS NULL")
    for vocab, col in ((COUNTRIES, "c.country"), (SENIORITY, "l.seniority"), (SOURCES, "l.source")):
        for word, value in vocab.items():
            if word in words:
                p.conds.append(f"{col} = '{value}'")
                known.add(word)

    days_m = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days?\b", q)
    days = int(days_m.group(1)) if days_m else 30
    top_m = re.search(r"\b(?:top|best|first|highest|hottest)\s+(\d{1,3})\b", q) or re.search(r"\b(\d{1,3})\s+(?:best|top|hottest)\b", q)
    if top_m:
        p.limit = min(int(top_m.group(1)), 200)
    elif re.search(r"\b(top|best|hottest)\b", q):
        p.limit = 10

    for pat, expr in ((r"scores?\s+(?:above|over|greater than|more than)\s+(\d+(?:\.\d+)?)", "s.score >"),
                      (r"scores?\s+(?:below|under|less than)\s+(\d+(?:\.\d+)?)", "s.score <"),
                      (r"(?:more than|over|above)\s+(\d+)\s+employees", "c.employees >"),
                      (r"(?:fewer than|less than|under|below)\s+(\d+)\s+employees", "c.employees <"),
                      (r"deal value (?:over|above|greater than|more than)\s+(\d+)", "l.deal_value >")):
        m = re.search(pat, q)
        if m:
            p.conds.append(f"{expr} {m.group(1)}")

    issue = next((v for k, v in ISSUES.items() if k in words), None)
    if issue:
        fld = next((f for f in ("email", "phone", "title") if f in words), None) if issue == "missing_field" else None
        detail = f" AND i.details = 'Missing {fld}'" if fld else ""
        p.conds.append(f"EXISTS (SELECT 1 FROM data_issues i WHERE i.lead_id = l.lead_id AND i.issue_type = '{issue}'{detail})")

    activity = next((v for k, v in ACTIVITIES.items() if k in words), None)
    act_cond = f"a.occurred_at >= {AS_OF_SQL} - INTERVAL {days} DAY" + (f" AND a.type = '{activity}'" if activity else "")

    group_m = re.search(r"\b(?:by|per|each|across)\s+(?:company\s+)?(owner|owners|rep|industry|stage|source|country|seniority|type)\b", q)
    if group_m:
        p.group = group_m.group(1)

    if re.search(r"\b(average|avg|mean)\b", q):
        p.metric = "avg_deal" if "deal" in words else "avg_score"
    elif re.search(r"\b(highest|max|maximum)\s+(lead\s+)?score\b", q):
        p.metric = "max_score"
    elif re.search(r"\b(total|sum)\b.*\b(deal|pipeline)\b|\bpipeline\b", q):
        p.metric = "sum_deal"
    elif re.search(r"\bhow many\b|\bcount\b|\bnumber of\b", q) or p.group:
        p.metric = "count"

    about_leads = bool({"leads", "lead", "who"} & set(words))
    if "companies" in words and not about_leads and not issue and not activity:
        p.entity = "companies"
    elif "issues" in words and not about_leads:
        p.entity = "issues"
    elif activity or "activities" in words:
        if about_leads:
            p.conds.append(f"EXISTS (SELECT 1 FROM activities a WHERE a.lead_id = l.lead_id AND {act_cond})")
        else:
            p.entity = "activities"
            p.conds.append(act_cond)

    unknown = [w for w in words if not w.isdigit() and w not in known and w not in STOPWORDS
               and w not in RECOGNIZED and w not in ISSUES and w not in ACTIVITIES and w not in GROUPS
               and w not in ALL_STAGES]
    return None if unknown else p


def _where(conds: list[str]) -> str:
    return f" WHERE {' AND '.join(conds)}" if conds else ""


def match(question: str) -> RuleMatch | None:
    p = _parse(question)
    if p is None:
        return None
    rule = f"{p.entity}:{p.metric}" + (f":by_{p.group}" if p.group else "")

    if p.entity == "companies":
        if p.metric != "count" or p.group or any(not c.startswith("c.") for c in p.conds):
            return None
        return RuleMatch(f"SELECT count(*) AS company_count FROM companies c{_where(p.conds)}", rule)

    if p.entity == "issues":
        if p.metric != "count" or p.conds or p.group not in (None, "type"):
            return None
        if p.group == "type":
            return RuleMatch("SELECT issue_type, count(*) AS issue_count FROM data_issues GROUP BY 1 ORDER BY 2 DESC", rule)
        return RuleMatch("SELECT count(*) AS issue_count FROM data_issues", rule)

    if p.entity == "activities":
        if p.metric != "count":
            return None
        from_ = f"FROM activities a JOIN leads l ON l.lead_id = a.lead_id {LEAD_JOINS}{_where(p.conds)}"
        if p.group:
            col = "a.type" if p.group == "type" else GROUPS[p.group]
            return RuleMatch(f"SELECT {col} AS {p.group}, count(*) AS activity_count {from_} GROUP BY 1 ORDER BY 2 DESC", rule)
        return RuleMatch(f"SELECT count(*) AS activity_count {from_}", rule)

    from_ = f"FROM leads l {LEAD_JOINS}{_where(p.conds)}"
    aggregates = {
        "count": "count(*) AS lead_count",
        "avg_score": "round(avg(s.score), 1) AS avg_score",
        "max_score": "max(s.score) AS max_score",
        "sum_deal": "round(sum(l.deal_value), 0) AS total_deal_value",
        "avg_deal": "round(avg(l.deal_value), 0) AS avg_deal_value",
    }
    if p.group:
        if p.group not in GROUPS or p.metric == "list":
            return None
        name = p.group.removesuffix("s")
        return RuleMatch(f"SELECT {GROUPS[p.group]} AS {name}, {aggregates[p.metric]} {from_} GROUP BY 1 ORDER BY 2 DESC", rule)
    if p.metric in aggregates:
        return RuleMatch(f"SELECT {aggregates[p.metric]} {from_}", rule)
    return RuleMatch(f"SELECT {LEAD_LIST_COLUMNS} {from_} ORDER BY s.score DESC, l.lead_id LIMIT {p.limit}", rule)
