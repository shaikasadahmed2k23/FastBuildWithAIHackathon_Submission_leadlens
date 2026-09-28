"""Verify that every ID and number an LLM states is backed by the evidence rows."""

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

ID_PATTERN = re.compile(r"\b(?:LD|CO|ACT|ISS|AX)-\d{4,6}\b")
_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?\b")
_NUMBER_PATTERN = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?(?![\w])")


class CitationReport(BaseModel):
    valid: bool
    cited: list[str]
    unknown_ids: list[str]  # cited but absent from the evidence
    unsupported_numbers: list[str]  # stated but not derivable from the evidence
    reason: str | None = None


def extract_ids(text: str) -> list[str]:
    seen: list[str] = []
    for match in ID_PATTERN.findall(text):
        if match not in seen:
            seen.append(match)
    return seen


def evidence_ids(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for row in rows:
        for value in row.values():
            if isinstance(value, str):
                ids.update(ID_PATTERN.findall(value))
            elif isinstance(value, (list, tuple)):
                ids.update(v for v in value if isinstance(v, str) and ID_PATTERN.fullmatch(v))
    return ids


def evidence_numbers(rows: Iterable[Mapping[str, Any]]) -> list[float]:
    nums: list[float] = []
    for row in rows:
        for value in row.values():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                nums.append(float(value))
            elif isinstance(value, str) and not ID_PATTERN.fullmatch(value):
                nums.extend(float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*(?:\.\d+)?", value)
                            if n.replace(",", "").replace("-", "").replace(".", "").isdigit())
    return nums


def _number_supported(token: str, allowed: list[float]) -> bool:
    raw = token.rstrip("%").replace(",", "")
    value = float(raw)
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    tolerance = 0.5 * 10 ** -decimals + 1e-9
    candidates = allowed + [a * 100 for a in allowed] if token.endswith("%") else allowed
    return any(abs(value - a) <= tolerance for a in candidates)


def check(
    text: str,
    rows: list[Mapping[str, Any]],
    *,
    extra_numbers: Iterable[float] = (),
    require_citation: bool | None = None,
) -> CitationReport:
    """Reject text that cites IDs not in ``rows`` or states numbers not in ``rows``.

    ``extra_numbers`` whitelists context numbers (e.g. ones from the question).
    ``require_citation`` defaults to True whenever the evidence contains IDs.
    """
    cited = extract_ids(text)
    known = evidence_ids(rows)
    unknown = [c for c in cited if c not in known]

    stripped = _DATE_PATTERN.sub(" ", ID_PATTERN.sub(" ", text))
    allowed = evidence_numbers(rows) + [float(len(rows))] + [float(n) for n in extra_numbers]
    unsupported = [t for t in _NUMBER_PATTERN.findall(stripped) if not _number_supported(t, allowed)]

    if require_citation is None:
        require_citation = bool(known)
    reason = None
    if unknown:
        reason = f"cites IDs not in the query result: {', '.join(unknown)}"
    elif unsupported:
        reason = f"states numbers not in the query result: {', '.join(unsupported)}"
    elif require_citation and not cited:
        reason = "makes claims without citing any row ID"
    return CitationReport(valid=reason is None, cited=cited, unknown_ids=unknown,
                          unsupported_numbers=unsupported, reason=reason)


def jsonable(value: Any) -> Any:
    """Make DuckDB row values JSON-friendly for prompts and API responses."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value
