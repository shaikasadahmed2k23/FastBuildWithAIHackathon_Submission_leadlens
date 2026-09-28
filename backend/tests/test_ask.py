from collections.abc import Callable
from typing import Any

import pytest

from app import ask, llm, sql_guard
from app.config import settings
from app.seed import GroundTruth

TOP3 = ("SELECT l.lead_id, s.score FROM leads l JOIN lead_scores s ON s.lead_id = l.lead_id "
        "ORDER BY s.score DESC, l.lead_id LIMIT 3")


class FakeLLM:
    """Replays scripted JSON replies and records the prompts it saw."""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def __call__(self, system: str, user: str) -> tuple[dict[str, Any], str]:
        self.prompts.append(user)
        if not self.replies:
            raise llm.LLMUnavailable("script exhausted")
        return self.replies.pop(0), "fake"


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[dict[str, Any]]], FakeLLM]:
    def install(replies: list[dict[str, Any]]) -> FakeLLM:
        fake = FakeLLM(replies)
        monkeypatch.setattr(settings, "groq_api_key", "test")
        monkeypatch.setattr(llm, "complete_json", fake)
        return fake
    return install


def _top3() -> list[dict[str, Any]]:
    return sql_guard.run(TOP3)[2]


def test_offline_count_question_matches_ground_truth(seeded: GroundTruth, offline: None) -> None:
    r = ask.ask("How many stale leads are there?")
    assert r.source == "rules" and r.valid
    assert r.rows == [{"lead_count": len(seeded.stale)}]
    assert str(len(seeded.stale)) in r.answer


def test_offline_list_question_cites_rows(seeded: GroundTruth, offline: None) -> None:
    r = ask.ask("top 5 open leads in Fintech")
    assert r.valid and len(r.rows) == 5
    assert r.citations and set(r.citations) <= {row["lead_id"] for row in r.rows}
    assert r.rows == sorted(r.rows, key=lambda x: -x["score"])


def test_offline_unknown_question_is_flagged(seeded: GroundTruth, offline: None) -> None:
    r = ask.ask("what is the weather")
    assert not r.valid and r.source == "none" and r.rows == []


def test_llm_happy_path(seeded: GroundTruth, fake_llm: Callable[..., FakeLLM]) -> None:
    top = _top3()[0]
    fake_llm([{"sql": TOP3}, {"answer": f"The top lead is [{top['lead_id']}] with a score of {top['score']}."}])
    r = ask.ask("Who are the top 3 leads?")
    assert r.valid and r.source == "llm" and r.citations == [top["lead_id"]]


def test_llm_unsafe_sql_is_retried(seeded: GroundTruth, fake_llm: Callable[..., FakeLLM]) -> None:
    top = _top3()[0]
    fake = fake_llm([{"sql": "DELETE FROM leads"}, {"sql": TOP3}, {"answer": f"Best: [{top['lead_id']}]."}])
    r = ask.ask("top 3 leads")
    assert r.valid and r.attempts == 2
    assert "only SELECT" in fake.prompts[1]


def test_hallucinated_citation_is_rejected_then_fixed(seeded: GroundTruth, fake_llm: Callable[..., FakeLLM]) -> None:
    top = _top3()[0]
    fake = fake_llm([{"sql": TOP3}, {"answer": "Top lead is [LD-99999]."}, {"answer": f"Top lead is [{top['lead_id']}]."}])
    r = ask.ask("top 3 leads")
    assert r.valid and r.citations == [top["lead_id"]]
    assert "LD-99999" in fake.prompts[2]
    assert any("LD-99999" in n for n in r.notes)


def test_persistent_hallucination_falls_back_to_template(seeded: GroundTruth, fake_llm: Callable[..., FakeLLM]) -> None:
    fake_llm([{"sql": TOP3}, {"answer": "Top is [LD-99999]."}, {"answer": "Top scores 101 [LD-99998]."}])
    r = ask.ask("top 3 leads")
    assert r.valid and "LD-99999" not in r.answer and "LD-99998" not in r.answer
    assert any("template" in n for n in r.notes)


def test_llm_outage_falls_back_to_rules(seeded: GroundTruth, fake_llm: Callable[..., FakeLLM]) -> None:
    fake_llm([])
    r = ask.ask("how many stale leads")
    assert r.source == "rules" and r.valid and r.rows == [{"lead_count": len(seeded.stale)}]


def test_fallback_labels_and_attempt_counts(seeded: GroundTruth, fake_llm: Callable[..., FakeLLM]) -> None:
    top = _top3()[0]
    fake_llm([{"sql": TOP3}, {"answer": "Top is [LD-99999]."}, {"answer": f"Top is [{top['lead_id']}]."}])
    r = ask.ask("top 3 leads")
    assert (r.fallback, r.attempts, r.answer_attempts) == ("none", 1, 2)

    fake_llm([{"sql": TOP3}, {"answer": "Top is [LD-99999]."}, {"answer": "Top is [LD-99998]."}])
    assert ask.ask("top 3 leads").fallback == "template"


def test_repeated_bad_sql_falls_back_to_rules(seeded: GroundTruth, fake_llm: Callable[..., FakeLLM]) -> None:
    fake_llm([{"sql": "DELETE FROM leads"}] * 3)
    r = ask.ask("how many stale leads")
    assert r.source == "rules" and r.fallback == "rules" and r.valid
    assert r.rows == [{"lead_count": len(seeded.stale)}]


def test_offline_mode_is_not_counted_as_fallback(seeded: GroundTruth, offline: None) -> None:
    r = ask.ask("how many stale leads")
    assert r.source == "rules" and r.fallback == "none"
