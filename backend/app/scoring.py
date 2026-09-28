"""Deterministic, explainable lead scoring (0-100).

score = fit (0-40) + intent (0-40) + recency (0-20)

Every component reports the exact inputs that produced it (lead fields, company
fields, activity IDs) so explanations can cite them.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import duckdb
import pandas as pd
from pydantic import BaseModel

from app.config import AS_OF, CLOSED_STAGES, ICP, INTENT_WEIGHTS, INTENT_WINDOW_DAYS

INTENT_HALF_LIFE_DAYS = 10.0
INTENT_MAX = 40.0
RECENCY_MAX = 20.0
SENIORITY_LABELS = {"c_level": "C-level", "vp": "VP", "director": "Director", "manager": "Manager", "individual": "IC"}


class Contribution(BaseModel):
    source: str  # "lead", "company" or "activity"
    ref: str  # row ID the value came from (lead_id, company_id, activity_id)
    field: str
    value: str
    points: float


class Component(BaseModel):
    points: float
    max_points: float
    summary: str
    contributions: list[Contribution]


class ScoreBreakdown(BaseModel):
    lead_id: str
    score: float
    fit: Component
    intent: Component
    recency: Component

    @property
    def citations(self) -> list[str]:
        refs: list[str] = []
        for comp in (self.fit, self.intent, self.recency):
            for c in comp.contributions:
                if c.ref not in refs:
                    refs.append(c.ref)
        return refs


def _days_between(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 86400


def fit_component(lead: dict[str, Any], company: dict[str, Any] | None) -> Component:
    seniority = lead.get("seniority") or "unknown"
    sen_pts = float(ICP["seniority_points"].get(seniority, 0))
    contribs = [Contribution(source="lead", ref=lead["lead_id"], field="seniority", value=seniority, points=sen_pts)]
    size_pts = ind_pts = 0.0
    if company:
        employees = int(company.get("employees") or 0)
        size_pts = float(next(p for floor, p in ICP["size_bands"] if employees >= floor))
        industry = company.get("industry") or "unknown"
        ind_pts = float(ICP["industry_points"].get(industry, ICP["industry_default"]))
        contribs += [
            Contribution(source="company", ref=company["company_id"], field="employees", value=str(employees), points=size_pts),
            Contribution(source="company", ref=company["company_id"], field="industry", value=industry, points=ind_pts),
        ]
    points = round(sen_pts + size_pts + ind_pts, 1)
    label = SENIORITY_LABELS.get(seniority, seniority)
    summary = (f"{label} at a {company['employees']}-person {company['industry']} company" if company
               else f"{label}, company unknown")
    return Component(points=points, max_points=40, summary=summary, contributions=contribs)


def intent_component(activities: Iterable[dict[str, Any]], as_of: datetime = AS_OF) -> Component:
    contribs: list[Contribution] = []
    for act in activities:
        age = _days_between(as_of, act["occurred_at"])
        if age < 0 or age > INTENT_WINDOW_DAYS:
            continue
        pts = INTENT_WEIGHTS.get(act["type"], 0.0) * 0.5 ** (age / INTENT_HALF_LIFE_DAYS)
        contribs.append(Contribution(source="activity", ref=act["activity_id"], field=act["type"],
                                     value="today" if age < 1 else f"{age:.0f}d ago", points=round(pts, 2)))
    contribs.sort(key=lambda c: (-c.points, c.ref))
    raw = sum(c.points for c in contribs)
    points = round(min(INTENT_MAX, raw), 1)
    if not contribs:
        summary = f"no activity in the last {INTENT_WINDOW_DAYS} days"
    else:
        counts: dict[str, int] = defaultdict(int)
        for c in contribs:
            counts[c.field] += 1
        top = sorted(counts.items(), key=lambda kv: (-INTENT_WEIGHTS.get(kv[0], 0), kv[0]))[:3]
        summary = ", ".join(f"{n} {t.replace('_', ' ')}" for t, n in top) + f" in last {INTENT_WINDOW_DAYS}d"
    return Component(points=points, max_points=INTENT_MAX, summary=summary, contributions=contribs)


def recency_points(days_since_contact: float | None, stage: str) -> tuple[float, str]:
    """Follow-up urgency: peaks when a follow-up is overdue, decays once the lead goes cold."""
    if stage in CLOSED_STAGES:
        return 0.0, f"closed ({stage}), no follow-up due"
    if days_since_contact is None:
        return 12.0, "never contacted, first touch due"
    d = days_since_contact
    if d <= 2:
        return 2.0, f"contacted {d:.0f}d ago, just touched"
    if d <= 7:
        return round(2 + (d - 2) * 2, 1), f"contacted {d:.0f}d ago, follow-up coming due"
    if d <= 30:
        return RECENCY_MAX, f"contacted {d:.0f}d ago, follow-up overdue"
    return round(RECENCY_MAX * 0.5 ** ((d - 30) / 30), 1), f"contacted {d:.0f}d ago, going cold"


def recency_component(lead: dict[str, Any], as_of: datetime = AS_OF) -> Component:
    contacted = lead.get("last_contacted_at")
    days = _days_between(as_of, contacted) if contacted is not None and not pd.isna(contacted) else None
    points, summary = recency_points(days, lead.get("stage") or "")
    value = contacted.isoformat(sep=" ", timespec="minutes") if days is not None else "never"
    return Component(
        points=points, max_points=RECENCY_MAX, summary=summary,
        contributions=[Contribution(source="lead", ref=lead["lead_id"], field="last_contacted_at", value=value, points=points)],
    )


def score_lead(lead: dict[str, Any], company: dict[str, Any] | None,
               activities: Iterable[dict[str, Any]], as_of: datetime = AS_OF) -> ScoreBreakdown:
    fit = fit_component(lead, company)
    intent = intent_component(activities, as_of)
    recency = recency_component(lead, as_of)
    return ScoreBreakdown(
        lead_id=lead["lead_id"],
        score=round(fit.points + intent.points + recency.points, 1),
        fit=fit, intent=intent, recency=recency,
    )


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame rows as dicts with NaT/NaN mapped to None and pandas timestamps to datetime."""
    out = []
    for rec in df.astype(object).where(df.notna(), None).to_dict("records"):
        out.append({k: (v.to_pydatetime() if isinstance(v, pd.Timestamp) else v) for k, v in rec.items()})
    return out


def score_one(cur: duckdb.DuckDBPyConnection, lead_id: str) -> ScoreBreakdown | None:
    lead_df = cur.execute("SELECT * FROM leads WHERE lead_id = ?", [lead_id]).df()
    if lead_df.empty:
        return None
    lead = _records(lead_df)[0]
    company_rows = _records(cur.execute("SELECT * FROM companies WHERE company_id = ?", [lead["company_id"]]).df())
    acts = _records(cur.execute("SELECT * FROM activities WHERE lead_id = ?", [lead_id]).df())
    return score_lead(lead, company_rows[0] if company_rows else None, acts)


def materialize_scores(conn: duckdb.DuckDBPyConnection) -> int:
    """Score every lead and store the result in ``lead_scores``."""
    leads = _records(conn.execute("SELECT * FROM leads").df())
    companies = {c["company_id"]: c for c in _records(conn.execute("SELECT * FROM companies").df())}
    acts_by_lead: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for act in _records(conn.execute("SELECT * FROM activities").df()):
        acts_by_lead[act["lead_id"]].append(act)

    rows = []
    for lead in leads:
        b = score_lead(lead, companies.get(lead["company_id"]), acts_by_lead.get(lead["lead_id"], []))
        rows.append((b.lead_id, b.score, b.fit.points, b.intent.points, b.recency.points))
    scores = pd.DataFrame(rows, columns=["lead_id", "score", "fit", "intent", "recency"])
    conn.execute("DELETE FROM lead_scores")
    conn.register("scores_df", scores)
    conn.execute("INSERT INTO lead_scores SELECT * FROM scores_df")
    conn.unregister("scores_df")
    return len(rows)
