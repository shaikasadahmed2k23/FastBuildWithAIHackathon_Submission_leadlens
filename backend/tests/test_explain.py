from typing import Any

import pytest

from app import db, explain, llm
from app.config import settings
from app.scoring import ScoreBreakdown, score_one
from app.seed import GroundTruth


def _top_breakdown() -> ScoreBreakdown:
    with db.cursor() as cur:
        lead_id = cur.execute("SELECT lead_id FROM lead_scores ORDER BY score DESC, lead_id LIMIT 1").fetchone()[0]
        b = score_one(cur, lead_id)
    assert b is not None
    return b


def test_template_is_valid_and_cites_breakdown(seeded: GroundTruth, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    b = _top_breakdown()
    e = explain.explain(b)
    assert e.source == "template" and e.valid
    assert b.lead_id in e.citations
    assert set(e.citations) <= set(b.citations)


def test_llm_note_with_bad_citation_falls_back(seeded: GroundTruth, monkeypatch: pytest.MonkeyPatch) -> None:
    replies: list[dict[str, Any]] = [{"why_now": "Hot lead [ACT-99999]."}, {"why_now": "Score is 999 [LD-00001]."}]
    monkeypatch.setattr(settings, "groq_api_key", "test")
    monkeypatch.setattr(llm, "complete_json", lambda s, u, **_: (replies.pop(0), "fake"))
    e = explain.explain(_top_breakdown())
    assert e.source == "template" and e.valid and len(e.notes) == 2


def test_llm_note_with_valid_citation_is_used(seeded: GroundTruth, monkeypatch: pytest.MonkeyPatch) -> None:
    b = _top_breakdown()
    act = b.intent.contributions[0]
    company = next(c for c in b.fit.contributions if c.source == "company")
    note = f"Showed fresh intent [{act.ref}] and fits the ICP [{company.ref}]."
    monkeypatch.setattr(settings, "groq_api_key", "test")
    monkeypatch.setattr(llm, "complete_json", lambda s, u, **_: ({"why_now": note}, "fake"))
    e = explain.explain(b)
    assert e.source == "llm" and e.valid and e.why_now == note
