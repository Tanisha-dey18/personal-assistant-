"""Conversation helpers: history window, rolling summaries (also indexed for semantic
recall of past conversations) and auto titles."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory import store
from app.memory.vectors import CONVERSATIONS, vectors
from app.models import Conversation, Message
from app.services.usage import log_usage

HISTORY_WINDOW = 24
SUMMARY_EVERY = 8


def msg_dict(m: Message) -> dict:
    return {"id": m.id, "conversation_id": m.conversation_id, "role": m.role, "content": m.content, "mode": m.mode,
            "meta": m.meta or {}, "created_at": m.created_at.isoformat() if m.created_at else None}


def conv_dict(c: Conversation, last: str | None = None) -> dict:
    return {"id": c.id, "title": c.title, "mode": c.mode, "summary": c.summary, "source": c.source, "pinned": c.pinned,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None, "preview": last}


async def get_owned(db: AsyncSession, user_id: str, conv_id: str) -> Conversation | None:
    c = await db.get(Conversation, conv_id)
    return c if c and c.user_id == user_id else None


async def history(db: AsyncSession, conv_id: str, limit: int = HISTORY_WINDOW) -> list[Message]:
    rows = (await db.execute(select(Message).where(Message.conversation_id == conv_id, Message.role.in_(("user", "assistant")))
                             .order_by(Message.created_at.desc()).limit(limit))).scalars().all()
    return list(reversed(rows))


async def message_count(db: AsyncSession, conv_id: str) -> int:
    return (await db.execute(select(func.count()).select_from(Message).where(Message.conversation_id == conv_id))).scalar_one()


async def maybe_summarize(db: AsyncSession, provider, user, conv: Conversation, force: bool = False) -> bool:
    n = await message_count(db, conv.id)
    if n < 4 or (not force and n - conv.summarized_count < SUMMARY_EVERY and conv.summary):
        return False
    msgs = await history(db, conv.id, limit=40)
    transcript = "\n".join(f"{m.role.upper()}: {m.content[:1200]}" for m in msgs)[-14000:]
    prompt = [
        {"role": "system", "content": "Summarise this conversation between the user and their AI companion ASTRA for long-term recall. "
                                      "Max 180 words. Capture: topics, facts about the user, decisions made, advice given, "
                                      "and any unfinished tasks or open questions. Plain prose, no preamble."},
        {"role": "user", "content": (f"Previous summary:\n{conv.summary}\n\n" if conv.summary else "") + f"Conversation:\n{transcript}"},
    ]
    text, usage = await provider.complete(prompt)
    log_usage(db, user.id, "summary", usage)
    conv.summary = text.strip()
    conv.summarized_count = n
    await db.commit()
    vec = await store.embed_one(provider, f"{conv.title}\n{conv.summary}")
    await vectors.upsert(CONVERSATIONS, conv.id, vec, {"user_id": user.id, "conversation_id": conv.id})
    return True


async def maybe_title(db: AsyncSession, provider, user, conv: Conversation, first_message: str) -> str | None:
    if conv.title != "New conversation":
        return None
    text, usage = await provider.complete([
        {"role": "system", "content": "Write a 2-6 word title for a chat that starts with this message. No quotes, no trailing punctuation."},
        {"role": "user", "content": first_message[:1000]}])
    log_usage(db, user.id, "title", usage)
    conv.title = text.strip().strip('"')[:120] or "Conversation"
    await db.commit()
    return conv.title
