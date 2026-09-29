"""Offline parser: must answer correctly or decline. Never a confident wrong answer."""

import pytest

from app import db, rules, sql_guard
from app.seed import GroundTruth

# Phrasings not in the golden set that the parser fully accounts for.
ANSWERABLE = [
    ("count the leads owned by Ravi", "SELECT count(*) FROM leads WHERE owner = 'Ravi Kumar'"),
    ("number of won leads in Healthcare",
     "SELECT count(*) FROM leads l JOIN companies c ON c.company_id = l.company_id "
     "WHERE l.stage = 'won' AND c.industry = 'Healthcare'"),
    ("how many directors are there", "SELECT count(*) FROM leads WHERE seniority = 'director'"),
    ("how many stale leads in the proposal stage",
     "SELECT count(DISTINCT i.lead_id) FROM data_issues i JOIN leads l ON l.lead_id = i.lead_id "
     "WHERE i.issue_type = 'stale' AND l.stage = 'proposal'"),
    ("how many leads are marked stale",
     "SELECT count(DISTINCT lead_id) FROM data_issues WHERE issue_type = 'stale'"),
    ("count leads tagged as missing a title",
     "SELECT count(*) FROM leads WHERE title IS NULL OR trim(title) = ''"),
    ("average score of leads from linkedin",
     "SELECT round(avg(s.score), 1) FROM leads l JOIN lead_scores s ON s.lead_id = l.lead_id WHERE l.source = 'linkedin'"),
    ("how many closed leads", "SELECT count(*) FROM leads WHERE stage IN ('won', 'lost')"),
    ("how many leads have never been contacted", "SELECT count(*) FROM leads WHERE last_contacted_at IS NULL"),
]

MUST_DECLINE = [
    # The three confident wrong answers from the held-out set (rule-based run, 5/25):
    "Top 5 leads by deal value in Manufacturing",  # was ranked by score
    "Top 4 industries by average deal value of open leads",  # was one overall average
    "How many open leads have never had any activity?",  # negation was dropped
    # Same failure classes, different wording:
    "which leads are not in Software",
    "leads without a title",
    "top 3 owners by pipeline",
    "top 10 leads by deal value",
    "how many leads were created in the last 30 days",  # day window with no activity to apply it to
    "how many leads with more activity",
    # Out of scope entirely:
    "which leads are most likely to churn next quarter",
    "what did Maya say on her last call",
    "forecast revenue for next month",
    "how many leads are flagged as spam",
]


@pytest.mark.parametrize(("question", "reference_sql"), ANSWERABLE)
def test_answerable_questions_are_correct(seeded: GroundTruth, question: str, reference_sql: str) -> None:
    m = rules.match(question)
    assert isinstance(m, rules.RuleMatch), f"{question}: {m}"
    _, _, rows = sql_guard.run(m.sql)
    with db.cursor() as cur:
        expected = cur.execute(reference_sql).fetchone()[0]
    assert next(iter(rows[0].values())) == pytest.approx(expected)


@pytest.mark.parametrize("question", MUST_DECLINE)
def test_unsupported_questions_are_declined(question: str) -> None:
    result = rules.match(question)
    assert isinstance(result, rules.RuleDecline), f"{question} was answered with: {result}"
    assert result.reason


@pytest.mark.parametrize("question", rules.OFFLINE_EXAMPLES)
def test_offline_examples_are_answerable(seeded: GroundTruth, question: str) -> None:
    m = rules.match(question)
    assert isinstance(m, rules.RuleMatch)
    assert sql_guard.run(m.sql)[2]
