"""Thin LLM client: Groq first, Gemini as fallback, ``None`` when neither works.

The LLM is only used to write SQL and to phrase explanations. It never computes
scores or numbers; callers verify everything it returns.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass(frozen=True)
class LLMReply:
    text: str
    provider: str


class LLMUnavailable(RuntimeError):
    pass


def available() -> bool:
    return bool(settings.groq_api_key or settings.gemini_api_key)


def _groq(system: str, user: str, json_mode: bool) -> str:
    body: dict[str, Any] = {
        "model": settings.groq_model,
        "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    resp = httpx.post(GROQ_URL, json=body, timeout=settings.llm_timeout_s,
                      headers={"Authorization": f"Bearer {settings.groq_api_key}"})
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _gemini(system: str, user: str, json_mode: bool) -> str:
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    resp = httpx.post(GEMINI_URL.format(model=settings.gemini_model), json=body, timeout=settings.llm_timeout_s,
                      headers={"x-goog-api-key": settings.gemini_api_key})
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def complete(system: str, user: str, json_mode: bool = True) -> LLMReply:
    """Return the first successful provider reply, or raise ``LLMUnavailable``."""
    providers = []
    if settings.groq_api_key:
        providers.append(("groq", _groq))
    if settings.gemini_api_key:
        providers.append(("gemini", _gemini))
    errors = []
    for name, call in providers:
        try:
            return LLMReply(text=call(system, user, json_mode), provider=name)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            log.warning("LLM provider %s failed: %s", name, exc)
            errors.append(f"{name}: {type(exc).__name__}")
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
