from typing import Any

import httpx
import pytest

from app import llm
from app.config import settings


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=httpx.Request("POST", "http://x"), response=None)  # type: ignore[arg-type]


OK = {"choices": [{"message": {"content": '{"sql": "SELECT 1"}'}}], "usage": {"total_tokens": 42}}


@pytest.fixture
def groq_only(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    monkeypatch.setattr(settings, "groq_api_key", "test")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    sleeps: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    llm.stats.clear()
    return sleeps


def test_rate_limit_is_retried_with_retry_after(groq_only: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    replies = [FakeResponse(429, headers={"retry-after": "3"}), FakeResponse(200, OK)]
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: replies.pop(0))
    data, provider = llm.complete_json("sys", "user")
    assert data == {"sql": "SELECT 1"} and provider == "groq"
    assert groq_only == [3.0]
    assert llm.stats["rate_limited"] == 1 and llm.stats["tokens"] == 42
    assert llm.last_call["ok"] is True


def test_persistent_rate_limit_raises_unavailable(groq_only: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResponse(429))
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("sys", "user")
    assert len(groq_only) == llm.MAX_RATE_LIMIT_RETRIES
    assert llm.last_call["ok"] is False


def test_provider_error_message_is_recorded_and_redacted(groq_only: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"error": {"message": "Rate limit reached for model in organization `org_01abcXYZ` on tokens per day (TPD)"}}
    response = httpx.Response(429, json=body, request=httpx.Request("POST", llm.GROQ_URL))
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: response)
    with pytest.raises(llm.LLMUnavailable) as err:
        llm.complete("sys", "user")
    assert "tokens per day" in str(err.value) and "org_01abcXYZ" not in str(err.value)
    assert llm.last_call["error"].startswith("HTTP 429")


def test_json_mode_prompt_always_mentions_json(groq_only: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    def post(url: str, json: dict[str, Any], **_: Any) -> FakeResponse:
        sent.append(json)
        return FakeResponse(200, OK)

    monkeypatch.setattr(llm.httpx, "post", post)
    llm.complete_json('Return {"sql": "..."}', "question")
    assert "json" in sent[0]["messages"][0]["content"].lower()


def test_app_prompts_mention_json() -> None:
    from app import ask, explain
    for prompt in (ask.SQL_SYSTEM, ask.ANSWER_SYSTEM, explain.SYSTEM, explain.DRAFT_SYSTEM):
        assert "json" in prompt.lower()
