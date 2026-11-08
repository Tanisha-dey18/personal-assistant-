"""'What JARVIS knows about me' — built live from the memory database, plus the timeline."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.memory import store
from app.models import CareerItem, Memory, ProfileSnapshot, Project
from app.services.usage import log_usage

SECTIONS = [
    ("who", "Who you are", ["personal", "people"]),
    ("studying", "What you're studying", ["education"]),
    ("learning", "What you're learning", ["learning"]),
    ("building", "What you're building", ["projects", "hackathons"]),
    ("goals", "What you want to achieve", ["goals", "career"]),
    ("skills", "Your skills", ["skills"]),
    ("experience", "Experience & achievements", ["internships", "achievements"]),
    ("challenges", "Challenges you've discussed", ["challenges", "decisions"]),
    ("preferences", "Preferences & routines", ["preferences", "routines"]),
    ("other", "Other things", ["other", "health"]),
]


async def knowledge(db, user_id: str) -> dict:
    rows = (await db.execute(select(Memory).where(Memory.user_id == user_id, Memory.status == "active")
                             .order_by(Memory.importance.desc(), Memory.updated_at.desc()))).scalars().all()
    by_cat: dict[str, list] = {}
    for m in rows:
        by_cat.setdefault(m.category, []).append(store.to_dict(m))
    sections = []
    for key, title, cats in SECTIONS:
        items = [i for c in cats for i in by_cat.get(c, [])]
        sections.append({"key": key, "title": title, "items": items})
    pending = (await db.execute(select(Memory).where(Memory.user_id == user_id, Memory.status == "pending"))).scalars().all()
    review = [store.to_dict(m) for m in rows if m.memory_type == "assumption"]
    snap = await db.get(ProfileSnapshot, user_id)
    return {"sections": sections, "total": len(rows), "pending": [store.to_dict(m) for m in pending], "needs_review": review,
            "portrait": snap.content if snap else "", "portrait_generated_at": snap.generated_at.isoformat() if snap else None}


async def synthesize(db, provider, user) -> str:
    rows = (await db.execute(select(Memory).where(Memory.user_id == user.id, Memory.status == "active", Memory.sensitive.is_(False))
                             .order_by(Memory.importance.desc()).limit(120))).scalars().all()
    if not rows:
        return "I don't know much about you yet. Talk to me, or import your CV / notes / ChatGPT history in Onboarding."
    facts = "\n".join(f"- [{m.category}{'' if m.memory_type == 'confirmed' else ', ' + m.memory_type}] {m.content}" for m in rows)
    text, usage = await provider.complete([
        {"role": "system", "content": "You are JARVIS. Write a warm, insightful second-person portrait ('You are...') of your owner "
                                      "using ONLY these memories. 150-250 words, markdown with 3-4 short paragraphs. Mention uncertainty for assumptions. "
                                      "Never add facts that aren't listed."},
        {"role": "user", "content": facts}], temperature=0.5)
    log_usage(db, user.id, "profile", usage)
    snap = await db.get(ProfileSnapshot, user.id)
    if not snap:
        snap = ProfileSnapshot(user_id=user.id)
        db.add(snap)
    snap.content, snap.generated_at = text.strip(), datetime.now(timezone.utc)
    await db.commit()
    return snap.content


async def timeline(db, user_id: str) -> list[dict]:
    items = []
    mems = (await db.execute(select(Memory).where(Memory.user_id == user_id, Memory.status == "active", Memory.event_date.is_not(None)))).scalars().all()
    for m in mems:
        items.append({"date": m.event_date, "title": store.text_of(m), "kind": m.category, "source": "memory", "id": m.id})
    career = (await db.execute(select(CareerItem).where(CareerItem.user_id == user_id, CareerItem.date.is_not(None)))).scalars().all()
    for c in career:
        items.append({"date": c.date, "title": f"{c.title}" + (f" — {c.organization}" if c.organization else ""), "kind": c.kind, "source": "career", "id": c.id})
    projects = (await db.execute(select(Project).where(Project.user_id == user_id))).scalars().all()
    for p in projects:
        items.append({"date": p.created_at.date().isoformat(), "title": f"Started project {p.name}", "kind": "projects", "source": "project", "id": p.id})
    items.sort(key=lambda x: x["date"] or "", reverse=True)
    return items
