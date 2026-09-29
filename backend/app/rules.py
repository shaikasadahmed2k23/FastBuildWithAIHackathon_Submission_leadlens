"""Strict keyword parser: question -> SQL, used only when the LLM is unavailable.

Safety policy (general, not per-question): answer only if every meaningful token is
consumed by a known slot (filter, metric, grouping, ranking, entity). Otherwise
decline. A confident wrong answer is worse than no answer, and the citation checker
cannot catch one: every number it states really is in the rows it fetched.

Specifically, the parser declines on:
- any negation (never/not/no/without/...), except the single supported filter
  "never (been) contacted", which is consumed as one unit;
- ranking by anything other than score, or ranking groups ("top 4 industries");
- grouping by an unsupported dimension;
- a filter it parsed but couldn't apply (e.g. a day window with no activity);
- any leftover content word.
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
             "individual contributor": "individual", "individual": "individual"}
SOURCES = {"referral": "referral", "referrals": "referral", "website": "website", "linkedin": "linkedin",
           "event": "event", "events": "event", "cold outbound": "cold_outbound", "outbound": "cold_outbound",
           "partner": "partner", "partners": "partner"}
# Phrase -> activity type. Longer phrases first so "pricing page visits" wins over "visits".
ACTIVITIES = {
    "requested a demo": "demo_request", "requested demos": "demo_request", "demo requests": "demo_request",
    "demo request": "demo_request", "demos": "demo_request", "demo": "demo_request",
    "visited the pricing page": "pricing_page_visit", "pricing page visits": "pricing_page_visit",
    "pricing page visit": "pricing_page_visit", "pricing": "pricing_page_visit",
    "had a meeting": "meeting", "meetings": "meeting", "meeting": "meeting",
    "replied": "email_reply", "replies": "email_reply", "reply": "email_reply",
    "calls": "call", "call": "call", "opened": "email_open", "opens": "email_open",
    "visited the site": "website_visit", "website visits": "website_visit",
}
ISSUES = {"stale": "stale", "duplicates": "duplicate", "duplicate": "duplicate", "dupes": "duplicate",
          "duplicated": "duplicate"}
MISSING_FIELDS = {"email address": "email", "email": "email", "phone number": "phone", "phone": "phone",
                  "job title": "title", "title": "title"}
ISSUE_VERBS = r"(?:flagged|marked|tagged|labeled|labelled|detected|identified|classified|considered|listed)(?: as)?"
GROUPS = {"owner": "l.owner", "owners": "l.owner", "rep": "l.owner", "industry": "c.industry",
          "stage": "l.stage", "source": "l.source", "country": "c.country", "seniority": "l.seniority",
          "type": None}
NEGATIONS = {"never", "not", "no", "without", "none", "nobody", "nothing", "except", "excluding", "exclude",
             "neither", "nor", "lacking"}
# Grammar that carries no meaning of its own. Anything else must be consumed by a slot.
FILLER = set("""
a an the of in at on for to from with and or is are was were be been being have has had do does did what
which who how show me list give find get there their them that this these those all any our my we i you it
its as please currently right now work working based leads lead prospects prospect people
contacts companies company
""".split())

OFFLINE_EXAMPLES = [
    "Top 10 open leads in Fintech",
    "How many stale leads does each owner have?",
    "Average lead score by industry",
    "Which leads requested a demo in the last 7 days?",
]


@dataclass
class Parsed:
    entity: str = "leads"  # leads | companies | activities | issues
    metric: str = "list"  # list | count | avg_score | max_score | sum_deal | avg_deal
    group: str | None = None
    limit: int = 200
    ranked: bool = False
    conds: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuleMatch:
    sql: str
    rule: str


@dataclass(frozen=True)
class RuleDecline:
    reason: str


class _Tokens:
    """The question as tokens, tracking which ones a slot has consumed."""

    def __init__(self, question: str) -> None:
        q = question.lower().replace("’", "'").replace("c-level", "c_level").replace("e-commerce", "ecommerce")
        q = q.replace("-", " ")
        self.words = re.findall(r"[a-z][a-z_']*|\d+(?:\.\d+)?", q)
        self.text = " ".join(self.words)
        self._starts = []
        pos = 0
        for w in self.words:
            self._starts.append(pos)
            pos += len(w) + 1
        self.used = [False] * len(self.words)

    def take(self, pattern: str) -> list[re.Match[str]]:
        """Consume every match of ``pattern`` (on word boundaries) that doesn't overlap consumed tokens."""
        found = []
        for m in re.finditer(rf"\b(?:{pattern})\b", self.text):
            idx = [i for i, s in enumerate(self._starts) if m.start() <= s < m.end()]
            if idx and not any(self.used[i] for i in idx):
                for i in idx:
                    self.used[i] = True
                found.append(m)
        return found

    def take_word(self, words: dict[str, str] | set[str]) -> list[str]:
        """Consume whole-phrase keys, longest first; return matched keys."""
        hits = []
        for key in sorted(words, key=len, reverse=True):
            if self.take(re.escape(key)):
                hits.append(key)
        return hits

    def leftover(self) -> list[str]:
        return [w for w, u in zip(self.words, self.used) if not u and w not in FILLER]


def _parse(question: str) -> Parsed | RuleDecline:
    t = _Tokens(question)
    p = Parsed()

    # Negation: only "never (been) contacted" is a supported negated filter.
    if t.take(r"never (?:been )?contacted"):
        p.conds.append("l.last_contacted_at IS NULL")
    negations = [w for w, used in zip(t.words, t.used) if not used and (w in NEGATIONS or w.endswith("n't"))]
    if negations:
        return RuleDecline(f"negation '{negations[0]}' is not supported offline")

    # Ranking (only by score).
    if m := (t.take(r"(?:top|best|highest|hottest|first) (\d{1,3})") or t.take(r"(\d{1,3}) (?:best|top|hottest)")):
        p.ranked, p.limit = True, min(int(m[0].group(1)), 200)
    elif t.take(r"top|best|hottest"):
        p.ranked, p.limit = True, 10
    t.take(r"by (?:lead )?score")

    # Numeric filters.
    for pattern, expr in ((r"scores? (?:above|over|greater than|more than) (\d+(?:\.\d+)?)", "s.score >"),
                          (r"scores? (?:below|under|less than) (\d+(?:\.\d+)?)", "s.score <"),
                          (r"(?:more than|over|above) (\d+) employees", "c.employees >"),
                          (r"(?:fewer than|less than|under|below) (\d+) employees", "c.employees <"),
                          (r"(?:a )?deal value (?:over|above|greater than|more than) (\d+)", "l.deal_value >")):
        for m in t.take(pattern):
            p.conds.append(f"{expr} {m.group(1)}")

    days_m = t.take(r"(?:in the |in )?(?:last|past) (\d{1,3}) days?")
    days = int(days_m[0].group(1)) if days_m else None

    # Metrics.
    if t.take(r"(?:average|avg|mean) (?:lead )?score"):
        p.metric = "avg_score"
    elif t.take(r"(?:average|avg|mean) deal value"):
        p.metric = "avg_deal"
    elif t.take(r"(?:highest|max|maximum) (?:lead )?score"):
        p.metric = "max_score"
    elif (re.search(r"\b(?:total|sum)\b", t.text) and re.search(r"\bdeal value\b|\bpipeline\b", t.text)) \
            or re.search(r"\bpipeline\b", t.text):
        t.take(r"total|sum(?: of)?|pipeline|deal value")
        p.metric = "sum_deal"
    elif t.take(r"how many|count(?: of)?|number of|lead count"):
        p.metric = "count"
    t.take(r"in total")

    # Filters by category.
    for industry in ICP["industry_points"]:
        if t.take(re.escape(industry.lower().replace("-", ""))):
            p.conds.append(f"c.industry = '{industry}'")
            t.take(r"industry")
    for owner in OWNERS:
        first, last = owner.lower().split()
        if t.take(rf"{first}(?: {last})?"):
            p.conds.append(f"l.owner = '{owner}'")
            t.take(r"owned by|owns?|belongs? to|belonging to")
    if t.take(r"open"):
        p.conds.append("l.stage NOT IN ('won', 'lost')")
    if t.take(r"closed"):
        p.conds.append("l.stage IN ('won', 'lost')")
    for stage in ALL_STAGES:
        pattern = r"new (?:leads?|stage)|in (?:the )?new stage" if stage == "new" else re.escape(stage)
        if t.take(pattern):
            p.conds.append(f"l.stage = '{stage}'")
            t.take(r"stage")
    for vocab, col in ((COUNTRIES, "c.country"), (SENIORITY, "l.seniority"), (SOURCES, "l.source")):
        for key in t.take_word(vocab):
            p.conds.append(f"{col} = '{vocab[key]}'")
    if any(c.startswith("l.source") for c in p.conds):
        t.take(r"came from|come from")
    if any(c.startswith("l.seniority") for c in p.conds):
        t.take(r"level")

    # Data issues.
    issue_found = False
    for m in t.take(r"missing (?:an? )?(email address|email|phone number|phone|job title|title)"):
        field_ = MISSING_FIELDS[m.group(1)]
        p.conds.append("EXISTS (SELECT 1 FROM data_issues i WHERE i.lead_id = l.lead_id "
                       f"AND i.issue_type = 'missing_field' AND i.details = 'Missing {field_}')")
        issue_found = True
    for key in t.take_word(ISSUES):
        p.conds.append(f"EXISTS (SELECT 1 FROM data_issues i WHERE i.lead_id = l.lead_id "
                       f"AND i.issue_type = '{ISSUES[key]}')")
        issue_found = True
    if issue_found:
        t.take(ISSUE_VERBS)
    if t.take(r"(?:data )?issues"):
        p.entity = "issues"

    # Activities.
    activity_keys = t.take_word(ACTIVITIES)
    activities_entity = bool(t.take(r"activities(?: were)?(?: recorded)?"))
    if days is not None and not (activity_keys or activities_entity):
        return RuleDecline("a date window is only supported for activities offline")

    # Grouping.
    if m := t.take(r"(?:by|per|for each|each|across) (?:company )?(owners?|rep|industry|stage|source|country|seniority|type)(?: levels?)?"):
        p.group = m[0].group(1)
        if p.metric == "list":
            p.metric = "count"

    leftover = t.leftover()
    if leftover:
        return RuleDecline(f"can't interpret '{' '.join(leftover)}' offline")
    if p.ranked and (p.group or p.metric != "list"):
        return RuleDecline("ranking is only supported for individual leads by score offline")

    act_cond = f"a.occurred_at >= {AS_OF_SQL} - INTERVAL {days or 30} DAY"
    if activity_keys:
        types = sorted({ACTIVITIES[k] for k in activity_keys})
        if len(types) > 1:
            return RuleDecline("more than one activity type in one question is not supported offline")
        act_cond += f" AND a.type = '{types[0]}'"
    about_companies = "companies" in t.words and not ({"leads", "lead", "who", "people"} & set(t.words))
    if activity_keys or activities_entity:
        if activities_entity or (p.metric == "count" and not ({"leads", "lead", "who"} & set(t.words))
                                 and "requests" in t.words):
            p.entity = "activities"
            p.conds.append(act_cond)
        else:
            p.conds.append(f"EXISTS (SELECT 1 FROM activities a WHERE a.lead_id = l.lead_id AND {act_cond})")
    elif about_companies and p.entity == "leads" and not issue_found:
        p.entity = "companies"
    return p


def _where(conds: list[str]) -> str:
    return f" WHERE {' AND '.join(conds)}" if conds else ""


def match(question: str) -> RuleMatch | RuleDecline:
    p = _parse(question)
    if isinstance(p, RuleDecline):
        return p
    rule = f"{p.entity}:{p.metric}" + (f":by_{p.group}" if p.group else "")

    if p.entity == "companies":
        if p.metric != "count" or p.group or any(not c.startswith("c.") for c in p.conds):
            return RuleDecline("only company counts by industry, country or size are supported offline")
        return RuleMatch(f"SELECT count(*) AS company_count FROM companies c{_where(p.conds)}", rule)

    if p.entity == "issues":
        if p.metric != "count" or p.conds or p.group not in (None, "type"):
            return RuleDecline("only issue counts (optionally by type) are supported offline")
        if p.group == "type":
            return RuleMatch("SELECT issue_type, count(*) AS issue_count FROM data_issues GROUP BY 1 ORDER BY 2 DESC", rule)
        return RuleMatch("SELECT count(*) AS issue_count FROM data_issues", rule)

    if p.entity == "activities":
        if p.metric != "count":
            return RuleDecline("only activity counts are supported offline")
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
        col = GROUPS.get(p.group)
        if col is None:
            return RuleDecline(f"grouping leads by '{p.group}' is not supported offline")
        name = p.group.removesuffix("s")
        return RuleMatch(f"SELECT {col} AS {name}, {aggregates[p.metric]} {from_} GROUP BY 1 ORDER BY 2 DESC", rule)
    if p.metric in aggregates:
        return RuleMatch(f"SELECT {aggregates[p.metric]} {from_}", rule)
    return RuleMatch(f"SELECT {LEAD_LIST_COLUMNS} {from_} ORDER BY s.score DESC, l.lead_id LIMIT {p.limit}", rule)
