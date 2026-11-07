"""Personal knowledge graph: entities (people, events, projects, technologies, skills, goals,
achievements...) and typed relations between them, each linked to the memory it came from."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity, MemoryEntity, Relation

ENTITY_TYPES = {"self", "person", "event", "project", "technology", "skill", "goal", "achievement",
                "organization", "place", "concept", "course", "other"}
SELF_ALIASES = {"i", "me", "user", "myself", "the user", "self", "owner"}
SELF_NAME = "Me"


def _key(name: str) -> str:
    return " ".join(name.lower().split())[:200]


async def upsert_entity(db: AsyncSession, user_id: str, name: str, etype: str = "other", description: str = "") -> Entity | None:
    name = (name or "").strip()
    if not name:
        return None
    if _key(name) in SELF_ALIASES:
        name, etype = SELF_NAME, "self"
    etype = etype.lower() if etype and etype.lower() in ENTITY_TYPES else "other"
    key = _key(name)
    r = await db.execute(select(Entity).where(Entity.user_id == user_id, Entity.name_key == key))
    ent = r.scalar_one_or_none()
    if ent:
        if ent.type == "other" and etype != "other":
            ent.type = etype
        if description and not ent.description:
            ent.description = description
        return ent
    ent = Entity(user_id=user_id, name=name[:200], name_key=key, type=etype, description=description)
    db.add(ent)
    await db.flush()
    return ent


async def link_memory(db: AsyncSession, memory_id: str, entity: Entity) -> None:
    exists = await db.get(MemoryEntity, (memory_id, entity.id))
    if not exists:
        db.add(MemoryEntity(memory_id=memory_id, entity_id=entity.id))


async def add_relation(db: AsyncSession, user_id: str, src: Entity, relation: str, dst: Entity, memory_id: str | None) -> None:
    relation = (relation or "related_to").strip().lower().replace(" ", "_")[:80]
    r = await db.execute(select(Relation).where(
        Relation.user_id == user_id, Relation.source_id == src.id, Relation.target_id == dst.id, Relation.relation == relation))
    if r.scalar_one_or_none():
        return
    db.add(Relation(user_id=user_id, source_id=src.id, target_id=dst.id, relation=relation, memory_id=memory_id))


async def apply_graph(db: AsyncSession, user_id: str, memory_id: str, entities: list[dict], relations: list[dict]) -> None:
    """Called by the extractor with LLM-proposed entities/relations for one memory."""
    by_name: dict[str, Entity] = {}
    for e in entities or []:
        ent = await upsert_entity(db, user_id, e.get("name", ""), e.get("type", "other"))
        if ent:
            by_name[_key(e.get("name", ""))] = ent
            await link_memory(db, memory_id, ent)
    for rel in relations or []:
        s, t = rel.get("source", ""), rel.get("target", "")
        src = by_name.get(_key(s)) or await upsert_entity(db, user_id, s)
        dst = by_name.get(_key(t)) or await upsert_entity(db, user_id, t)
        if src and dst and src.id != dst.id:
            await add_relation(db, user_id, src, rel.get("relation", "related_to"), dst, memory_id)


async def full_graph(db: AsyncSession, user_id: str) -> dict:
    ents = (await db.execute(select(Entity).where(Entity.user_id == user_id))).scalars().all()
    rels = (await db.execute(select(Relation).where(Relation.user_id == user_id))).scalars().all()
    degree: dict[str, int] = {}
    for r in rels:
        degree[r.source_id] = degree.get(r.source_id, 0) + 1
        degree[r.target_id] = degree.get(r.target_id, 0) + 1
    return {
        "nodes": [{"id": e.id, "name": e.name, "type": e.type, "description": e.description, "degree": degree.get(e.id, 0)} for e in ents],
        "links": [{"id": r.id, "source": r.source_id, "target": r.target_id, "relation": r.relation, "memory_id": r.memory_id} for r in rels],
    }


async def context_lines(db: AsyncSession, user_id: str, text: str, memory_ids: list[str], limit: int = 25) -> list[str]:
    """Find entities mentioned in the message or attached to retrieved memories, return their 1-hop relations."""
    tl = f" {text.lower()} "
    ents = (await db.execute(select(Entity).where(Entity.user_id == user_id, Entity.type != "self"))).scalars().all()
    seed = {e.id for e in ents if len(e.name_key) >= 3 and f"{e.name_key}" in tl}
    if memory_ids:
        rows = (await db.execute(select(MemoryEntity.entity_id).where(MemoryEntity.memory_id.in_(memory_ids)))).scalars().all()
        seed.update(rows)
    if not seed:
        return []
    rels = (await db.execute(select(Relation).where(
        Relation.user_id == user_id, or_(Relation.source_id.in_(seed), Relation.target_id.in_(seed))).limit(limit))).scalars().all()
    names = {e.id: e for e in ents}
    if any(r.source_id not in names or r.target_id not in names for r in rels):
        all_e = (await db.execute(select(Entity).where(Entity.user_id == user_id))).scalars().all()
        names = {e.id: e for e in all_e}
    out = []
    for r in rels:
        s, t = names.get(r.source_id), names.get(r.target_id)
        if s and t:
            out.append(f"{s.name} ({s.type}) —{r.relation}→ {t.name} ({t.type})")
    return out
