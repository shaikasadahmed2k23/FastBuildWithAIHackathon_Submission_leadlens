"""Held-out phrasings (not in the golden set): the rules engine must be right or decline."""

import pytest

from app import db, rules, sql_guard
from app.seed import GroundTruth

HELD_OUT = [
    ("count the leads owned by Ravi", "SELECT count(*) FROM leads WHERE owner = 'Ravi Kumar'"),
    ("number of won leads in Healthcare",
     "SELECT count(*) FROM leads l JOIN companies c ON c.company_id = l.company_id "
     "WHERE l.stage = 'won' AND c.industry = 'Healthcare'"),
    ("how many directors are there", "SELECT count(*) FROM leads WHERE seniority = 'director'"),
    ("how many stale leads in the proposal stage",
     "SELECT count(DISTINCT i.lead_id) FROM data_issues i JOIN leads l ON l.lead_id = i.lead_id "
     "WHERE i.issue_type = 'stale' AND l.stage = 'proposal'"),
    ("average score of leads from linkedin",
     "SELECT round(avg(s.score), 1) FROM leads l JOIN lead_scores s ON s.lead_id = l.lead_id WHERE l.source = 'linkedin'"),
]

MUST_DECLINE = [
    "which leads are most likely to churn next quarter",
    "what did Maya say on her last call",
    "forecast revenue for next month",
    "how many leads are flagged as spam",
]


@pytest.mark.parametrize(("question", "reference_sql"), HELD_OUT)
def test_held_out_questions_answer_correctly(seeded: GroundTruth, question: str, reference_sql: str) -> None:
    m = rules.match(question)
    assert m is not None, question
    _, _, rows = sql_guard.run(m.sql)
    with db.cursor() as cur:
        expected = cur.execute(reference_sql).fetchone()[0]
    assert next(iter(rows[0].values())) == pytest.approx(expected)


@pytest.mark.parametrize("question", MUST_DECLINE)
def test_unknown_questions_are_declined(question: str) -> None:
    assert rules.match(question) is None
