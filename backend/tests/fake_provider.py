"""Deterministic stand-in for the LLM so the full pipeline can be tested offline.
It is ONLY used by tests — the real app never falls back to fake responses."""
import hashlib
import json
import math
import re

from app.ai.provider import ToolCall, Usage
from app.core.config import settings


def _vec(text: str) -> list[float]:
    v = [0.0] * settings.EMBEDDING_DIM
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % len(v)] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class FakeProvider:
    name = "fake"

    async def embed(self, texts):
        return [_vec(t) for t in texts]

    async def complete(self, messages, model=None, json_mode=False, temperature=0.2):
        system = messages[0]["content"]
        body = messages[-1]["content"]
        if "memory curator" in system:
            mems = []
            m = re.search(r"I study ([^.\n]+)", body)
            if m:
                mems.append({"action": "create", "content": f"The user studies {m.group(1).strip()}.", "category": "education",
                             "memory_type": "confirmed", "importance": 0.9, "sensitive": False,
                             "entities": [{"name": "Me", "type": "self"}, {"name": m.group(1).strip(), "type": "course"}],
                             "relations": [{"source": "Me", "relation": "studies", "target": m.group(1).strip()}]})
            if "anxiety" in body:
                mems.append({"action": "create", "content": "The user has been dealing with exam anxiety.", "category": "health",
                             "memory_type": "confirmed", "importance": 0.6, "sensitive": True, "entities": [], "relations": []})
            m = re.search(r"I built ([A-Za-z]+) with ([A-Za-z]+)", body)
            if m:
                mems.append({"action": "create", "content": f"The user built {m.group(1)} using {m.group(2)}.", "category": "projects",
                             "memory_type": "confirmed", "importance": 0.8, "sensitive": False,
                             "entities": [{"name": m.group(1), "type": "project"}, {"name": m.group(2), "type": "technology"}],
                             "relations": [{"source": "Me", "relation": "built", "target": m.group(1)},
                                           {"source": m.group(1), "relation": "uses", "target": m.group(2)}]})
            return json.dumps({"memories": mems, "questions": []}), Usage("fake", 10, 10)
        if "title" in system.lower():
            return "Test Conversation", Usage("fake", 5, 3)
        return "A short summary.", Usage("fake", 5, 5)

    async def stream_chat(self, messages, tools, model, temperature):
        last = messages[-1]
        if last["role"] == "tool":
            yield {"type": "token", "content": "Done with the tool. "}
            yield {"type": "token", "content": "Anything else?"}
            yield {"type": "usage", "usage": Usage("fake", 20, 5)}
            return
        text = last["content"].lower()
        if "remind me" in text and tools:
            yield {"type": "tool_calls", "calls": [ToolCall("call_1", "create_reminder", {"text": "drink water", "remind_at": "2030-01-01T09:00"})]}
            return
        if "send an email" in text and tools:
            yield {"type": "tool_calls", "calls": [ToolCall("call_2", "gmail_send", {"to": "a@b.com", "subject": "Hi", "body": "Hello"})]}
            return
        # Echo the system context so tests can verify memory retrieval
        system = messages[0]["content"]
        knows = "KNOWS_STUDY" if "studies" in system else "NO_STUDY"
        for piece in ["Hey ", "there! ", knows]:
            yield {"type": "token", "content": piece}
        yield {"type": "usage", "usage": Usage("fake", 30, 3)}

    async def transcribe(self, audio, filename, prompt=""):
        return "hello astra"

    async def speak(self, text, voice, speed=1.0, instructions=""):
        return b"ID3fake-mp3"
