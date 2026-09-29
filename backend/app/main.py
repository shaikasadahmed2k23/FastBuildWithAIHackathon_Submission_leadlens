"""LeadLens HTTP API."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import actions, ask, db, explain, llm
from app.citations import jsonable
from app.config import AS_OF, BACKEND_DIR, settings
from app.demo import DEMO_QUESTIONS
from app.ratelimit import limiter
from app.scoring import ScoreBreakdown, score_one

log = logging.getLogger("leadlens")
EVALS_PATH = BACKEND_DIR / "evals" / "latest.json"

SORTABLE = {
    "score": "s.score", "fit": "s.fit", "intent": "s.intent", "recency": "s.recency",
    "name": "lower(l.last_name || ' ' || l.first_name)", "company": "lower(c.name)", "stage": "l.stage",
    "owner": "l.owner", "last_contacted_at": "l.last_contacted_at", "deal_value": "l.deal_value",
    "created_at": "l.created_at", "lead_id": "l.lead_id",
}
ROW_TABLES = {"LD": ("leads", "lead_id"), "CO": ("companies", "company_id"),
              "ACT": ("activities", "activity_id"), "ISS": ("data_issues", "issue_id")}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    with db.cursor() as cur:
        empty = cur.execute("SELECT count(*) FROM leads").fetchone()[0] == 0
    if empty:  # first boot (e.g. fresh deploy): build the dataset
        from app.seed import save_ground_truth, write_database
        log.info("Database empty; seeding synthetic data")
        save_ground_truth(write_database())
    yield
    db.close()


app = FastAPI(title="LeadLens API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"])


def _rows(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    with db.cursor() as cur:
        return [{k: jsonable(v) for k, v in r.items()} for r in db.fetch_dicts(cur, sql, params)]


# ---------------------------------------------------------------- health / overview

@app.get("/health")
def health() -> dict[str, Any]:
    with db.cursor() as cur:
        leads = cur.execute("SELECT count(*) FROM leads").fetchone()[0]
    # "failing" means a key is set but the most recent LLM call errored, so answers are
    # currently coming from the rule-based fallback.
    if not llm.available():
        status = "none"
    elif llm.last_call["ok"] is None:
        status = "untested"
    else:
        status = "ok" if llm.last_call["ok"] else "failing"
    return {"status": "ok", "leads": leads, "as_of": AS_OF.isoformat(), "llm": llm.configured_provider(),
            "mode": "full" if llm.available() else "offline", "llm_status": status,
            "llm_last_call": dict(llm.last_call)}


@app.get("/overview")
def overview() -> dict[str, Any]:
    totals = _rows("""
        SELECT (SELECT count(*) FROM leads) AS leads,
               (SELECT count(*) FROM leads WHERE stage NOT IN ('won', 'lost')) AS open_leads,
               (SELECT count(*) FROM companies) AS companies,
               (SELECT count(*) FROM activities) AS activities,
               (SELECT round(sum(deal_value), 0) FROM leads WHERE stage NOT IN ('won', 'lost')) AS open_pipeline,
               (SELECT round(avg(score), 1) FROM lead_scores) AS avg_score,
               (SELECT count(DISTINCT lead_id) FROM data_issues) AS leads_with_issues,
               (SELECT count(*) FROM actions WHERE status = 'pending') AS pending_actions
    """)[0]
    totals["clean_pct"] = round(100 * (1 - totals["leads_with_issues"] / totals["leads"]), 1) if totals["leads"] else 0
    return {
        "as_of": AS_OF.isoformat(),
        "totals": totals,
        "issues": _rows("SELECT issue_type, count(*) AS count FROM data_issues GROUP BY 1 ORDER BY 2 DESC"),
        "stages": _rows("""SELECT stage, count(*) AS count, round(avg(s.score), 1) AS avg_score
                           FROM leads l JOIN lead_scores s ON s.lead_id = l.lead_id GROUP BY 1
                           ORDER BY array_position(['new','contacted','qualified','proposal','negotiation','won','lost'], stage)"""),
        "score_histogram": _rows("""SELECT least(floor(score / 10), 9) * 10 AS bucket, count(*) AS count
                                    FROM lead_scores GROUP BY 1 ORDER BY 1"""),
        "top_leads": _rows("""
            SELECT l.lead_id, l.first_name || ' ' || l.last_name AS name, c.name AS company, l.stage, l.owner,
                   s.score, s.fit, s.intent, s.recency
            FROM leads l JOIN lead_scores s ON s.lead_id = l.lead_id JOIN companies c ON c.company_id = l.company_id
            WHERE l.stage NOT IN ('won', 'lost') ORDER BY s.score DESC, l.lead_id LIMIT 8"""),
    }


# ---------------------------------------------------------------- leads

LEAD_SELECT = """
    SELECT l.lead_id, l.first_name, l.last_name, l.email, l.phone, l.title, l.seniority, l.stage, l.owner,
           l.source, l.deal_value, l.created_at, l.last_contacted_at, l.updated_at,
           c.company_id, c.name AS company, c.industry, c.employees, c.country,
           s.score, s.fit, s.intent, s.recency,
           coalesce((SELECT list(DISTINCT i.issue_type ORDER BY i.issue_type) FROM data_issues i
                     WHERE i.lead_id = l.lead_id), []) AS issues
    FROM leads l
    LEFT JOIN companies c ON c.company_id = l.company_id
    LEFT JOIN lead_scores s ON s.lead_id = l.lead_id
"""


@app.get("/leads")
def list_leads(
    q: str | None = None,
    stage: Annotated[list[str] | None, Query()] = None,
    owner: str | None = None,
    industry: str | None = None,
    issue: Literal["any", "none", "duplicate", "stale", "missing_field"] | None = None,
    min_score: float | None = None,
    sort: str = "score",
    order: Literal["asc", "desc"] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    if sort not in SORTABLE:
        raise HTTPException(400, f"sort must be one of {sorted(SORTABLE)}")
    conds, params = [], []
    if q:
        conds.append("(l.lead_id ILIKE ? OR (l.first_name || ' ' || l.last_name) ILIKE ? OR l.email ILIKE ? OR c.name ILIKE ?)")
        params += [f"%{q.strip()}%"] * 4
    if stage:
        conds.append("l.stage IN (SELECT unnest(?))")
        params.append([s for part in stage for s in part.split(",") if s])
    if owner:
        conds.append("l.owner = ?")
        params.append(owner)
    if industry:
        conds.append("c.industry = ?")
        params.append(industry)
    if min_score is not None:
        conds.append("s.score >= ?")
        params.append(min_score)
    if issue == "any":
        conds.append("EXISTS (SELECT 1 FROM data_issues i WHERE i.lead_id = l.lead_id)")
    elif issue == "none":
        conds.append("NOT EXISTS (SELECT 1 FROM data_issues i WHERE i.lead_id = l.lead_id)")
    elif issue:
        conds.append("EXISTS (SELECT 1 FROM data_issues i WHERE i.lead_id = l.lead_id AND i.issue_type = ?)")
        params.append(issue)
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    base_from = "FROM leads l LEFT JOIN companies c ON c.company_id = l.company_id LEFT JOIN lead_scores s ON s.lead_id = l.lead_id"
    with db.cursor() as cur:
        total = cur.execute(f"SELECT count(*) {base_from} {where}", params).fetchone()[0]
    items = _rows(
        f"{LEAD_SELECT} {where} ORDER BY {SORTABLE[sort]} {order} NULLS LAST, l.lead_id LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _breakdown(lead_id: str) -> ScoreBreakdown:
    with db.cursor() as cur:
        b = score_one(cur, lead_id)
    if b is None:
        raise HTTPException(404, f"lead {lead_id} not found")
    return b


@app.get("/leads/{lead_id}")
def get_lead(lead_id: str) -> dict[str, Any]:
    leads = _rows(f"{LEAD_SELECT} WHERE l.lead_id = ?", [lead_id])
    if not leads:
        raise HTTPException(404, f"lead {lead_id} not found")
    b = _breakdown(lead_id)
    return {
        "lead": leads[0],
        "breakdown": b.model_dump(),
        "citations": b.citations,
        "activities": _rows("SELECT activity_id, type, occurred_at FROM activities WHERE lead_id = ? "
                            "ORDER BY occurred_at DESC LIMIT 50", [lead_id]),
        "issues": _rows("SELECT issue_id, issue_type, details, related_lead_id FROM data_issues WHERE lead_id = ? "
                        "OR related_lead_id = ? ORDER BY issue_id", [lead_id, lead_id]),
        "actions": [a.model_dump(mode="json") for a in actions.list_actions(lead_id=lead_id)],
    }


def llm_rate_limit(request: Request) -> None:
    """Per-client limit on endpoints that may spend LLM tokens."""
    client = request.client.host if request.client else "unknown"
    wait = limiter.check(client, settings.llm_rate_limit_per_min)
    if wait is not None:
        raise HTTPException(
            429,
            f"Rate limit: at most {settings.llm_rate_limit_per_min} requests per minute. Try again in {wait:.0f}s.",
            headers={"Retry-After": str(max(1, round(wait)))},
        )


@app.post("/leads/{lead_id}/explain", dependencies=[Depends(llm_rate_limit)])
def explain_lead(lead_id: str) -> explain.Explanation:
    return explain.explain(_breakdown(lead_id))


@app.get("/rows/{row_id}")
def get_row(row_id: str) -> dict[str, Any]:
    """Resolve any cited ID (LD-, CO-, ACT-, ISS-) to its source row."""
    prefix = row_id.split("-", 1)[0]
    if prefix not in ROW_TABLES:
        raise HTTPException(400, "unknown ID prefix")
    table, key = ROW_TABLES[prefix]
    rows = _rows(f"SELECT * FROM {table} WHERE {key} = ?", [row_id])
    if not rows:
        raise HTTPException(404, f"{row_id} not found")
    return {"id": row_id, "table": table, "row": rows[0]}


# ---------------------------------------------------------------- issues

@app.get("/issues")
def list_issues(
    type: Literal["duplicate", "stale", "missing_field"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    where, params = ("WHERE i.issue_type = ?", [type]) if type else ("", [])
    with db.cursor() as cur:
        total = cur.execute(f"SELECT count(*) FROM data_issues i {where}", params).fetchone()[0]
    items = _rows(
        f"""SELECT i.issue_id, i.issue_type, i.details, i.lead_id, i.related_lead_id,
                   l.first_name || ' ' || l.last_name AS name, c.name AS company, l.owner, l.stage, s.score
            FROM data_issues i JOIN leads l ON l.lead_id = i.lead_id
            LEFT JOIN companies c ON c.company_id = l.company_id LEFT JOIN lead_scores s ON s.lead_id = l.lead_id
            {where} ORDER BY i.issue_type, s.score DESC NULLS LAST, i.issue_id LIMIT ? OFFSET ?""",
        params + [page_size, (page - 1) * page_size],
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------- ask

class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/ask", dependencies=[Depends(llm_rate_limit)])
def ask_question(req: AskRequest) -> ask.AskResponse:
    return ask.ask(req.question)


@app.get("/ask/examples")
def ask_examples() -> list[str]:
    """Demo questions; the pre-warm script caches exactly these."""
    return DEMO_QUESTIONS


# ---------------------------------------------------------------- actions

class ActionCreate(BaseModel):
    type: actions.ActionType
    lead_ids: list[str] = Field(min_length=1, max_length=50)
    payload: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=500)
    actor: str = Field(default="reviewer", min_length=1, max_length=80)


class Decision(BaseModel):
    actor: str = Field(default="reviewer", min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)


@app.get("/actions")
def get_actions(status: actions.ActionStatus | None = None) -> list[actions.Action]:
    return actions.list_actions(status)


@app.get("/actions/{action_id}")
def get_action(action_id: str) -> actions.Action:
    try:
        return actions.get(action_id)
    except KeyError:
        raise HTTPException(404, f"action {action_id} not found") from None


@app.post("/actions", status_code=201)
def create_action(req: ActionCreate) -> actions.Action:
    payload = dict(req.payload)
    if req.type == "outreach" and not (payload.get("subject") and payload.get("body")):
        if len(req.lead_ids) != 1:
            raise HTTPException(400, "auto-drafted outreach targets exactly one lead")
        lead_id = req.lead_ids[0]
        with db.cursor() as cur:
            b = score_one(cur, lead_id)
            if b is None:
                raise HTTPException(400, f"unknown lead_ids: {lead_id}")
            lead = db.fetch_dicts(cur, "SELECT * FROM leads WHERE lead_id = ?", [lead_id])[0]
            company = next(iter(db.fetch_dicts(cur, "SELECT * FROM companies WHERE company_id = ?", [lead["company_id"]])), None)
        payload.update(explain.draft_outreach(b, lead, company).model_dump(exclude={"source"}))
    try:
        return actions.create(req.type, req.lead_ids, payload, req.actor, req.note)
    except actions.ActionError as exc:
        raise HTTPException(400, str(exc)) from None


def _transition(fn: Any, action_id: str, d: Decision) -> actions.Action:
    try:
        return fn(action_id, d.actor, d.note)
    except KeyError:
        raise HTTPException(404, f"action {action_id} not found") from None
    except actions.ActionConflict as exc:
        raise HTTPException(409, str(exc)) from None


@app.post("/actions/{action_id}/approve")
def approve_action(action_id: str, d: Decision) -> actions.Action:
    return _transition(actions.approve, action_id, d)


@app.post("/actions/{action_id}/reject")
def reject_action(action_id: str, d: Decision) -> actions.Action:
    return _transition(actions.reject, action_id, d)


# ---------------------------------------------------------------- evals

@app.get("/evals/latest")
def evals_latest() -> dict[str, Any]:
    if not EVALS_PATH.exists():
        raise HTTPException(404, "no eval run yet; run `python -m evals.run`")
    return json.loads(EVALS_PATH.read_text(encoding="utf-8"))
