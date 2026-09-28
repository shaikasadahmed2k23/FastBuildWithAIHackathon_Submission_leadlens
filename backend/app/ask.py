"""Plain-English questions -> SQL -> verified, cited answer."""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel

from app import citations, llm, rules, sql_guard
from app.config import AS_OF_SQL, OPEN_STAGES

MAX_SQL_ATTEMPTS = 3
MAX_ANSWER_ATTEMPTS = 2
PROMPT_ROWS = 40
TEMPLATE_ROWS = 5

SCHEMA_DOC = f"""DuckDB tables (read-only):
companies(company_id VARCHAR 'CO-00001', name, domain, industry, employees INT, country, created_at TIMESTAMP)
leads(lead_id VARCHAR 'LD-00001', company_id, first_name, last_name, email, phone, title,
      seniority ['c_level','vp','director','manager','individual'], source, stage, deal_value DOUBLE,
      owner, created_at, last_contacted_at TIMESTAMP NULL, updated_at)
activities(activity_id VARCHAR 'ACT-00001', lead_id, type, occurred_at TIMESTAMP)
  type in ['email_open','email_reply','call','meeting','demo_request','website_visit','pricing_page_visit']
data_issues(issue_id VARCHAR 'ISS-00001', lead_id, issue_type ['duplicate','stale','missing_field'],
            details VARCHAR (e.g. 'Missing email'), related_lead_id VARCHAR NULL)
lead_scores(lead_id, score DOUBLE 0-100, fit 0-40, intent 0-40, recency 0-20)

Stages: open = {list(OPEN_STAGES)}, closed = ['won','lost'].
Industries: Software, Fintech, Healthcare, E-commerce, Logistics, Manufacturing, Education, Media.
Owners are full names, e.g. 'Maya Chen'. Countries are ISO codes ('US','GB','DE','IN','CA','AU','FR').
The dataset is frozen: "now" is {AS_OF_SQL}. Never use now(), current_date or current_timestamp."""

SQL_SYSTEM = f"""You translate a sales team's question into ONE DuckDB SELECT query.
{SCHEMA_DOC}

Rules:
- Return JSON: {{"sql": "..."}}. One SELECT (CTEs allowed). No DDL/DML, no semicolons.
- When the answer concerns specific leads/companies/activities, SELECT their ID column
  (lead_id, company_id, activity_id, issue_id) so the answer can cite them.
- For "top"/"best"/"hottest" leads, rank by lead_scores.score DESC, tie-break by lead_id.
- Include a readable name column when listing leads (first_name || ' ' || last_name AS name).
- Default LIMIT 10 for lists unless the question gives a number. Aggregate in SQL; never
  expect the reader to count or compute.
- Case-insensitive text matching: use ILIKE or lower()."""

ANSWER_SYSTEM = """You answer a sales team's question using ONLY the SQL result rows provided.
Return JSON: {"answer": "..."}.
- 1-3 short sentences, plain and specific. No preamble, no markdown headers.
- Cite the row IDs you rely on inline in square brackets, e.g. [LD-00123] or [ACT-04567].
  Cite only IDs that appear in the rows. If rows have IDs, you must cite at least one.
- Every number you write must appear verbatim in the rows (or be the row count).
  Do not compute, sum, average or estimate anything yourself.
- If the rows are empty, say no matching records were found."""


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
    attempts: int = 0
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
    payload = {
        "question": question,
        "sql": sql,
        "row_count": len(rows),
        "rows": [{k: citations.jsonable(v) for k, v in r.items()} for r in rows[:PROMPT_ROWS]],
    }
    user = json.dumps(payload, default=str)
    if feedback:
        user += f"\n\nYour previous answer was rejected: {feedback}. Fix it."
    data, provider = llm.complete_json(ANSWER_SYSTEM, user)
    return str(data.get("answer", "")).strip(), provider


def _finish(question: str, sql: str, columns: list[str], rows: list[dict[str, Any]], answer: str,
            source: Literal["llm", "rules", "none"], provider: str | None, attempts: int, notes: list[str],
            templated: bool = False) -> AskResponse:
    # The template may mention how many rows it shows; the LLM never gets that allowance.
    extra = _question_numbers(question) + ([float(min(TEMPLATE_ROWS, len(rows)))] if source != "llm" or templated else [])
    report = citations.check(answer, rows, extra_numbers=extra)
    if not report.valid:
        notes = notes + [f"Rejected by citation checker: {report.reason}"]
    return AskResponse(
        question=question, answer=answer, sql=sql, columns=columns,
        rows=[{k: citations.jsonable(v) for k, v in r.items()} for r in rows],
        citations=report.cited, valid=report.valid, source=source, provider=provider,
        attempts=attempts, notes=notes,
    )


def _ask_llm(question: str) -> AskResponse | None:
    notes: list[str] = []
    feedback: str | None = None
    attempts = 0
    for _ in range(MAX_SQL_ATTEMPTS):
        attempts += 1
        user = f"Question: {question}"
        if feedback:
            user += f"\n\nYour previous SQL was rejected: {feedback}. Write a corrected query."
        try:
            data, provider = llm.complete_json(SQL_SYSTEM, user)
            sql, columns, rows = sql_guard.run(str(data.get("sql", "")))
        except llm.LLMUnavailable as exc:
            notes.append(f"LLM unavailable: {exc}")
            return None
        except sql_guard.UnsafeSQL as exc:
            feedback = str(exc)
            notes.append(f"SQL attempt {attempts} rejected: {exc}")
            continue

        answer_feedback: str | None = None
        for _ in range(MAX_ANSWER_ATTEMPTS):
            try:
                answer, provider = _answer_with_llm(question, sql, columns, rows, answer_feedback)
            except llm.LLMUnavailable as exc:
                notes.append(f"LLM unavailable while answering: {exc}")
                break
            report = citations.check(answer, rows, extra_numbers=_question_numbers(question))
            if report.valid:
                return _finish(question, sql, columns, rows, answer, "llm", provider, attempts, notes)
            answer_feedback = report.reason
            notes.append(f"Answer rejected: {report.reason}")
        # The SQL result is trustworthy even when the prose isn't: summarize it deterministically.
        notes.append("Fell back to a template answer built from the query result.")
        return _finish(question, sql, columns, rows, template_answer(columns, rows), "llm", provider, attempts, notes,
                       templated=True)
    notes.append("Could not produce a valid query.")
    return AskResponse(question=question, answer="I couldn't turn that question into a valid query. Try rephrasing it.",
                       sql=None, columns=[], rows=[], citations=[], valid=False, source="llm",
                       attempts=attempts, notes=notes)


def ask(question: str) -> AskResponse:
    question = question.strip()
    notes: list[str] = []
    if llm.available():
        result = _ask_llm(question)
        if result is not None:
            return result
        notes.append("LLM unavailable; used rule-based fallback.")
    else:
        notes.append("No LLM key configured; used rule-based fallback.")

    matched = rules.match(question)
    if matched is None:
        return AskResponse(
            question=question,
            answer="I can't answer that in offline mode. Try e.g. \"top 10 open leads in Fintech\", "
                   "\"how many stale leads\", or \"leads that requested a demo in the last 14 days\".",
            sql=None, columns=[], rows=[], citations=[], valid=False, source="none", notes=notes,
        )
    sql, columns, rows = sql_guard.run(matched.sql)
    return _finish(question, sql, columns, rows, template_answer(columns, rows), "rules", None, 1,
                   notes + [f"Matched rule: {matched.rule}"])
