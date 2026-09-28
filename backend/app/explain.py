"""One-line "why now" explanations grounded in a lead's score breakdown."""

import json
from typing import Any, Literal

from pydantic import BaseModel

from app import citations, llm
from app.scoring import ScoreBreakdown

MAX_ATTEMPTS = 2
PROMPT_CONTRIBUTIONS = 8

SYSTEM = """You write a one-line "why now" note telling a salesperson why to act on a lead today.
Use ONLY the facts provided. Return JSON: {"why_now": "..."}.
- One sentence, at most 30 words, plain and concrete. No hype, no emojis.
- Cite every fact inline with its row ID in square brackets, e.g. [ACT-01234], [CO-00042], [LD-00007].
  Only use IDs from the facts.
- Do not write any numbers except ones that appear verbatim in the facts. Never compute or add numbers."""


class Explanation(BaseModel):
    lead_id: str
    why_now: str
    citations: list[str]
    valid: bool
    source: Literal["llm", "template"]
    provider: str | None = None
    notes: list[str] = []


def evidence_rows(b: ScoreBreakdown) -> list[dict[str, Any]]:
    rows = []
    for name, comp in (("fit", b.fit), ("intent", b.intent), ("recency", b.recency)):
        for c in comp.contributions[:PROMPT_CONTRIBUTIONS]:
            rows.append({"component": name, "ref": c.ref, "field": c.field, "value": c.value, "points": c.points})
    rows.append({"component": "total", "ref": b.lead_id, "field": "score", "value": str(b.score), "points": b.score})
    return rows


def template(b: ScoreBreakdown) -> str:
    parts: list[str] = []
    labels = {"demo_request": "requested a demo", "pricing_page_visit": "viewed pricing", "meeting": "took a meeting",
              "email_reply": "replied to email", "call": "took a call", "website_visit": "visited the site",
              "email_open": "opened an email"}
    top = []
    for c in b.intent.contributions:  # strongest signal of each type, at most two
        if c.field not in {t.field for t in top}:
            top.append(c)
        if len(top) == 2:
            break
    if top:
        parts.append(" and ".join(f"{labels.get(c.field, c.field)} {c.value} [{c.ref}]" for c in top))
    company_ref = next((c.ref for c in b.fit.contributions if c.source == "company"), None)
    parts.append(f"{b.fit.summary}" + (f" [{company_ref}]" if company_ref else ""))
    parts.append(f"{b.recency.summary} [{b.lead_id}]")
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def explain(b: ScoreBreakdown, context: dict[str, Any] | None = None) -> Explanation:
    rows = evidence_rows(b)
    # Summaries embed numbers (e.g. "600-person"), so they count as evidence too.
    evidence = rows + [{"fit": b.fit.summary, "intent": b.intent.summary, "recency": b.recency.summary}]
    notes: list[str] = []
    if llm.available():
        feedback: str | None = None
        facts = {"lead_id": b.lead_id, "score": b.score, "context": context or {},
                 "fit_summary": b.fit.summary, "intent_summary": b.intent.summary,
                 "recency_summary": b.recency.summary, "facts": rows}
        for _ in range(MAX_ATTEMPTS):
            user = json.dumps(facts, default=str)
            if feedback:
                user += f"\n\nYour previous note was rejected: {feedback}. Fix it."
            try:
                data, provider = llm.complete_json(SYSTEM, user)
            except llm.LLMUnavailable as exc:
                notes.append(f"LLM unavailable: {exc}")
                break
            text = str(data.get("why_now", "")).strip()
            report = citations.check(text, evidence)
            if report.valid and text:
                return Explanation(lead_id=b.lead_id, why_now=text, citations=report.cited, valid=True,
                                   source="llm", provider=provider, notes=notes)
            feedback = report.reason or "empty note"
            notes.append(f"Rejected: {feedback}")

    text = template(b)
    report = citations.check(text, evidence)
    return Explanation(lead_id=b.lead_id, why_now=text, citations=report.cited, valid=report.valid,
                       source="template", notes=notes)


DRAFT_SYSTEM = """You draft a short, plain B2B sales email to a lead. Use ONLY the facts provided.
Return JSON: {"subject": "...", "body": "..."}.
- Subject under 8 words. Body 3-5 sentences, no hype, no emojis, signed by the owner's first name.
- Reference the lead's recent activity naturally; do not mention scores, tracking or internal IDs.
- Do not state any numbers that are not in the facts."""

ACTIVITY_PHRASES = {
    "demo_request": "your demo request", "pricing_page_visit": "your interest in our pricing",
    "meeting": "our recent conversation", "email_reply": "your reply", "call": "our recent call",
    "website_visit": "your recent visit", "email_open": "my last note",
}


class OutreachDraft(BaseModel):
    subject: str
    body: str
    citations: list[str]
    source: Literal["llm", "template"]


def draft_outreach(b: ScoreBreakdown, lead: dict[str, Any], company: dict[str, Any] | None) -> OutreachDraft:
    """Draft an email for human review. Citations record which rows motivated it."""
    top = b.intent.contributions[0] if b.intent.contributions else None
    cited = [b.lead_id] + ([top.ref] if top else [])
    first = (lead.get("first_name") or "there").strip()
    first = first.title() if first.isupper() else first  # CRM rows are sometimes all caps
    owner_first = (lead.get("owner") or "").split(" ")[0] or "The team"
    company_name = company["name"] if company else "your team"
    if llm.available():
        facts = {"lead_first_name": first, "title": lead.get("title"), "company": company_name,
                 "industry": company.get("industry") if company else None, "owner": lead.get("owner"),
                 "stage": lead.get("stage"), "recent_activity": [c.field for c in b.intent.contributions[:3]],
                 "follow_up_status": b.recency.summary}
        try:
            data, _ = llm.complete_json(DRAFT_SYSTEM, json.dumps(facts, default=str))
            subject, body = str(data.get("subject", "")).strip(), str(data.get("body", "")).strip()
            evidence = [{k: str(v) for k, v in facts.items()}]
            if subject and body and citations.check(f"{subject} {body}", evidence, require_citation=False).valid:
                return OutreachDraft(subject=subject, body=body, citations=cited, source="llm")
        except llm.LLMUnavailable:
            pass
    hook = ACTIVITY_PHRASES.get(top.field, "your interest") if top else "where things stand"
    subject = f"Following up on {hook}"
    body = (f"Hi {first},\n\nThanks for {hook}. I'd love to understand what {company_name} is looking to solve "
            f"and whether a short call this week would help.\n\nWould Tuesday or Wednesday work?\n\n{owner_first}")
    return OutreachDraft(subject=subject, body=body, citations=cited, source="template")
