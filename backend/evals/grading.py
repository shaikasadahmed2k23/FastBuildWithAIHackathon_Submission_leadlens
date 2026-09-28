"""Extract a comparable answer from query rows and grade it against the golden value."""

from typing import Any

from app.citations import ID_PATTERN

Expected = float | list[str] | dict[str, float] | None


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def extract(kind: str, rows: list[dict[str, Any]]) -> Expected:
    if kind == "scalar":
        if not rows:
            return None
        return next((float(v) for v in rows[0].values() if _is_number(v)), None)
    if kind == "id_set":
        ids: list[str] = []
        for row in rows:
            first = next((v for v in row.values() if isinstance(v, str) and ID_PATTERN.fullmatch(v)), None)
            if first and first not in ids:
                ids.append(first)
        return sorted(ids)
    table: dict[str, float] = {}
    for row in rows:
        key = next((v for v in row.values() if isinstance(v, str)), None)
        val = next((v for v in row.values() if _is_number(v)), None)
        if key is not None and val is not None:
            table[key.lower()] = float(val)
    return table


def _close(a: float, b: float) -> bool:
    # Allows the reader to round an average to one decimal or a sum to the unit.
    return abs(a - b) <= max(0.051, 0.001 * abs(b))


def grade(kind: str, expected: Expected, got: Expected) -> bool:
    if got is None or expected is None:
        return got == expected
    if kind == "scalar":
        return _close(float(got), float(expected))  # type: ignore[arg-type]
    if kind == "id_set":
        return set(got) == set(expected)  # type: ignore[arg-type]
    assert isinstance(got, dict) and isinstance(expected, dict)
    exp = {k.lower(): v for k, v in expected.items()}
    return set(got) == set(exp) and all(_close(got[k], exp[k]) for k in exp)
