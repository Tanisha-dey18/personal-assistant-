"""Selects ONLY the relevant slice of the user's memory for each turn.

Ranking = 0.70 * semantic similarity + 0.20 * importance + 0.10 * recency.
Plus: a few always-on "core identity" memories, 1-hop knowledge-graph facts, relevant
older conversations, relevant document chunks, and open tasks/reminders."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory import graph, store
from app.memory.vectors import CONVERSATIONS, DOCUMENTS, vectors
from app.models import Conversation, Document, DocumentChunk, Memory, Project, Reminder, Task
from app.services.user_settings import get_user_settings

CORE_CATEGORIES = ("personal", "education", "career", "goals")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _recency(dt: datetime | None) -> float:
    dt = _aware(dt)
    if not dt:
        return 0.0
    days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    return math.exp(-days / 90)


def _fmt_mem(m: Memory) -> str:
    tag = "" if m.memory_type == "confirmed" else f" ({m.memory_type})"
    date = f" [{m.event_date}]" if m.event_date else ""
    return f"- [{m.category}]{date} {store.text_of(m)}{tag}"


async def build_context(db: AsyncSession, provider, user, query: str, conversation_id: str | None) -> dict:
    prefs = get_user_settings(user)
    limit = int(prefs["memory"].get("max_context_memories", 12))
    vec = await store.embed_one(provider, query[:4000])

    hits = await store.semantic_search(db, provider, user.id, query, limit=limit * 2, vector=vec, min_score=0.22)
    ranked = sorted(hits, key=lambda h: 0.7 * h[1] + 0.2 * h[0].importance + 0.1 * _recency(h[0].updated_at), reverse=True)[:limit]
    used_ids = {m.id for m, _ in ranked}

    core_rows = (await db.execute(
        select(Memory).where(Memory.user_id == user.id, Memory.status == "active", Memory.importance >= 0.75,
                             Memory.category.in_(CORE_CATEGORIES))
        .order_by(Memory.importance.desc(), Memory.updated_at.desc()).limit(8)
    )).scalars().all()
    core = [m for m in core_rows if m.id not in used_ids]

    now = datetime.now(timezone.utc)
    for m, _ in ranked:
        m.access_count = (m.access_count or 0) + 1
        m.last_accessed = now

    graph_lines = await graph.context_lines(db, user.id, query, list(used_ids))

    # Older conversations that are relevant (their summaries are embedded when summarised)
    past = []
    for cid, score, _ in await vectors.search(CONVERSATIONS, vec, user.id, limit=4):
        if cid == conversation_id or score < 0.3:
            continue
        c = await db.get(Conversation, cid)
        if c and c.user_id == user.id and c.summary:
            past.append({"id": c.id, "title": c.title, "summary": c.summary[:600], "date": c.updated_at.date().isoformat(), "score": score})
    past = past[:3]

    docs = []
    for chunk_id, score, payload in await vectors.search(DOCUMENTS, vec, user.id, limit=4):
        if score < 0.35:
            continue
        ch = await db.get(DocumentChunk, chunk_id)
        if ch and ch.user_id == user.id:
            d = await db.get(Document, ch.document_id)
            docs.append({"filename": d.filename if d else "document", "content": ch.content[:1200], "score": score})

    tasks = (await db.execute(select(Task).where(Task.user_id == user.id, Task.status != "done")
                              .order_by(Task.due_at.is_(None), Task.due_at).limit(8))).scalars().all()
    reminders = (await db.execute(select(Reminder).where(Reminder.user_id == user.id, Reminder.done.is_(False))
                                  .order_by(Reminder.remind_at).limit(5))).scalars().all()
    projects = (await db.execute(select(Project).where(Project.user_id == user.id, Project.status.in_(("active", "paused")))
                                 .order_by(Project.updated_at.desc()).limit(6))).scalars().all()
    await db.commit()

    parts = []
    if core:
        parts.append("CORE FACTS ABOUT THE USER:\n" + "\n".join(_fmt_mem(m) for m in core))
    if ranked:
        parts.append("RELEVANT MEMORIES:\n" + "\n".join(_fmt_mem(m) for m, _ in ranked))
    if graph_lines:
        parts.append("KNOWLEDGE GRAPH LINKS:\n" + "\n".join(f"- {line}" for line in graph_lines))
    if past:
        parts.append("RELEVANT PAST CONVERSATIONS:\n" + "\n".join(f"- ({p['date']}) {p['title']}: {p['summary']}" for p in past))
    if docs:
        parts.append("RELEVANT DOCUMENT EXCERPTS:\n" + "\n".join(f"- from {d['filename']}: {d['content']}" for d in docs))
    if tasks:
        parts.append("OPEN TASKS:\n" + "\n".join(
            f"- [{t.priority}] {t.title}" + (f" (due {_aware(t.due_at).strftime('%Y-%m-%d %H:%M')} UTC)" if t.due_at else "") + f" id={t.id}"
            for t in tasks))
    if reminders:
        parts.append("UPCOMING REMINDERS:\n" + "\n".join(f"- {r.text} at {_aware(r.remind_at).strftime('%Y-%m-%d %H:%M')} UTC" for r in reminders))
    if projects:
        parts.append("ACTIVE PROJECTS:\n" + "\n".join(
            f"- {p.name} ({p.status}, {p.progress}%): {', '.join(p.tech_stack or [])} — last updated {_aware(p.updated_at).date()}" for p in projects))

    return {
        "text": "\n\n".join(parts) if parts else "(No stored memories yet — you are just getting to know the user.)",
        "memories_used": [store.to_dict(m, s) for m, s in ranked] + [store.to_dict(m) for m in core],
        "past_conversations": past,
        "documents": [{"filename": d["filename"], "score": round(d["score"], 3)} for d in docs],
    }
