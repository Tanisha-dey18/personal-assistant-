"""Onboarding importers: ChatGPT data export (conversations.json or the whole .zip),
free text ("about me", notes) and a structured onboarding form."""
from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime, timezone

from app.ai.provider import get_provider
from app.core.db import SessionLocal
from app.memory import store
from app.memory.extractor import extract_and_store
from app.models import Conversation, ImportJob, Message, User
from app.services import conversations as convs

log = logging.getLogger("astra.import")


def parse_chatgpt_export(data: bytes) -> list[dict]:
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next((n for n in z.namelist() if n.endswith("conversations.json")), None)
            if not name:
                raise ValueError("No conversations.json inside the zip")
            data = z.read(name)
    raw = json.loads(data.decode("utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Unexpected format: expected a list of conversations")
    out = []
    for c in raw:
        mapping = c.get("mapping") or {}
        node_id = c.get("current_node")
        chain = []
        seen = set()
        while node_id and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            node = mapping[node_id]
            msg = node.get("message")
            if msg:
                role = (msg.get("author") or {}).get("role")
                parts = (msg.get("content") or {}).get("parts") or []
                text = "\n".join(p for p in parts if isinstance(p, str)).strip()
                if role in ("user", "assistant") and text:
                    chain.append({"role": role, "text": text, "time": msg.get("create_time")})
            node_id = node.get("parent")
        chain.reverse()
        if chain:
            out.append({"title": c.get("title") or "Imported chat", "create_time": c.get("create_time"),
                        "update_time": c.get("update_time"), "messages": chain})
    out.sort(key=lambda x: x.get("update_time") or x.get("create_time") or 0, reverse=True)
    return out


def _ts(t) -> datetime:
    try:
        return datetime.fromtimestamp(float(t), tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


async def run_chatgpt_import(job_id: str, user_id: str, conversations: list[dict], extract: bool) -> None:
    async with SessionLocal() as db:
        job = await db.get(ImportJob, job_id)
        try:
            user = await db.get(User, user_id)
            provider = await get_provider(db, user_id)
            job.status, job.total = "running", len(conversations)
            await db.commit()
            totals = {"conversations": 0, "messages": 0, "created": 0, "updated": 0, "pending": 0, "questions": []}
            for c in conversations:
                conv = Conversation(user_id=user_id, title=c["title"][:200], source="chatgpt", created_at=_ts(c["create_time"]),
                                    updated_at=_ts(c.get("update_time") or c["create_time"]))
                db.add(conv)
                await db.flush()
                for m in c["messages"]:
                    db.add(Message(conversation_id=conv.id, user_id=user_id, role=m["role"], content=m["text"][:8000],
                                   created_at=_ts(m.get("time") or c["create_time"]), meta={"imported": "chatgpt"}))
                await db.commit()
                totals["conversations"] += 1
                totals["messages"] += len(c["messages"])
                try:
                    if extract:
                        user_text = "\n---\n".join(m["text"][:1500] for m in c["messages"] if m["role"] == "user")[:6000]
                        r = await extract_and_store(db, provider, user, user_text, kind="conversation", source="import",
                                                    source_ref=f"chatgpt: {c['title'][:150]}")
                        for k in ("created", "updated", "pending"):
                            totals[k] += len(r[k])
                        totals["questions"] += r["questions"]
                    await convs.maybe_summarize(db, provider, user, conv, force=True)
                except Exception:  # noqa: BLE001 — keep going on per-conversation failures
                    log.exception("failed processing imported conversation")
                    await db.rollback()
                job = await db.get(ImportJob, job_id)
                job.progress += 1
                job.result = {**totals}
                await db.commit()
            job.status = "done"
            await db.commit()
        except Exception as e:  # noqa: BLE001
            log.exception("chatgpt import failed")
            await db.rollback()
            job = await db.get(ImportJob, job_id)
            job.status, job.error = "failed", str(e)[:500]
            await db.commit()


async def run_text_import(job_id: str, user_id: str, text: str, label: str) -> None:
    async with SessionLocal() as db:
        job = await db.get(ImportJob, job_id)
        try:
            user = await db.get(User, user_id)
            provider = await get_provider(db, user_id)
            windows = [text[i:i + 6000] for i in range(0, min(len(text), 60000), 6000)]
            job.status, job.total = "running", len(windows)
            await db.commit()
            totals = {"created": 0, "updated": 0, "pending": 0, "questions": []}
            for w in windows:
                r = await extract_and_store(db, provider, user, w, kind="document", source="manual", source_ref=label)
                for k in ("created", "updated", "pending"):
                    totals[k] += len(r[k])
                totals["questions"] += r["questions"]
                job.progress += 1
                job.result = {**totals}
                await db.commit()
            job.status = "done"
            await db.commit()
        except Exception as e:  # noqa: BLE001
            log.exception("text import failed")
            await db.rollback()
            job = await db.get(ImportJob, job_id)
            job.status, job.error = "failed", str(e)[:500]
            await db.commit()


ONBOARDING_FIELDS = {
    # field: (template, category, importance)
    "name": ("The user's name is {}.", "personal", 1.0),
    "location": ("The user lives in {}.", "personal", 0.7),
    "education": ("Education: {}.", "education", 0.95),
    "current_focus": ("The user is currently focused on: {}.", "goals", 0.85),
    "skills": ("The user's skills include: {}.", "skills", 0.75),
    "interests": ("The user is interested in: {}.", "preferences", 0.6),
    "career_goals": ("The user's career goals: {}.", "career", 0.95),
    "projects": ("Projects the user has built or is building: {}.", "projects", 0.8),
    "learning_style": ("The user prefers to learn like this: {}.", "learning", 0.7),
    "about": ("About the user: {}.", "personal", 0.7),
}


async def apply_onboarding(db, provider, user: User, data: dict) -> list[dict]:
    """Structured answers become confirmed memories directly (the user typed them, so no guessing)."""
    created = []
    for key, (tpl, cat, imp) in ONBOARDING_FIELDS.items():
        val = (data.get(key) or "").strip()
        if not val:
            continue
        m, _ = await store.create_memory(db, provider, user.id, tpl.format(val.rstrip(".")), cat, "confirmed", imp, source="manual",
                                         source_ref="onboarding")
        created.append(store.to_dict(m))
    if data.get("name"):
        user.name = data["name"].strip()[:120]
    user.onboarded = True
    await db.commit()
    return created
