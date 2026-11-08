"""Turns conversations/documents into structured long-term memories.

Pipeline per exchange:
  1. fetch existing memories similar to the new text (so the LLM can UPDATE instead of duplicating)
  2. ask a fast model for strict JSON: facts, type (confirmed/assumption/temporary), importance,
     sensitivity, entities + relations for the knowledge graph, clarifying questions
  3. write them through store.create_memory (which also runs vector duplicate detection)
  4. sensitive facts are parked as status="pending" until the user approves them."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory import graph, store
from app.models import Notification
from app.services.usage import log_usage
from app.services.user_settings import get_user_settings

log = logging.getLogger("astra.memory")

SYSTEM = """You are the memory curator for JARVIS, a personal AI companion. You decide what is worth
remembering long-term about the OWNER (the human user). Output ONLY JSON.

Rules:
- Only record facts about the owner, their life, people they know, their work, projects, goals,
  preferences, skills, decisions, routines, achievements, challenges and plans.
- Only use what the OWNER said or what the source document states. Never infer facts from the
  assistant's replies, never invent details, never guess dates.
- Skip small talk, jokes, one-off questions with no lasting relevance, and general knowledge.
- Write each memory as a short standalone sentence in third person about "the user"
  (e.g. "The user is a B.Tech CSE student at XYZ University, graduating 2027.").
- memory_type: "confirmed" = stated plainly; "assumption" = implied/uncertain/ambiguous;
  "temporary" = only relevant for a short time (e.g. "has an exam on Friday") — set expires_in_days.
- importance 0..1: identity/education/career goals/major projects ≈ 0.8-1; skills/preferences ≈ 0.5-0.7; minor ≈ 0.2-0.4.
- sensitive=true for health, mental health, finances, religion, politics, sexuality, legal issues,
  government IDs, passwords or intimate relationship details. NEVER store passwords/keys/ID numbers — skip them.
- If an EXISTING memory is now outdated or should be refined, use action "update" with its target_id
  and the full corrected sentence. If it simply repeats an existing memory, output nothing for it.
- event_date: only if an explicit date/year is given (YYYY, YYYY-MM or YYYY-MM-DD).
- entities: things mentioned in the memory with type in
  [person, event, project, technology, skill, goal, achievement, organization, place, course, concept].
  Use "Me" for the owner.
- relations: links like {"source":"Me","relation":"built","target":"StudyBuddy"},
  {"source":"StudyBuddy","relation":"uses","target":"FastAPI"}, {"source":"Smart India Hackathon","relation":"produced","target":"StudyBuddy"}.
- questions: up to 2 short clarifying questions ONLY when something important is genuinely ambiguous.

Categories: personal, education, career, skills, learning, projects, internships, achievements,
hackathons, people, preferences, goals, routines, decisions, challenges, health, other.

JSON shape:
{"memories":[{"action":"create|update","target_id":null,"content":"...","category":"...",
"memory_type":"confirmed|assumption|temporary","importance":0.7,"sensitive":false,"expires_in_days":null,
"event_date":null,"entities":[{"name":"...","type":"..."}],"relations":[{"source":"...","relation":"...","target":"..."}]}],
"questions":[]}
Return {"memories":[],"questions":[]} when nothing is worth remembering."""


def _parse(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return {"memories": [], "questions": []}
        try:
            data = json.loads(text[start: end + 1])
        except json.JSONDecodeError:
            return {"memories": [], "questions": []}
    if not isinstance(data, dict):
        return {"memories": [], "questions": []}
    data.setdefault("memories", [])
    data.setdefault("questions", [])
    return data


async def extract_and_store(
    db: AsyncSession, provider, user, text: str, assistant_text: str = "", kind: str = "chat",
    source: str = "chat", source_ref: str | None = None, force_type: str | None = None,
) -> dict:
    prefs = get_user_settings(user)["memory"]
    result = {"created": [], "updated": [], "pending": [], "questions": []}
    if not text.strip():
        return result

    related = await store.semantic_search(db, provider, user.id, text[:2000], limit=8, min_score=0.3)
    existing = "\n".join(f"- id={m.id} [{m.category}] {store.text_of(m)}" for m, _ in related) or "(none)"
    if kind == "chat":
        body = f"OWNER said:\n{text}\n\nASSISTANT replied (context only, not facts):\n{assistant_text[:1500]}"
    elif kind == "conversation":
        body = f"Messages the OWNER wrote in an older chat with another AI assistant:\n{text}"
    else:
        body = f"Document provided by the OWNER about themselves ({source_ref}):\n{text}"
    today = datetime.now(timezone.utc).date().isoformat()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Today: {today}\n\nEXISTING related memories:\n{existing}\n\n{body}"},
    ]
    raw, usage = await provider.complete(messages, json_mode=True)
    log_usage(db, user.id, "extract", usage)
    data = _parse(raw)
    related_ids = {m.id: m for m, _ in related}

    for item in data["memories"][:15]:
        content = (item.get("content") or "").strip()
        if not content or len(content) > 1000:
            continue
        sensitive = bool(item.get("sensitive"))
        mtype = force_type or item.get("memory_type", "confirmed")
        status = "active"
        if (sensitive and prefs.get("ask_before_sensitive", True)) or not prefs.get("auto_save", True):
            status = "pending"
        expires = None
        if mtype == "temporary":
            days = item.get("expires_in_days") or 7
            try:
                expires = datetime.now(timezone.utc) + timedelta(days=max(1, min(365, int(days))))
            except (TypeError, ValueError):
                expires = datetime.now(timezone.utc) + timedelta(days=7)
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5

        target = related_ids.get(item.get("target_id") or "")
        if item.get("action") == "update" and target:
            await store.update_memory(db, provider, target, content=content, category=item.get("category"),
                                      memory_type=mtype, importance=max(target.importance, importance))
            mem, bucket = target, "updated"
        else:
            mem, created = await store.create_memory(
                db, provider, user.id, content, item.get("category"), mtype, importance, sensitive,
                source=source, source_ref=source_ref, event_date=item.get("event_date"), expires_at=expires, status=status,
            )
            bucket = ("pending" if mem.status == "pending" else "created") if created else "updated"
        try:
            await graph.apply_graph(db, user.id, mem.id, item.get("entities") or [], item.get("relations") or [])
            await db.commit()
        except Exception:  # noqa: BLE001 — graph is best effort
            await db.rollback()
            log.exception("graph update failed")
        result[bucket].append(store.to_dict(mem))

    for q in data["questions"][:2]:
        if isinstance(q, str) and q.strip():
            result["questions"].append(q.strip())
            if kind != "chat":  # during chat JARVIS can just ask; during imports we queue them
                db.add(Notification(user_id=user.id, kind="question", title="JARVIS has a question", body=q.strip()))
    if result["pending"]:
        db.add(Notification(user_id=user.id, kind="memory", title="Sensitive memory awaiting approval",
                            body=f"{len(result['pending'])} item(s) need your OK before JARVIS remembers them.",
                            dedupe_key=None))
    await db.commit()
    return result
