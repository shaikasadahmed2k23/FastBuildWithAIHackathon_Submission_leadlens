"""Quota protection: answer cache, data-version invalidation, rate limit, call ledger."""

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import actions, ask, cache, db, llm
from app.config import settings
from app.main import app
from app.ratelimit import RateLimiter
from app.seed import GroundTruth
from tests.test_ask import TOP3, FakeLLM, _top3


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[dict[str, Any]]], FakeLLM]:
    def install(replies: list[dict[str, Any]]) -> FakeLLM:
        fake = FakeLLM(replies)
        monkeypatch.setattr(settings, "groq_api_key", "test")
        monkeypatch.setattr(llm, "complete_json", fake)
        return fake
    return install


def _good_answer() -> dict[str, str]:
    return {"answer": f"The top lead is [{_top3()[0]['lead_id']}]."}


def test_normalize_question() -> None:
    assert cache.normalize_question('  "Top 3   LEADS?" ') == cache.normalize_question("top 3 leads")
    assert cache.normalize_question("top 3 leads") != cache.normalize_question("top 4 leads")


def test_repeat_question_is_served_from_cache(seeded: GroundTruth, scripted: Callable[..., FakeLLM]) -> None:
    fake = scripted([{"sql": TOP3}, _good_answer()])
    first = ask.ask("Top 3 leads?")
    assert not first.cached and first.valid
    second = ask.ask("top 3 leads")  # different case/punctuation, same question
    assert second.cached and second.tokens == 0 and second.answer == first.answer
    assert len(fake.prompts) == 2  # no LLM calls for the repeat


def test_data_change_invalidates_cache(fresh_db: GroundTruth, scripted: Callable[..., FakeLLM]) -> None:
    scripted([{"sql": TOP3}, _good_answer(), {"sql": TOP3}, _good_answer()])
    ask.ask("top 3 leads")
    lead_id = fresh_db.stale[0]
    actions.approve(actions.create("stage_change", [lead_id], {"stage": "qualified"}, "a").action_id, "b")
    assert not ask.ask("top 3 leads").cached


def test_fallback_answers_are_not_cached(seeded: GroundTruth, scripted: Callable[..., FakeLLM]) -> None:
    scripted([{"sql": TOP3}, {"answer": "[LD-99999]"}, {"answer": "[LD-99998]"},
              {"sql": TOP3}, {"answer": "[LD-99999]"}, {"answer": "[LD-99998]"}])
    assert ask.ask("top 3 leads").fallback == "template"
    assert not ask.ask("top 3 leads").cached


def test_rate_limiter_window() -> None:
    rl = RateLimiter()
    assert all(rl.check("ip", 3, now=t) is None for t in (0.0, 1.0, 2.0))
    assert rl.check("ip", 3, now=3.0) == pytest.approx(57.0)
    assert rl.check("other", 3, now=3.0) is None
    assert rl.check("ip", 3, now=61.0) is None  # the first hit has left the window


@pytest.fixture
def client(seeded: GroundTruth, offline: None) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_ask_endpoint_is_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_rate_limit_per_min", 2)
    body = {"question": "how many stale leads"}
    assert client.post("/ask", json=body).status_code == 200
    assert client.post("/ask", json=body).status_code == 200
    limited = client.post("/ask", json=body)
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1
    assert client.get("/leads", params={"page_size": 1}).status_code == 200  # other endpoints unaffected


def test_examples_endpoint(client: TestClient) -> None:
    examples = client.get("/ask/examples").json()
    assert 8 <= len(examples) <= 10


def test_every_provider_call_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "test")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    ok = {"choices": [{"message": {"content": '{"sql": "SELECT 1"}'}}],
          "usage": {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42}}
    replies = [httpx.Response(200, json=ok, request=httpx.Request("POST", llm.GROQ_URL)),
               httpx.Response(400, json={"error": {"message": "bad request"}}, request=httpx.Request("POST", llm.GROQ_URL))]
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: replies.pop(0))
    with llm.track_usage() as usage:
        llm.complete_json("sys", "user", purpose="ask.sql")
        with pytest.raises(llm.LLMUnavailable):
            llm.complete_json("sys", "user", purpose="ask.answer")
    assert usage.tokens == 42 and usage.by_purpose == {"ask.sql": 42}
    entries = llm.read_log()
    assert [(e["purpose"], e["ok"]) for e in entries] == [("ask.sql", True), ("ask.answer", False)]
    assert entries[0]["total_tokens"] == 42 and "bad request" in entries[1]["error"]
    json.dumps(entries)  # ledger stays plain JSON


def test_cache_table_survives_reconnect(seeded: GroundTruth) -> None:
    cache.put("ask", "k1", {"x": 1})
    db.close()
    assert cache.get("ask", "k1") == {"x": 1}
