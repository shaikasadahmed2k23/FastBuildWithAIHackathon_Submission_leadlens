from datetime import datetime

import pandas as pd
import pytest

from app import db
from app.cleaning import find_duplicates, normalize_company, normalize_email, normalize_phone, same_person_name
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



@pytest.mark.parametrize(
    ("a", "b"),
    [("Acme Labs Inc", "ACME LABS, Ltd."), ("Wallace Robotics S.A.", "Wallace Robotics GmbH"),
     ("Müller Foods Pvt Ltd", "Muller Foods"), ("Nova B.V.", "Nova")],
)
def test_company_legal_forms_are_ignored(a: str, b: str) -> None:
    assert normalize_company(a) == normalize_company(b)


def test_phone_formats_normalize() -> None:
    assert normalize_phone("+1 (415) 555-0134") == normalize_phone("415.555.0134") == "4155550134"
    assert normalize_phone("123") is None


@pytest.mark.parametrize(
    ("first_a", "last_a", "first_b", "last_b", "same"),
    [
        ("bob", "smith", "robert", "smith", True),       # nickname
        ("dan", "lee", "daniel", "lee", True),
        ("dan", "lee", "danielle", "lee", False),        # nickname must resolve exactly
        ("chris", "lee", "christine", "lee", False),
        ("alex", "lopez", "alexis", "lopez", False),
        ("raul", "freitas", "paulo", "freitas", False),
        ("gary", "jackson", "gayr", "jackson", True),    # adjacent swap
        ("john", "riggs", "jon", "riggs", True),         # dropped letter
        ("ann", "lee", "dan", "lee", False),             # two short names need an exact match
        ("garcia", "jose", "jose", "garcia", True),      # swapped fields
    ],
)
def test_same_person_name(first_a: str, last_a: str, first_b: str, last_b: str, same: bool) -> None:
    assert (same_person_name(first_a, last_a, first_b, last_b) is not None) is same


def test_shared_office_phone_does_not_merge_different_people() -> None:
    df = pd.DataFrame([
        ("LD-1", "CO-1", "Acme Inc", "Maria", "Gonzalez", "maria@acme.com", "+1 415 555 0100", datetime(2026, 1, 1)),
        ("LD-2", "CO-1", "Acme Inc", "Peter", "Novak", "peter@acme.com", "(415) 555-0100", datetime(2026, 1, 2)),
        ("LD-3", "CO-2", "Acme Ltd", "José", "Müller", None, None, datetime(2026, 1, 3)),
        ("LD-4", "CO-1", "Acme Inc", "Jose", "Muller", None, None, datetime(2026, 1, 4)),
    ], columns=["lead_id", "company_id", "company_name", "first_name", "last_name", "email", "phone", "created_at"])
    assert {(p.lead_id, p.related_lead_id) for p in find_duplicates(df)} == {("LD-4", "LD-3")}
