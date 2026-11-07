"""LLM provider abstraction.

Everything else in ASTRA talks to `LLMProvider`, never to the OpenAI SDK directly.
To swap models/providers you either change env vars (any OpenAI-compatible API — OpenRouter,
Groq, Together, Ollama — works through OPENAI_BASE_URL) or add another class implementing
the same five methods and register it in `build_provider`."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from app.core.config import settings


class AIUnavailable(Exception):
    """Raised when no provider/key is configured. The UI shows a setup hint instead of fake output."""


class AIError(Exception):
    pass


@dataclass
class Usage:
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    def stream_chat(self, messages: list[dict], tools: list[dict] | None, model: str, temperature: float) -> AsyncIterator[dict]: ...
    async def complete(self, messages: list[dict], model: str | None = None, json_mode: bool = False, temperature: float = 0.2) -> tuple[str, Usage]: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def transcribe(self, audio: bytes, filename: str, prompt: str = "") -> str: ...
    async def speak(self, text: str, voice: str, speed: float = 1.0, instructions: str = "") -> bytes: ...


def _supports_temperature(model: str) -> bool:
    m = model.lower()
    return not (m.startswith("gpt-5") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4"))


def _wrap_error(e: Exception) -> AIError:
    import openai

    if isinstance(e, openai.AuthenticationError):
        return AIError("The AI provider rejected the API key. Check OPENAI_API_KEY (backend/.env or ASTRA → Integrations).")
    if isinstance(e, openai.RateLimitError):
        return AIError("The AI provider is rate-limiting us (or the account is out of credit). Try again shortly.")
    if isinstance(e, openai.NotFoundError):
        return AIError(f"Model not found or not available on this account: {e}")
    if isinstance(e, openai.APIConnectionError):
        return AIError("Couldn't reach the AI provider. Check your internet connection or OPENAI_BASE_URL.")
    return AIError(f"AI provider error: {e}")


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, base_url: str = ""):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url or None, timeout=120)

    async def stream_chat(self, messages, tools, model, temperature) -> AsyncIterator[dict]:
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "stream": True, "stream_options": {"include_usage": True}}
        if tools:
            kwargs["tools"] = tools
        if _supports_temperature(model):
            kwargs["temperature"] = temperature
        try:
            stream = await self.client.chat.completions.create(**kwargs)
            calls: dict[int, dict] = {}
            async for chunk in stream:
                if chunk.usage:
                    yield {"type": "usage", "usage": Usage(model, chunk.usage.prompt_tokens or 0, chunk.usage.completion_tokens or 0)}
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield {"type": "token", "content": delta.content}
                for tc in delta.tool_calls or []:
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments
            if calls:
                out = []
                for slot in calls.values():
                    try:
                        args = json.loads(slot["args"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    out.append(ToolCall(slot["id"], slot["name"], args))
                yield {"type": "tool_calls", "calls": out}
        except Exception as e:  # noqa: BLE001
            raise _wrap_error(e) from e

    async def complete(self, messages, model=None, json_mode=False, temperature=0.2):
        model = model or settings.FAST_MODEL
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if _supports_temperature(model):
            kwargs["temperature"] = temperature
        try:
            r = await self.client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            raise _wrap_error(e) from e
        u = r.usage
        return r.choices[0].message.content or "", Usage(model, u.prompt_tokens if u else 0, u.completion_tokens if u else 0)

    async def embed(self, texts):
        try:
            r = await self.client.embeddings.create(model=settings.EMBEDDING_MODEL, input=[t[:8000] for t in texts])
        except Exception as e:  # noqa: BLE001
            raise _wrap_error(e) from e
        return [d.embedding for d in r.data]

    async def transcribe(self, audio, filename, prompt=""):
        try:
            r = await self.client.audio.transcriptions.create(model=settings.STT_MODEL, file=(filename, audio), prompt=prompt or None)
        except Exception as e:  # noqa: BLE001
            raise _wrap_error(e) from e
        return r.text

    async def speak(self, text, voice, speed=1.0, instructions=""):
        kwargs: dict[str, Any] = {"model": settings.TTS_MODEL, "voice": voice, "input": text[:4000], "response_format": "mp3"}
        if settings.TTS_MODEL.startswith("gpt-4o") and instructions:
            kwargs["instructions"] = instructions
        if speed and speed != 1.0:
            kwargs["speed"] = speed
        try:
            r = await self.client.audio.speech.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            raise _wrap_error(e) from e
        return r.content


# A hook for tests (and future local providers) to override provider construction.
_override: LLMProvider | None = None


def set_provider_override(p: LLMProvider | None) -> None:
    global _override
    _override = p


def build_provider(api_key: str = "", base_url: str = "") -> LLMProvider:
    if _override is not None:
        return _override
    key = api_key or settings.OPENAI_API_KEY
    if not key:
        raise AIUnavailable("No AI key configured. Add OPENAI_API_KEY to backend/.env or paste a key in ASTRA → Integrations.")
    return OpenAIProvider(key, base_url or settings.OPENAI_BASE_URL)


async def get_provider(db, user_id: str) -> LLMProvider:
    """User-supplied key (stored encrypted) wins over the server key."""
    if _override is not None:
        return _override
    from app.services.integrations_store import get_secret

    secret = await get_secret(db, user_id, "openai")
    if secret and secret.get("api_key"):
        return build_provider(secret["api_key"], secret.get("base_url", ""))
    return build_provider()


async def ai_configured(db, user_id: str) -> bool:
    try:
        await get_provider(db, user_id)
        return True
    except AIUnavailable:
        return False
