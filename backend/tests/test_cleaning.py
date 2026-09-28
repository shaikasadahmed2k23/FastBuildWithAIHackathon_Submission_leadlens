from datetime import datetime

import pandas as pd

from app import db
from app.cleaning import find_duplicates, normalize_email
from app.seed import GroundTruth


def test_normalize_email_handles_gmail_dots_case_and_blanks() -> None:
    assert normalize_email("John.Smith+crm@GMAIL.com") == "johnsmith@gmail.com"
    assert normalize_email(" Jane.Doe@Acme.io ") == "jane.doe@acme.io"
    assert normalize_email("  ") is None
    assert normalize_email(None) is None
    assert normalize_email(float("nan")) is None


def _leads(rows: list[tuple[str, str, str, str, str | None]]) -> pd.DataFrame:
    return pd.DataFrame(
        [(lid, co, f, l, e, datetime(2026, 1, i + 1)) for i, (lid, co, f, l, e) in enumerate(rows)],
        columns=["lead_id", "company_id", "first_name", "last_name", "email", "created_at"],
    )


def test_find_duplicates_catches_typos_and_marks_newer_record() -> None:
    df = _leads([
        ("LD-1", "CO-1", "Maria", "Gonzalez", "maria.gonzalez@acme.com"),
        ("LD-2", "CO-1", "Maria", "Gonzales", "maria.gonzales@acme.com"),  # typo in both
        ("LD-3", "CO-2", "Ann", "Lee", "ann.lee7@gmail.com"),
        ("LD-4", "CO-2", "ANN", "LEE", "annlee7@gmail.com"),  # case + gmail dots
    ])
    pairs = {(p.lead_id, p.related_lead_id) for p in find_duplicates(df)}
    assert pairs == {("LD-2", "LD-1"), ("LD-4", "LD-3")}


def test_find_duplicates_ignores_different_people_at_same_company() -> None:
    df = _leads([
        ("LD-1", "CO-1", "Maria", "Gonzalez", "maria.gonzalez@acme.com"),
        ("LD-2", "CO-1", "Mario", "Rossi", "mario.rossi@acme.com"),
        ("LD-3", "CO-2", "Maria", "Gonzalez", "maria.gonzalez@other.com"),  # same name, other company
    ])
    assert find_duplicates(df) == []


def test_detected_issues_match_ground_truth(seeded: GroundTruth) -> None:
    with db.cursor() as cur:
        dups = {frozenset(r) for r in cur.execute(
            "SELECT lead_id, related_lead_id FROM data_issues WHERE issue_type = 'duplicate'").fetchall()}
        stale = {r[0] for r in cur.execute(
            "SELECT lead_id FROM data_issues WHERE issue_type = 'stale'").fetchall()}
        missing = {(r[0], r[1].removeprefix("Missing ")) for r in cur.execute(
            "SELECT lead_id, details FROM data_issues WHERE issue_type = 'missing_field'").fetchall()}

    truth_dups = {frozenset((d["lead_id"], d["original_id"])) for d in seeded.duplicates}
    true_pos = len(dups & truth_dups)
    assert true_pos / len(dups) >= 0.95, "duplicate precision"
    assert true_pos / len(truth_dups) >= 0.95, "duplicate recall"
    assert stale == set(seeded.stale)
    assert missing == {(m["lead_id"], m["field"]) for m in seeded.missing}
