"""Quota protection: answer cache, data-version invalidation, rate limit, call ledger."""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import actions, ask, cache, db, llm, sql_guard
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


COMPANIES_SQL = "SELECT count(*) AS fintech_companies FROM companies WHERE industry = 'Fintech'"


def _companies_answer() -> dict[str, str]:
    n = sql_guard.run(COMPANIES_SQL)[2][0]["fintech_companies"]
    return {"answer": f"There are {n} Fintech companies."}


def test_only_answers_reading_changed_tables_are_invalidated(fresh_db: GroundTruth,
                                                             scripted: Callable[..., FakeLLM]) -> None:
    scripted([{"sql": TOP3}, _good_answer(), {"sql": COMPANIES_SQL}, _companies_answer(),
              {"sql": TOP3}, _good_answer()])
    ask.ask("top 3 leads")
    ask.ask("how many fintech companies")

    # Proposing and rejecting actions touches only actions/audit_log: nothing is invalidated.
    lead_id = fresh_db.stale[0]
    actions.reject(actions.create("stage_change", [lead_id], {"stage": "won"}, "a").action_id, "b")
    assert ask.ask("top 3 leads").cached and ask.ask("how many fintech companies").cached

    # An approved stage change rewrites leads/lead_scores/data_issues, not companies.
    actions.approve(actions.create("stage_change", [lead_id], {"stage": "qualified"}, "a").action_id, "b")
    assert ask.ask("how many fintech companies").cached
    assert not ask.ask("top 3 leads").cached


def test_import_invalidates_answers_over_changed_tables(fresh_db: GroundTruth,
                                                        scripted: Callable[..., FakeLLM]) -> None:
    from app import importer
    from app.config import DATA_DIR

    scripted([{"sql": COMPANIES_SQL}, _companies_answer()])
    ask.ask("how many fintech companies")
    sample = (DATA_DIR / "sample_hubspot_export.csv").read_bytes()
    importer.run_import(sample, "s.csv", importer.preview(sample, "s.csv").mapping, "tester")
    assert not ask.ask("how many fintech companies", use_cache=True).cached  # new companies were created


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
    cache.put("ask", "k1", {"x": 1}, snap={}, tables=[])
    db.close()
    assert cache.get("ask", "k1") == {"x": 1}


def test_cache_seed_round_trip_survives_reset(fresh_db: GroundTruth, scripted: Callable[..., FakeLLM],
                                              tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.demo import reset_demo_data

    seed = tmp_path / "answer_cache_seed.json"
    monkeypatch.setattr(settings, "answer_cache_seed_path", str(seed))
    fake = scripted([{"sql": TOP3}, _good_answer()])
    reset_demo_data()  # clean seed-42 state, like the prewarm script
    ask.ask("top 3 leads")
    assert cache.export_entries(seed) == 1

    lead_id = fresh_db.stale[0]
    actions.approve(actions.create("stage_change", [lead_id], {"stage": "won"}, "a").action_id, "b")
    result = reset_demo_data()
    assert result.leads == 4992 and result.cached_answers_loaded == 1
    assert ask.ask("top 3 leads").cached and len(fake.prompts) == 2  # served from the seed, no LLM call


def test_seed_entries_for_other_data_are_skipped(fresh_db: GroundTruth, tmp_path: Path) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([{"kind": "ask", "key": "k", "payload": {}, "deps": {"leads": "not-a-real-hash"}}]))
    assert cache.load_entries(seed) == 0


def test_reset_endpoint(fresh_db: GroundTruth, offline: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "answer_cache_seed_path", str(tmp_path / "missing.json"))
    with TestClient(app) as c:
        lead_id = fresh_db.stale[0]
        c.post(f"/actions/{c.post('/actions', json={'type': 'stage_change', 'lead_ids': [lead_id], 'payload': {'stage': 'won'}}).json()['action_id']}/approve", json={})
        body = c.post("/admin/reset-demo").json()
        assert body == {**body, "leads": 4992, "cached_answers_loaded": 0, "cache_seed_found": False}
        assert c.get("/actions").json() == []  # approvals are gone
        monkeypatch.setattr(settings, "demo_reset_enabled", False)
        assert c.post("/admin/reset-demo").status_code == 403


def test_old_cache_table_is_migrated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import duckdb

    path = tmp_path / "old.duckdb"
    old = duckdb.connect(str(path))
    old.execute("CREATE TABLE llm_cache (kind VARCHAR, key VARCHAR, payload VARCHAR NOT NULL, "
                "created_at TIMESTAMP NOT NULL, hits INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (kind, key))")
    old.close()
    db.close()
    monkeypatch.setattr(settings, "leadlens_db_path", str(path))
    try:
        cols = {r[0] for r in db.connect().execute("DESCRIBE llm_cache").fetchall()}
        assert "deps" in cols
    finally:
        db.close()
