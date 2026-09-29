"""Thin LLM client: Groq first, Gemini as fallback, ``LLMUnavailable`` when neither works.

The LLM is only used to write SQL and to phrase explanations. It never computes
scores or numbers; callers verify everything it returns.

Every provider call (success or failure) is appended to a JSONL ledger
(``settings.llm_log_path``) with its purpose, tokens, latency and error message.
"""

import json
import logging
import re
import threading
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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
_log_lock = threading.Lock()

Tokens = tuple[int, int, int]  # prompt, completion (incl. reasoning), total


@dataclass(frozen=True)
class LLMReply:
    text: str
    provider: str


@dataclass
class Usage:
    """Tokens and calls spent inside one ``track_usage()`` block, e.g. one request."""

    tokens: int = 0
    calls: int = 0
    by_purpose: Counter[str] = field(default_factory=Counter)


_current_usage: ContextVar[Usage | None] = ContextVar("llm_usage", default=None)


class LLMUnavailable(RuntimeError):
    pass


def available() -> bool:
    return bool(settings.groq_api_key or settings.gemini_api_key)


def configured_provider() -> str | None:
    return "groq" if settings.groq_api_key else "gemini" if settings.gemini_api_key else None


@contextmanager
def track_usage() -> Iterator[Usage]:
    usage = Usage()
    token = _current_usage.set(usage)
    try:
        yield usage
    finally:
        _current_usage.reset(token)


def _record(entry: dict[str, Any]) -> None:
    """Append one provider call to the JSONL ledger. Logging must never break a request."""
    path = Path(settings.llm_log_path)
    try:
        with _log_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        log.warning("could not write LLM call log: %s", exc)


def _post(url: str, body: dict[str, Any], headers: dict[str, str], retries: list[int]) -> dict[str, Any]:
    """POST with backoff on rate limits (429) and transient server errors (5xx)."""
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        resp = httpx.post(url, json=body, headers=headers, timeout=settings.llm_timeout_s)
        if resp.status_code != 429 and resp.status_code < 500:
            resp.raise_for_status()
            return resp.json()
        if attempt == MAX_RATE_LIMIT_RETRIES:
            resp.raise_for_status()
        retries[0] += 1
        stats["rate_limited" if resp.status_code == 429 else "server_errors"] += 1
        try:
            wait = float(resp.headers.get("retry-after", ""))
        except ValueError:
            wait = 2.0 ** attempt
        wait = min(max(wait, 0.5), MAX_BACKOFF_S)
        stats["backoff_ms"] += round(wait * 1000)
        time.sleep(wait)
    raise AssertionError("unreachable")


def _groq(system: str, user: str, json_mode: bool, retries: list[int]) -> tuple[str, Tokens]:
    body: dict[str, Any] = {
        "model": settings.groq_model,
        "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if settings.groq_model.startswith("openai/gpt-oss") and settings.groq_reasoning_effort:
        body["reasoning_effort"] = settings.groq_reasoning_effort
    data = _post(GROQ_URL, body, {"Authorization": f"Bearer {settings.groq_api_key}"}, retries)
    u = data.get("usage", {})
    tokens = (int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)), int(u.get("total_tokens", 0)))
    return data["choices"][0]["message"]["content"], tokens


def _gemini(system: str, user: str, json_mode: bool, retries: list[int]) -> tuple[str, Tokens]:
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    data = _post(GEMINI_URL.format(model=settings.gemini_model), body, {"x-goog-api-key": settings.gemini_api_key},
                 retries)
    u = data.get("usageMetadata", {})
    prompt, total = int(u.get("promptTokenCount", 0)), int(u.get("totalTokenCount", 0))
    return data["candidates"][0]["content"]["parts"][0]["text"], (prompt, total - prompt, total)


def _describe(exc: Exception) -> str:
    """Short error text, including the provider's own message (e.g. which quota was hit)."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        try:
            message = exc.response.json().get("error", {}).get("message", "")
        except ValueError:
            message = exc.response.text
        # Provider messages can name the account's organization ID; it surfaces in /health and notes.
        message = re.sub(r"\borg_[A-Za-z0-9]+\b", "org_…", str(message))
        return f"HTTP {exc.response.status_code}: {message[:200]}".rstrip(": ")
    return f"{type(exc).__name__}: {str(exc)[:200]}".rstrip(": ")


def complete(system: str, user: str, json_mode: bool = True, purpose: str = "") -> LLMReply:
    """Return the first successful provider reply, or raise ``LLMUnavailable``."""
    providers = []
    if settings.groq_api_key:
        providers.append(("groq", settings.groq_model, _groq))
    if settings.gemini_api_key:
        providers.append(("gemini", settings.gemini_model, _gemini))
    errors = []
    usage = _current_usage.get()
    for name, model, call in providers:
        stats["calls"] += 1
        retries = [0]
        started = time.perf_counter()
        entry: dict[str, Any] = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "provider": name,
                                 "model": model, "purpose": purpose}
        try:
            text, (prompt_t, completion_t, total_t) = call(system, user, json_mode, retries)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            detail = _describe(exc)
            log.warning("LLM provider %s failed (%s): %s", name, purpose or "-", detail)
            stats["failures"] += 1
            errors.append(f"{name}: {detail}")
            last_call.update(provider=name, ok=False, at=entry["at"], error=detail)
            _record({**entry, "ok": False, "error": detail, "rate_limit_retries": retries[0],
                     "latency_ms": round((time.perf_counter() - started) * 1000)})
            continue
        stats["tokens"] += total_t
        if usage is not None:
            usage.tokens += total_t
            usage.calls += 1
            usage.by_purpose[purpose or "other"] += total_t
        last_call.update(provider=name, ok=True, at=entry["at"], error=None)
        _record({**entry, "ok": True, "prompt_tokens": prompt_t, "completion_tokens": completion_t,
                 "total_tokens": total_t, "rate_limit_retries": retries[0],
                 "latency_ms": round((time.perf_counter() - started) * 1000)})
        return LLMReply(text=text, provider=name)
    raise LLMUnavailable("; ".join(errors) or "no LLM provider configured")


def complete_json(system: str, user: str, purpose: str = "") -> tuple[dict[str, Any], str]:
    """Like ``complete`` but parses a JSON object (tolerating code fences)."""
    reply = complete(system, user, json_mode=True, purpose=purpose)
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


def read_log(since: str | None = None) -> list[dict[str, Any]]:
    """Ledger entries, optionally only those at or after an ISO date/time prefix (UTC)."""
    path = Path(settings.llm_log_path)
    if not path.exists():
        return []
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [e for e in entries if since is None or e["at"] >= since]
