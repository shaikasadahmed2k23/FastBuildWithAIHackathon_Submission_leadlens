"""Plain-English questions -> SQL -> verified, cited answer."""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel

from app import cache, citations, llm, rules, sql_guard
from app.config import AS_OF_SQL, settings

MAX_SQL_ATTEMPTS = 3
MAX_ANSWER_ATTEMPTS = 2
PROMPT_ROWS = 12  # rows shown to the answer writer; the checker still sees all rows
TEMPLATE_ROWS = 5

# Kept deliberately terse: every line carries a fact the model got wrong without it
# (blank encoding, exact codes, definitions, dialect, LIMIT rule). See docs/EVALS.md.
SCHEMA_DOC = f"""DuckDB tables (read-only). IDs look like LD-00001, CO-00001, ACT-00001, ISS-00001.
companies(company_id, name, domain, industry, employees, country, created_at)
leads(lead_id, company_id, first_name, last_name, email, phone, title, seniority, source, stage,
      deal_value, owner, created_at, last_contacted_at, updated_at)
activities(activity_id, lead_id, type, occurred_at)
data_issues(issue_id, lead_id, issue_type, details, related_lead_id)
lead_scores(lead_id, score 0-100, fit 0-40, intent 0-40, recency 0-20)

Exact codes (compare with = or IN, never LIKE):
seniority: c_level vp director manager individual
source: website referral linkedin event cold_outbound partner
stage: open = new contacted qualified proposal negotiation; closed = won lost
activities.type: email_open email_reply call meeting demo_request website_visit pricing_page_visit
issue_type: duplicate stale missing_field (details like 'Missing email')
industry: Software Fintech Healthcare E-commerce Logistics Manufacturing Education Media
country: US GB DE IN CA AU FR. owner: full name, e.g. 'Maya Chen'.

Now is {AS_OF_SQL} (frozen data; never now()/current_date).
Data-quality questions: use data_issues. stale = open lead with no contact for >90 days.
duplicate: lead_id is the newer copy of related_lead_id.
Missing text is NULL, '' or whitespace: (col IS NULL OR trim(col) = '').
last_contacted_at NULL = never contacted. Compare names/emails case-insensitively."""

SQL_SYSTEM = f"""Translate the sales team's question into ONE DuckDB SELECT.
{SCHEMA_DOC}

Return JSON {{"sql": "..."}}: one SELECT (CTEs ok), no semicolon.
- Select the ID column of rows the answer is about; for leads also first_name || ' ' || last_name AS name.
- Top/best/hottest leads: ORDER BY lead_scores.score DESC, tie-break by ID, LIMIT N (10 if no N).
  "Which"/"list"/"show" questions: return all matching rows, no LIMIT (results are capped at 200).
- Do all counting and aggregation in SQL.
- ILIKE only for free text (names, companies, titles). No ILIKE ANY / LIKE ANY."""

ANSWER_SYSTEM = """Answer the question using ONLY the SQL result. Return JSON {"answer": "..."}: 1-3 plain sentences.
- Cite the row IDs you use inline, like [LD-00123]; only IDs present in the rows; at least one if rows have IDs.
- Rows without IDs (counts, averages): cite nothing. Brackets are only for real row IDs, never [row-0] or [1].
- Every number must appear verbatim in the rows or be row_count. Never compute, sum or estimate.
- Only the first rows may be shown; row_count is the total. Empty result: say nothing matched."""

# Cached answers are only reused by the exact prompts and models that produced them.
PROMPT_FINGERPRINT = cache.fingerprint(SQL_SYSTEM, ANSWER_SYSTEM)


def _model_fingerprint() -> str:
    return cache.fingerprint(PROMPT_FINGERPRINT, settings.groq_model, settings.groq_reasoning_effort,
                             settings.gemini_model)


class AskResponse(BaseModel):
    question: str
    answer: str
    sql: str | None
    columns: list[str]
    rows: list[dict[str, Any]]
    citations: list[str]
    valid: bool
    source: Literal["llm", "rules", "none"]
    provider: str | None = None
    attempts: int = 0  # SQL generation attempts
    answer_attempts: int = 0  # LLM answer-writing attempts
    # How the final answer was produced when the LLM path didn't fully succeed:
    # "template" = LLM SQL + deterministic summary; "rules" = rule-based parser after an LLM failure.
    fallback: Literal["none", "template", "rules"] = "none"
    cached: bool = False  # served from the answer cache: no LLM call, zero tokens
    tokens: int = 0  # LLM tokens spent producing this response
    notes: list[str] = []


def _question_numbers(question: str) -> list[float]:
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", question)]


DISPLAY_PRIORITY = ("name", "company", "score", "details", "owner", "industry", "stage", "lead_count", "avg_score")
LABELED = ("score", "lead_count", "avg_score")


def _display(row: dict[str, Any]) -> str:
    def is_id(v: Any) -> bool:
        return isinstance(v, str) and bool(citations.ID_PATTERN.fullmatch(v))

    ident = next((v for v in row.values() if is_id(v)), None)
    keys = [k for k in DISPLAY_PRIORITY if row.get(k) is not None][:3]
    if not keys:
        keys = [k for k, v in row.items() if v is not None and not is_id(v)][:3]
    parts = [f"{k.replace('_', ' ')} {citations.jsonable(row[k])}" if k in LABELED or k not in DISPLAY_PRIORITY
             else str(citations.jsonable(row[k])) for k in keys]
    body = ", ".join(parts)
    return f"[{ident}] {body}" if ident else body


def template_answer(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """A deterministic summary built only from the rows (always passes the checker)."""
    if not rows:
        return "No matching records were found."
    if len(rows) == 1 and not citations.evidence_ids(rows):
        return "; ".join(f"{c.replace('_', ' ')}: {citations.jsonable(rows[0][c])}" for c in columns) + "."
    shown = rows[:TEMPLATE_ROWS]
    lines = "; ".join(_display(r) for r in shown)
    more = f" (showing {len(shown)} of {len(rows)})" if len(rows) > len(shown) else ""
    return f"{len(rows)} matching rows{more}: {lines}."


def _answer_with_llm(question: str, sql: str, columns: list[str], rows: list[dict[str, Any]],
                     feedback: str | None) -> tuple[str, str]:
    # Column names once plus value arrays: far fewer tokens than a list of dicts.
    payload = {
        "question": question,
        "row_count": len(rows),
        "columns": columns,
        "rows": [[citations.jsonable(r[c]) for c in columns] for r in rows[:PROMPT_ROWS]],
    }
    user = json.dumps(payload, default=str, separators=(",", ":"))
    if feedback:
        user += f"\n\nYour previous answer was rejected: {feedback}. Fix it."
    data, provider = llm.complete_json(ANSWER_SYSTEM, user, purpose="ask.answer")
    return str(data.get("answer", "")).strip(), provider


def _finish(question: str, sql: str, columns: list[str], rows: list[dict[str, Any]], answer: str, *,
            source: Literal["llm", "rules", "none"], provider: str | None = None, attempts: int = 1,
            answer_attempts: int = 0, fallback: Literal["none", "template", "rules"] = "none",
            notes: list[str]) -> AskResponse:
    # A template may mention how many rows it shows; LLM-written answers never get that allowance.
    templated = source == "rules" or fallback == "template"
    extra = _question_numbers(question) + ([float(min(TEMPLATE_ROWS, len(rows)))] if templated else [])
    report = citations.check(answer, rows, extra_numbers=extra)
    if not report.valid:
        notes = notes + [f"Rejected by citation checker: {report.reason}"]
    return AskResponse(
        question=question, answer=answer, sql=sql, columns=columns,
        rows=[{k: citations.jsonable(v) for k, v in r.items()} for r in rows],
        citations=report.cited, valid=report.valid, source=source, provider=provider,
        attempts=attempts, answer_attempts=answer_attempts, fallback=fallback, notes=notes,
    )


def _ask_llm(question: str, notes: list[str]) -> AskResponse | None:
    """The LLM path. Returns None when it can't produce a result (caller falls back to rules)."""
    feedback: str | None = None
    for attempt in range(1, MAX_SQL_ATTEMPTS + 1):
        user = f"Question: {question}"
        if feedback:
            user += f"\n\n{feedback}\nWrite a corrected query."
        candidate = ""
        try:
            data, provider = llm.complete_json(SQL_SYSTEM, user, purpose="ask.sql")
            candidate = str(data.get("sql", ""))
            sql, columns, rows = sql_guard.run(candidate)
        except llm.LLMUnavailable as exc:
            notes.append(f"LLM unavailable: {exc}")
            return None
        except sql_guard.UnsafeSQL as exc:
            # Show the model its own query next to the error; the error alone is often not enough to fix it.
            feedback = f"Your previous SQL was rejected.\nSQL: {candidate}\nError: {exc}"
            notes.append(f"SQL attempt {attempt} rejected: {exc} | SQL: {candidate[:300]}")
            continue

        answer_feedback: str | None = None
        answer_attempts = 0
        for _ in range(MAX_ANSWER_ATTEMPTS):
            answer_attempts += 1
            try:
                answer, provider = _answer_with_llm(question, sql, columns, rows, answer_feedback)
            except llm.LLMUnavailable as exc:
                notes.append(f"LLM unavailable while answering: {exc}")
                break
            report = citations.check(answer, rows, extra_numbers=_question_numbers(question))
            if report.valid:
                return _finish(question, sql, columns, rows, answer, source="llm", provider=provider,
                               attempts=attempt, answer_attempts=answer_attempts, notes=notes)
            answer_feedback = report.reason
            notes.append(f"Answer rejected: {report.reason} | Answer: {answer[:300]}")
        # The SQL result is trustworthy even when the prose isn't: summarize it deterministically.
        notes.append("Fell back to a template answer built from the query result.")
        return _finish(question, sql, columns, rows, template_answer(columns, rows), source="llm", provider=provider,
                       attempts=attempt, answer_attempts=answer_attempts, fallback="template", notes=notes)
    notes.append(f"No valid query after {MAX_SQL_ATTEMPTS} attempts.")
    return None


def ask(question: str, use_cache: bool = True) -> AskResponse:
    """Answer a question. Valid LLM answers are cached until the data changes."""
    question = question.strip()
    notes: list[str] = []
    llm_failed = False
    spent = 0
    if llm.available():
        key = cache.make_key("ask", cache.normalize_question(question), _model_fingerprint()) if use_cache else None
        if key and (hit := cache.get("ask", key)):
            return AskResponse(**{**hit, "question": question, "cached": True, "tokens": 0})
        with llm.track_usage() as usage:
            result = _ask_llm(question, notes)
        if result is not None:
            result.tokens = usage.tokens
            # Only fully-LLM, verified answers are reused; fallbacks may reflect a transient outage.
            if key and result.valid and result.fallback == "none":
                cache.put("ask", key, result.model_dump())
            return result
        llm_failed, spent = True, usage.tokens
        notes.append("Used the rule-based parser instead.")
    else:
        notes.append("No LLM key configured; used the rule-based parser.")

    matched = rules.match(question)
    if matched is None:
        return AskResponse(
            question=question,
            answer="I can't answer that without the LLM. Try e.g. \"top 10 open leads in Fintech\", "
                   "\"how many stale leads\", or \"leads that requested a demo in the last 14 days\".",
            sql=None, columns=[], rows=[], citations=[], valid=False, source="none",
            attempts=MAX_SQL_ATTEMPTS if llm_failed else 0, fallback="rules" if llm_failed else "none",
            tokens=spent, notes=notes,
        )
    sql, columns, rows = sql_guard.run(matched.sql)
    result = _finish(question, sql, columns, rows, template_answer(columns, rows), source="rules",
                     fallback="rules" if llm_failed else "none", notes=notes + [f"Matched rule: {matched.rule}"])
    result.tokens = spent
    return result
