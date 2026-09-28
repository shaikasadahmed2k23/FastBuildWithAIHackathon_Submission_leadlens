"""Thin LLM client: Groq first, Gemini as fallback, ``LLMUnavailable`` when neither works.

The LLM is only used to write SQL and to phrase explanations. It never computes
scores or numbers; callers verify everything it returns.
"""

import json
import logging
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_RATE_LIMIT_RETRIES = 4
MAX_BACKOFF_S = 30.0

# Process-wide counters (read by /health and the eval runner).
stats: Counter[str] = Counter()
last_call: dict[str, Any] = {"provider": None, "ok": None, "at": None, "error": None}


@dataclass(frozen=True)
class LLMReply:
    text: str
    provider: str


class LLMUnavailable(RuntimeError):
    pass


def available() -> bool:
    return bool(settings.groq_api_key or settings.gemini_api_key)


def configured_provider() -> str | None:
    return "groq" if settings.groq_api_key else "gemini" if settings.gemini_api_key else None


def _post(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    """POST with backoff on rate limits (429) and transient server errors (5xx)."""
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        resp = httpx.post(url, json=body, headers=headers, timeout=settings.llm_timeout_s)
        if resp.status_code != 429 and resp.status_code < 500:
            resp.raise_for_status()
            return resp.json()
        if attempt == MAX_RATE_LIMIT_RETRIES:
            resp.raise_for_status()
        stats["rate_limited" if resp.status_code == 429 else "server_errors"] += 1
        try:
            wait = float(resp.headers.get("retry-after", ""))
        except ValueError:
            wait = 2.0 ** attempt
        time.sleep(min(max(wait, 0.5), MAX_BACKOFF_S))
    raise AssertionError("unreachable")


def _groq(system: str, user: str, json_mode: bool) -> str:
    body: dict[str, Any] = {
        "model": settings.groq_model,
        "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = _post(GROQ_URL, body, {"Authorization": f"Bearer {settings.groq_api_key}"})
    stats["tokens"] += int(data.get("usage", {}).get("total_tokens", 0))
    return data["choices"][0]["message"]["content"]


def _gemini(system: str, user: str, json_mode: bool) -> str:
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    data = _post(GEMINI_URL.format(model=settings.gemini_model), body, {"x-goog-api-key": settings.gemini_api_key})
    stats["tokens"] += int(data.get("usageMetadata", {}).get("totalTokenCount", 0))
    return data["candidates"][0]["content"]["parts"][0]["text"]


def complete(system: str, user: str, json_mode: bool = True) -> LLMReply:
    """Return the first successful provider reply, or raise ``LLMUnavailable``."""
    providers = []
    if settings.groq_api_key:
        providers.append(("groq", _groq))
    if settings.gemini_api_key:
        providers.append(("gemini", _gemini))
    errors = []
    for name, call in providers:
        stats["calls"] += 1
        try:
            text = call(system, user, json_mode)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            log.warning("LLM provider %s failed: %s", name, exc)
            stats["failures"] += 1
            errors.append(f"{name}: {type(exc).__name__}")
            last_call.update(provider=name, ok=False, at=datetime.now(UTC).isoformat(timespec="seconds"),
                             error=type(exc).__name__)
            continue
        last_call.update(provider=name, ok=True, at=datetime.now(UTC).isoformat(timespec="seconds"), error=None)
        return LLMReply(text=text, provider=name)
    raise LLMUnavailable("; ".join(errors) or "no LLM provider configured")


def complete_json(system: str, user: str) -> tuple[dict[str, Any], str]:
    """Like ``complete`` but parses a JSON object (tolerating code fences)."""
    reply = complete(system, user, json_mode=True)
    text = reply.text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"{reply.provider}: invalid JSON") from exc
    if not isinstance(data, dict):
        raise LLMUnavailable(f"{reply.provider}: expected a JSON object")
    return data, reply.provider
