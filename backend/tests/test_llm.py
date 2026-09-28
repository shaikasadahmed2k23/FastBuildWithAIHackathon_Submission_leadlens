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
