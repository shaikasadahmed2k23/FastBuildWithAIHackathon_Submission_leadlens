from datetime import timedelta

import pytest

from app import db
from app.config import AS_OF
from app.scoring import intent_component, recency_points, score_lead, score_one
from app.seed import GroundTruth

LEAD = {"lead_id": "LD-1", "seniority": "vp", "stage": "qualified", "last_contacted_at": AS_OF - timedelta(days=12)}
COMPANY = {"company_id": "CO-1", "employees": 600, "industry": "Software"}


def _act(aid: str, kind: str, days_ago: float) -> dict:
    return {"activity_id": aid, "lead_id": "LD-1", "type": kind, "occurred_at": AS_OF - timedelta(days=days_ago)}


def test_breakdown_sums_and_cites_inputs() -> None:
    acts = [_act("ACT-1", "demo_request", 1), _act("ACT-2", "email_open", 3), _act("ACT-3", "meeting", 45)]
    b = score_lead(LEAD, COMPANY, acts)
    assert b.fit.points == 14 + 12 + 10
    assert b.recency.points == 20
    assert b.score == round(b.fit.points + b.intent.points + b.recency.points, 1)
    assert [c.ref for c in b.intent.contributions] == ["ACT-1", "ACT-2"]  # ACT-3 outside 30d window
    assert set(b.citations) == {"LD-1", "CO-1", "ACT-1", "ACT-2"}


def test_high_intent_signals_outweigh_passive_ones() -> None:
    demo = intent_component([_act("A", "demo_request", 2)])
    opens = intent_component([_act(f"A{i}", "email_open", 2) for i in range(5)])
    assert demo.points > opens.points


def test_intent_decays_with_age_and_is_capped() -> None:
    fresh = intent_component([_act("A", "pricing_page_visit", 0)])
    old = intent_component([_act("A", "pricing_page_visit", 20)])
    assert fresh.points > old.points
    flood = intent_component([_act(f"A{i}", "demo_request", 0) for i in range(20)])
    assert flood.points == 40


@pytest.mark.parametrize(
    ("days", "stage", "expected"),
    [(None, "new", 12.0), (1, "contacted", 2.0), (15, "proposal", 20.0), (60, "qualified", 10.0), (5, "won", 0.0)],
)
def test_recency_curve(days: float | None, stage: str, expected: float) -> None:
    assert recency_points(days, stage)[0] == expected


def test_overdue_follow_up_beats_just_contacted() -> None:
    assert recency_points(20, "qualified")[0] > recency_points(1, "qualified")[0]


def test_materialized_scores_match_on_demand_scores(seeded: GroundTruth) -> None:
    with db.cursor() as cur:
        rows = cur.execute("SELECT lead_id, score, fit, intent, recency FROM lead_scores ORDER BY lead_id LIMIT 25").fetchall()
        assert cur.execute("SELECT min(score) >= 0 AND max(score) <= 100 FROM lead_scores").fetchone()[0]
        for lead_id, score, fit, intent, recency in rows:
            b = score_one(cur, lead_id)
            assert b is not None
            assert (b.score, b.fit.points, b.intent.points, b.recency.points) == (score, fit, intent, recency)
