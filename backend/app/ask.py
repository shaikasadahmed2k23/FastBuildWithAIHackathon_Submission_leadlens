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
      seniority ['c_level','vp','director','manager','individual'],
      source ['website','referral','linkedin','event','cold_outbound','partner'], stage, deal_value DOUBLE NULL,
      owner, created_at, last_contacted_at TIMESTAMP NULL (NULL = never contacted), updated_at)
activities(activity_id VARCHAR 'ACT-00001', lead_id, type, occurred_at TIMESTAMP)
  type in ['email_open','email_reply','call','meeting','demo_request','website_visit','pricing_page_visit']
data_issues(issue_id VARCHAR 'ISS-00001', lead_id, issue_type ['duplicate','stale','missing_field'],
            details VARCHAR (e.g. 'Missing email'), related_lead_id VARCHAR NULL)
lead_scores(lead_id, score DOUBLE 0-100, fit 0-40, intent 0-40, recency 0-20)

Stages: open = {list(OPEN_STAGES)}, closed = ['won','lost'].
Industries: Software, Fintech, Healthcare, E-commerce, Logistics, Manufacturing, Education, Media.
Owners are full names, e.g. 'Maya Chen'. Countries are ISO codes ('US','GB','DE','IN','CA','AU','FR').
The dataset is frozen: "now" is {AS_OF_SQL}. Never use now(), current_date or current_timestamp.

Data quirks (the CRM is messy on purpose):
- A missing email/phone/title may be stored as NULL, '' or whitespace. Test "missing" with
  (col IS NULL OR trim(col) = ''). data_issues rows with issue_type 'missing_field' list the same leads.
- Names and emails can have inconsistent case; compare them case-insensitively."""

SQL_SYSTEM = f"""You translate a sales team's question into ONE DuckDB SELECT query.
{SCHEMA_DOC}

Rules:
- Return JSON: {{"sql": "..."}}. One SELECT (CTEs allowed). No DDL/DML, no semicolons.
- When the answer concerns specific leads/companies/activities, SELECT their ID column
  (lead_id, company_id, activity_id, issue_id) so the answer can cite them.
- For "top"/"best"/"hottest" leads, rank by lead_scores.score DESC, tie-break by lead_id.
- Include a readable name column when listing leads (first_name || ' ' || last_name AS name).
- LIMIT only for ranking questions ("top", "best", "hottest", "first N"): use N, or 10 if no
  number is given. For "which"/"list"/"show" questions return every matching row (no LIMIT;
  the system caps results at 200). Never truncate a complete list silently.
- Aggregate in SQL; never expect the reader to count or compute.
- Coded columns (stage, seniority, source, type, issue_type, industry, country, owner) hold the exact
  values listed above: compare with = or IN (...). Use ILIKE only for free text such as names,
  company names or titles.
- DuckDB dialect: no ILIKE ANY/ALL, no LIKE ANY; write separate conditions joined with OR instead."""

ANSWER_SYSTEM = """You answer a sales team's question using ONLY the SQL result rows provided.
Return JSON: {"answer": "..."}.
- 1-3 short sentences, plain and specific. No preamble, no markdown headers.
- Cite the row IDs you rely on inline in square brackets, e.g. [LD-00123] or [ACT-04567].
  Cite only IDs that appear in the rows. If rows have IDs, you must cite at least one.
- If the rows have no ID values (e.g. a count or an average), cite nothing. Never invent
  reference labels such as [row-0] or [1]; square brackets are only for real row IDs.
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
    attempts: int = 0  # SQL generation attempts
    answer_attempts: int = 0  # LLM answer-writing attempts
    # How the final answer was produced when the LLM path didn't fully succeed:
    # "template" = LLM SQL + deterministic summary; "rules" = rule-based parser after an LLM failure.
    fallback: Literal["none", "template", "rules"] = "none"
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
            data, provider = llm.complete_json(SQL_SYSTEM, user)
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


def ask(question: str) -> AskResponse:
    question = question.strip()
    notes: list[str] = []
    llm_failed = False
    if llm.available():
        result = _ask_llm(question, notes)
        if result is not None:
            return result
        llm_failed = True
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
            attempts=MAX_SQL_ATTEMPTS if llm_failed else 0, fallback="rules" if llm_failed else "none", notes=notes,
        )
    sql, columns, rows = sql_guard.run(matched.sql)
    return _finish(question, sql, columns, rows, template_answer(columns, rows), source="rules",
                   fallback="rules" if llm_failed else "none", notes=notes + [f"Matched rule: {matched.rule}"])
