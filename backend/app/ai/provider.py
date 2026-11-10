"""LLM provider abstraction.

Everything else in JARVIS talks to `LLMProvider`, never to the OpenAI SDK directly.
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
    extra: dict = field(default_factory=dict)  # provider data to echo back, e.g. Gemini's thought_signature


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

    if isinstance(e, AIError):
        return e
    if isinstance(e, openai.AuthenticationError):
        err = AIError("The AI provider rejected the API key. Check OPENAI_API_KEY (backend/.env or JARVIS → Integrations).")
    elif isinstance(e, openai.RateLimitError):
        err = AIError("The AI provider is rate-limiting us (free-tier limit or out of credit). Try again in a minute.")
    elif isinstance(e, openai.NotFoundError):
        err = AIError(f"Model not found or not available on this account: {e}")
    elif isinstance(e, openai.APIConnectionError):
        err = AIError("Couldn't reach the AI provider. Check your internet connection or OPENAI_BASE_URL.")
    elif isinstance(e, openai.APIStatusError) and e.status_code >= 500:
        err = AIError("The AI provider is overloaded right now. Try again in a moment.")
    else:
        err = AIError(f"AI provider error: {e}")
    err.status = getattr(e, "status_code", None)
    return err


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, base_url: str = ""):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url or None, timeout=120)

    async def stream_chat(self, messages, tools, model, temperature) -> AsyncIterator[dict]:
        """Streams the reply. If the chosen model is overloaded/rate-limited before anything was
        streamed (common on free tiers), retries once on FAST_MODEL."""
        started = False
        try:
            async for ev in self._stream(messages, tools, model, temperature):
                started = True
                yield ev
        except AIError as e:
            if started or model == settings.FAST_MODEL or getattr(e, "status", None) not in (429, 500, 502, 503, 504):
                raise
            async for ev in self._stream(messages, tools, settings.FAST_MODEL, temperature):
                yield ev

    async def _stream(self, messages, tools, model, temperature) -> AsyncIterator[dict]:
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
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": "", "extra": {}})
                    for k, v in (getattr(tc, "model_extra", None) or {}).items():
                        if v is not None:
                            slot["extra"][k] = v
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
                    out.append(ToolCall(slot["id"], slot["name"], args, slot["extra"]))
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
        try:  # fixed dimensions keep the Qdrant collections compatible across embedding models
            out = []
            for i in range(0, len(texts), 100):  # Gemini caps a batch at 100 inputs
                r = await self.client.embeddings.create(model=settings.EMBEDDING_MODEL, input=[t[:8000] for t in texts[i:i + 100]],
                                                        dimensions=settings.EMBEDDING_DIM)
                out += [d.embedding for d in r.data]
        except Exception as e:  # noqa: BLE001
            raise _wrap_error(e) from e
        return out

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


class GeminiProvider(OpenAIProvider):
    """Google Gemini through its OpenAI-compatible endpoint (free tier available).
    Chat, tools, JSON mode and embeddings use the shared code; speech-to-text uses Gemini's
    native audio understanding; text-to-speech is left to the browser's built-in voice."""

    name = "gemini"

    def __init__(self, api_key: str, base_url: str):
        super().__init__(api_key, base_url)
        self.api_key = api_key

    async def transcribe(self, audio, filename, prompt=""):
        import base64

        import httpx

        ext = filename.rsplit(".", 1)[-1].lower()
        mime = {"webm": "audio/webm", "ogg": "audio/ogg", "m4a": "audio/mp4", "mp4": "audio/mp4", "wav": "audio/wav", "mp3": "audio/mp3"}.get(ext, "audio/webm")
        body = {"contents": [{"parts": [
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}},
            {"text": "Transcribe this speech verbatim. The speaker may mix Hindi and English (Hinglish); write Hindi words "
                     "in Latin script. Output only the transcript, or nothing if there is no speech."}]}]}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.FAST_MODEL}:generateContent"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, json=body, headers={"x-goog-api-key": self.api_key})
        if r.status_code != 200:
            raise AIError(f"Gemini transcription failed ({r.status_code}).")
        parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip()

    async def speak(self, text, voice, speed=1.0, instructions=""):
        raise AIError("Server voice isn't available with Gemini — using the browser's voice instead.")


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
        raise AIUnavailable("No AI key configured. Add OPENAI_API_KEY to backend/.env or paste a key in JARVIS → Integrations.")
    base = base_url or settings.OPENAI_BASE_URL
    if "generativelanguage.googleapis.com" in base:
        return GeminiProvider(key, base)
    return OpenAIProvider(key, base)


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
