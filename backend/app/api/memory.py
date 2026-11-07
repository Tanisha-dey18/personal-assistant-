"""Memory management: browse, search, edit, approve, delete, graph, timeline, profile."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import AIError, AIUnavailable, get_provider
from app.core.db import get_db
from app.core.deps import get_current_user, rate_limited_user
from app.memory import graph, store
from app.models import Entity, Memory, Relation, User
from app.services import profile

router = APIRouter(prefix="/api/memory", tags=["memory"])

MemType = Literal["confirmed", "assumption", "temporary"]


async def _provider(db, user):
    try:
        return await get_provider(db, user.id)
    except AIUnavailable as e:
        raise HTTPException(503, str(e)) from e


@router.get("")
async def list_memories(category: str | None = None, status: str | None = "active", memory_type: str | None = None,
                        q: str | None = None, limit: int = 100, offset: int = 0,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows, total = await store.list_memories(db, user.id, category, status or None, memory_type, q, min(limit, 500), offset)
    counts = dict((await db.execute(select(Memory.category, func.count()).where(Memory.user_id == user.id, Memory.status == "active")
                                    .group_by(Memory.category))).all())
    return {"items": [store.to_dict(m) for m in rows], "total": total, "categories": counts}


@router.get("/search")
async def search(q: str, limit: int = 10, user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    provider = await _provider(db, user)
    try:
        hits = await store.semantic_search(db, provider, user.id, q, limit=min(limit, 30), min_score=0.15)
    except AIError as e:
        raise HTTPException(502, str(e)) from e
    return {"items": [store.to_dict(m, s) for m, s in hits]}


class MemoryIn(BaseModel):
    content: str = Field(min_length=2, max_length=2000)
    category: str = "other"
    memory_type: MemType = "confirmed"
    importance: float = Field(default=0.6, ge=0, le=1)
    sensitive: bool = False
    event_date: str | None = None


@router.post("")
async def create(body: MemoryIn, user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    provider = await _provider(db, user)
    m, created = await store.create_memory(db, provider, user.id, body.content, body.category, body.memory_type, body.importance,
                                           body.sensitive, source="manual", event_date=body.event_date)
    return {"memory": store.to_dict(m), "created": created}


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, max_length=2000)
    category: str | None = None
    memory_type: MemType | None = None
    importance: float | None = Field(default=None, ge=0, le=1)
    sensitive: bool | None = None
    status: Literal["active", "pending", "archived"] | None = None
    event_date: str | None = None


@router.patch("/{mid}")
async def patch(mid: str, body: MemoryPatch, user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    m = await store.get_user_memory(db, user.id, mid)
    if not m:
        raise HTTPException(404, "Memory not found")
    provider = await _provider(db, user) if body.content else None
    m = await store.update_memory(db, provider, m, **body.model_dump(exclude_unset=True))
    return store.to_dict(m)


@router.post("/{mid}/approve")
async def approve(mid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    m = await store.get_user_memory(db, user.id, mid)
    if not m:
        raise HTTPException(404, "Memory not found")
    return store.to_dict(await store.update_memory(db, None, m, status="active"))


@router.post("/{mid}/confirm")
async def confirm(mid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Mark an assumption as confirmed."""
    m = await store.get_user_memory(db, user.id, mid)
    if not m:
        raise HTTPException(404, "Memory not found")
    return store.to_dict(await store.update_memory(db, None, m, memory_type="confirmed"))


@router.delete("/{mid}")
async def remove(mid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    m = await store.get_user_memory(db, user.id, mid)
    if not m:
        raise HTTPException(404, "Memory not found")
    await store.delete_memory(db, m)
    return {"deleted": True}


@router.get("/graph/data")
async def graph_data(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await graph.full_graph(db, user.id)


@router.get("/graph/entity/{eid}")
async def entity_detail(eid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    e = await db.get(Entity, eid)
    if not e or e.user_id != user.id:
        raise HTTPException(404, "Entity not found")
    from app.models import MemoryEntity

    mids = (await db.execute(select(MemoryEntity.memory_id).where(MemoryEntity.entity_id == eid))).scalars().all()
    mems = (await db.execute(select(Memory).where(Memory.id.in_(mids), Memory.user_id == user.id))).scalars().all() if mids else []
    return {"entity": {"id": e.id, "name": e.name, "type": e.type, "description": e.description},
            "memories": [store.to_dict(m) for m in mems]}


@router.delete("/graph/entity/{eid}")
async def delete_entity(eid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    e = await db.get(Entity, eid)
    if not e or e.user_id != user.id:
        raise HTTPException(404, "Entity not found")
    await db.execute(delete(Relation).where((Relation.source_id == eid) | (Relation.target_id == eid)))
    await db.delete(e)
    await db.commit()
    return {"deleted": True}


@router.get("/timeline/items")
async def get_timeline(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {"items": await profile.timeline(db, user.id)}


@router.get("/profile/knowledge")
async def knowledge(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await profile.knowledge(db, user.id)


@router.post("/profile/synthesize")
async def synthesize(user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    provider = await _provider(db, user)
    try:
        return {"portrait": await profile.synthesize(db, provider, user)}
    except AIError as e:
        raise HTTPException(502, str(e)) from e
