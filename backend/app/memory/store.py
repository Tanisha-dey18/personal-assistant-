"""Memory CRUD: Postgres row + Qdrant vector kept in sync, with duplicate detection
and transparent encryption of sensitive memories."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt, encrypt
from app.memory.vectors import MEMORIES, vectors
from app.models import Memory, MemoryEntity

CATEGORIES = [
    "personal", "education", "career", "skills", "learning", "projects", "internships", "achievements",
    "hackathons", "people", "preferences", "goals", "routines", "decisions", "challenges", "health", "other",
]
DUPLICATE_THRESHOLD = 0.92


def norm_category(c: str | None) -> str:
    c = (c or "other").strip().lower()
    return c if c in CATEGORIES else "other"


def text_of(m: Memory) -> str:
    return decrypt(m.content) if m.sensitive else m.content


def to_dict(m: Memory, score: float | None = None) -> dict:
    d = {
        "id": m.id, "content": text_of(m), "category": m.category, "memory_type": m.memory_type,
        "status": m.status, "importance": round(m.importance, 2), "sensitive": m.sensitive, "source": m.source,
        "source_ref": m.source_ref, "event_date": m.event_date,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "access_count": m.access_count,
    }
    if score is not None:
        d["score"] = round(score, 3)
    return d


def _payload(m: Memory) -> dict:
    return {"user_id": m.user_id, "memory_id": m.id, "category": m.category, "status": m.status}


async def embed_one(provider, text: str) -> list[float]:
    return (await provider.embed([text]))[0]


async def find_duplicate(provider, user_id: str, vector: list[float], db: AsyncSession) -> tuple[Memory | None, float]:
    hits = await vectors.search(MEMORIES, vector, user_id, limit=1)
    if not hits:
        return None, 0.0
    mid, score, _ = hits[0]
    if score < DUPLICATE_THRESHOLD:
        return None, score
    m = await db.get(Memory, mid)
    if not m or m.user_id != user_id:
        return None, score
    return m, score


async def create_memory(
    db: AsyncSession, provider, user_id: str, content: str, category: str = "other", memory_type: str = "confirmed",
    importance: float = 0.5, sensitive: bool = False, source: str = "chat", source_ref: str | None = None,
    event_date: str | None = None, expires_at: datetime | None = None, status: str = "active", dedupe: bool = True,
    vector: list[float] | None = None,
) -> tuple[Memory, bool]:
    """Returns (memory, created). If a near-identical memory exists it is refreshed instead."""
    content = content.strip()
    vector = vector or await embed_one(provider, content)
    if dedupe:
        dup, _ = await find_duplicate(provider, user_id, vector, db)
        if dup:
            dup.importance = max(dup.importance, importance)
            # Prefer the newer phrasing, and upgrade assumption -> confirmed when re-stated.
            if not dup.sensitive:
                dup.content = content
            if memory_type == "confirmed":
                dup.memory_type = "confirmed"
            dup.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await vectors.upsert(MEMORIES, dup.id, vector, _payload(dup))
            return dup, False
    m = Memory(
        user_id=user_id, content=encrypt(content) if sensitive else content, category=norm_category(category),
        memory_type=memory_type if memory_type in ("confirmed", "assumption", "temporary") else "confirmed",
        importance=max(0.0, min(1.0, float(importance))), sensitive=sensitive, source=source, source_ref=source_ref,
        event_date=event_date, expires_at=expires_at, status=status,
    )
    db.add(m)
    await db.commit()
    await vectors.upsert(MEMORIES, m.id, vector, _payload(m))
    return m, True


async def update_memory(db: AsyncSession, provider, m: Memory, **fields) -> Memory:
    new_content = fields.pop("content", None)
    sensitive = fields.pop("sensitive", None)
    current_text = text_of(m)
    if sensitive is not None:
        m.sensitive = bool(sensitive)
    text = new_content.strip() if new_content else current_text
    m.content = encrypt(text) if m.sensitive else text
    for k, v in fields.items():
        if v is None:
            continue
        if k == "category":
            v = norm_category(v)
        setattr(m, k, v)
    m.updated_at = datetime.now(timezone.utc)
    await db.commit()
    if new_content and new_content.strip() != current_text:
        vec = await embed_one(provider, text)
        await vectors.upsert(MEMORIES, m.id, vec, _payload(m))
    else:
        await vectors.client.set_payload(MEMORIES, payload=_payload(m), points=[m.id])
    return m


async def delete_memory(db: AsyncSession, m: Memory) -> None:
    await vectors.delete(MEMORIES, [m.id])
    await db.execute(sql_delete(MemoryEntity).where(MemoryEntity.memory_id == m.id))
    await db.delete(m)
    await db.commit()


async def get_user_memory(db: AsyncSession, user_id: str, memory_id: str) -> Memory | None:
    m = await db.get(Memory, memory_id)
    return m if m and m.user_id == user_id else None


async def list_memories(db: AsyncSession, user_id: str, category: str | None = None, status: str | None = None,
                        memory_type: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0) -> tuple[list[Memory], int]:
    stmt = select(Memory).where(Memory.user_id == user_id)
    if category:
        stmt = stmt.where(Memory.category == category)
    if status:
        stmt = stmt.where(Memory.status == status)
    if memory_type:
        stmt = stmt.where(Memory.memory_type == memory_type)
    stmt = stmt.order_by(Memory.importance.desc(), Memory.updated_at.desc())
    if q:  # keyword filter in Python because sensitive rows are encrypted
        rows = (await db.execute(stmt)).scalars().all()
        ql = q.lower()
        rows = [m for m in rows if ql in text_of(m).lower()]
        return rows[offset: offset + limit], len(rows)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return list(rows), total


async def semantic_search(db: AsyncSession, provider, user_id: str, query: str, limit: int = 10,
                          vector: list[float] | None = None, min_score: float = 0.2) -> list[tuple[Memory, float]]:
    vector = vector or await embed_one(provider, query)
    hits = await vectors.search(MEMORIES, vector, user_id, limit=limit * 2, must={"status": "active"})
    out = []
    now = datetime.now(timezone.utc)
    for mid, score, _ in hits:
        if score < min_score:
            continue
        m = await db.get(Memory, mid)
        if not m or m.user_id != user_id or m.status != "active":
            continue
        exp = m.expires_at
        if exp and (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)) < now:
            continue
        out.append((m, score))
    return out[:limit]
