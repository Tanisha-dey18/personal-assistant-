"""Settings, status/usage, voice, integrations, pending-action confirmation, export & data deletion."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.modes import MODES
from app.ai.provider import AIError, AIUnavailable, ai_configured, build_provider, get_provider
from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user, rate_limited_user
from app.core.security import create_token, decode_token, verify_password
from app.memory import store
from app.memory.vectors import ALL, vectors
from app.models import (CareerItem, Conversation, Document, Entity, ImportJob, Memory, Message, Notification, PendingAction,
                        ProfileSnapshot, Project, Relation, Reminder, Task, UsageLog, User)
from app.services.integrations_store import delete_integration, get_integration, set_secret
from app.services.usage import log_usage
from app.services.user_settings import get_user_settings, update_user_settings
from app.tools import google as g
from app.tools.registry import ToolContext, ToolError, action_dict, execute_action

router = APIRouter(prefix="/api", tags=["system"])
VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"]


# ------------------------------------------------------------------ status & settings
@router.get("/status")
async def status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {
        "ai_configured": await ai_configured(db, user.id),
        "provider": settings.LLM_PROVIDER,
        "chat_model": get_user_settings(user).get("model") or settings.CHAT_MODEL,
        "database": "postgresql" if "postgresql" in settings.async_database_url else "sqlite",
        "vector_store": "qdrant-server" if settings.QDRANT_URL else "qdrant-embedded",
        "cache": "redis" if settings.REDIS_URL else "in-memory",
        "modes": [{"id": k, "label": v["label"]} for k, v in MODES.items()],
    }


@router.get("/settings")
async def get_settings_(user: User = Depends(get_current_user)):
    return {"settings": get_user_settings(user), "available_models": settings.available_models, "default_model": settings.CHAT_MODEL,
            "voices": VOICES, "modes": [{"id": k, "label": v["label"]} for k, v in MODES.items()]}


@router.patch("/settings")
async def patch_settings(patch: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    allowed = {"model", "temperature", "default_mode", "personality", "voice", "memory", "proactive", "learning", "location", "timezone"}
    bad = set(patch) - allowed
    if bad:
        raise HTTPException(400, f"Unknown settings: {', '.join(bad)}")
    if patch.get("model") and patch["model"] not in settings.available_models:
        raise HTTPException(400, "Model not in AVAILABLE_MODELS")
    if "temperature" in patch:
        patch["temperature"] = max(0.0, min(1.5, float(patch["temperature"])))
    merged = update_user_settings(user, patch)
    await db.commit()
    return {"settings": merged}


@router.get("/usage")
async def usage(days: int = 30, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(select(UsageLog.kind, UsageLog.model, func.count(), func.sum(UsageLog.prompt_tokens), func.sum(UsageLog.completion_tokens))
                             .where(UsageLog.user_id == user.id, UsageLog.created_at >= since).group_by(UsageLog.kind, UsageLog.model))).all()
    items = [{"kind": k, "model": m, "calls": c, "prompt_tokens": p or 0, "completion_tokens": o or 0} for k, m, c, p, o in rows]
    return {"days": days, "items": items, "total_tokens": sum(i["prompt_tokens"] + i["completion_tokens"] for i in items)}


# ------------------------------------------------------------------ voice
@router.post("/voice/transcribe")
async def transcribe(file: UploadFile = File(...), user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    data = await file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "Audio too long")
    if len(data) < 1000:
        return {"text": ""}
    try:
        provider = await get_provider(db, user.id)
        text = await provider.transcribe(data, Path(file.filename or "audio.webm").name,
                                         prompt="Conversation with JARVIS. The speaker may mix Hindi and English (Hinglish).")
    except AIUnavailable as e:
        raise HTTPException(503, str(e)) from e
    except AIError as e:
        raise HTTPException(502, str(e)) from e
    db.add(UsageLog(user_id=user.id, kind="stt", model=settings.STT_MODEL))
    await db.commit()
    return {"text": text.strip()}


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None
    speed: float | None = None


@router.post("/voice/speak")
async def speak(body: SpeakIn, user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    prefs = get_user_settings(user)["voice"]
    voice = body.voice or prefs.get("voice") or settings.DEFAULT_VOICE
    if voice not in VOICES:
        voice = settings.DEFAULT_VOICE
    try:
        provider = await get_provider(db, user.id)
        audio = await provider.speak(body.text, voice, body.speed or prefs.get("speed", 1.0),
                                     instructions="Warm, natural, lightly playful, intelligent companion. Conversational pacing.")
    except AIUnavailable as e:
        raise HTTPException(503, str(e)) from e
    except AIError as e:
        raise HTTPException(502, str(e)) from e
    db.add(UsageLog(user_id=user.id, kind="tts", model=settings.TTS_MODEL, completion_tokens=len(body.text)))
    await db.commit()
    return Response(content=audio, media_type="audio/mpeg")


# ------------------------------------------------------------------ integrations
@router.get("/integrations")
async def integrations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async def info(p):
        i = await get_integration(db, user.id, p)
        return {"connected": bool(i), "meta": (i.meta if i else {}), "connected_at": i.created_at.isoformat() if i else None}

    return {
        "openai": {**await info("openai"), "server_key": bool(settings.OPENAI_API_KEY)},
        "google": {**await info("google"), "server_configured": g.google_configured(), "redirect_uri": settings.google_redirect_uri},
        "github": await info("github"),
        "tavily": {**await info("tavily"), "server_key": bool(settings.TAVILY_API_KEY)},
        "weather": {"connected": True, "meta": {"provider": "Open-Meteo (no key needed)"}},
    }


class KeyIn(BaseModel):
    api_key: str = Field(min_length=10, max_length=500)
    base_url: str = Field(default="", max_length=300)


@router.post("/integrations/openai")
async def connect_openai(body: KeyIn, user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    try:  # verify the key works before saving it
        p = build_provider(body.api_key, body.base_url)
        _, u = await p.complete([{"role": "user", "content": "Reply with OK"}])
        log_usage(db, user.id, "verify", u)
    except AIError as e:
        raise HTTPException(400, f"Key check failed: {e}") from e
    await set_secret(db, user.id, "openai", {"api_key": body.api_key, "base_url": body.base_url},
                     meta={"key_hint": "…" + body.api_key[-4:], "base_url": body.base_url})
    indexed = await store.backfill_vectors(db, p, user.id)  # memories saved before the key existed
    return {"connected": True, "indexed_memories": indexed}


@router.post("/integrations/tavily")
async def connect_tavily(body: KeyIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await set_secret(db, user.id, "tavily", {"api_key": body.api_key}, meta={"key_hint": "…" + body.api_key[-4:]})
    return {"connected": True}


class GithubIn(BaseModel):
    token: str = Field(min_length=10, max_length=300)


@router.post("/integrations/github")
async def connect_github(body: GithubIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    import httpx

    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.github.com/user", headers={"Authorization": f"Bearer {body.token}", "Accept": "application/vnd.github+json"})
    if r.status_code != 200:
        raise HTTPException(400, "GitHub rejected that token.")
    login = r.json().get("login")
    await set_secret(db, user.id, "github", {"token": body.token}, meta={"login": login})
    return {"connected": True, "login": login}


@router.get("/integrations/google/auth-url")
async def google_auth_url(user: User = Depends(get_current_user)):
    if not g.google_configured():
        raise HTTPException(400, "Google OAuth isn't configured on the server. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (see README).")
    state = create_token(user.id, purpose="google_oauth", minutes=10)
    return {"url": g.auth_url(state)}


@router.get("/integrations/google/callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                          db: AsyncSession = Depends(get_db)):
    target = f"{settings.FRONTEND_URL.rstrip('/')}/integrations"
    if error or not code or not state:
        return RedirectResponse(f"{target}?google=error")
    data = decode_token(state, purpose="google_oauth")
    if not data:
        return RedirectResponse(f"{target}?google=expired")
    try:
        tok = await g.exchange_code(code)
    except Exception:  # noqa: BLE001
        return RedirectResponse(f"{target}?google=error")
    await set_secret(db, data["sub"], "google", tok, meta={"email": tok.get("email")})
    return RedirectResponse(f"{target}?google=connected")


@router.delete("/integrations/{provider}")
async def disconnect(provider: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if provider not in ("openai", "google", "github", "tavily"):
        raise HTTPException(404, "Unknown integration")
    return {"disconnected": await delete_integration(db, user.id, provider)}


# ------------------------------------------------------------------ pending actions (human-in-the-loop)
@router.get("/actions")
async def list_actions(status: str = "pending", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PendingAction).where(PendingAction.user_id == user.id, PendingAction.status == status)
                             .order_by(PendingAction.created_at.desc()).limit(50))).scalars().all()
    return {"items": [action_dict(a) for a in rows]}


async def _note(db, a: PendingAction, text: str):
    if a.conversation_id:
        db.add(Message(conversation_id=a.conversation_id, user_id=a.user_id, role="assistant", content=text,
                       mode="executive", meta={"action_id": a.id, "system_note": True}))


@router.post("/actions/{aid}/approve")
async def approve_action(aid: str, user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    a = await db.get(PendingAction, aid)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Action not found")
    if a.status != "pending":
        raise HTTPException(409, f"Action already {a.status}")
    try:
        provider = await get_provider(db, user.id)
    except AIUnavailable:
        provider = None
    try:
        result = await execute_action(ToolContext(db=db, provider=provider, user=user, conversation_id=a.conversation_id), a)
        a.status, a.result = "executed", result[:4000]
        await _note(db, a, f"✅ Done — {a.summary.splitlines()[0]}")
    except (ToolError, Exception) as e:  # noqa: BLE001
        a.status, a.result = "failed", str(e)[:1000]
        await _note(db, a, f"⚠️ That action failed: {e}")
    await db.commit()
    return action_dict(a)


@router.post("/actions/{aid}/reject")
async def reject_action(aid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    a = await db.get(PendingAction, aid)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Action not found")
    if a.status != "pending":
        raise HTTPException(409, f"Action already {a.status}")
    a.status = "rejected"
    await _note(db, a, f"❌ Cancelled — {a.summary.splitlines()[0]}")
    await db.commit()
    return action_dict(a)


# ------------------------------------------------------------------ export & deletion
def _row(obj) -> dict:
    out = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        out[col.name] = v.isoformat() if isinstance(v, datetime) else v
    return out


@router.get("/export")
async def export_all(user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    """Everything JARVIS stores about you, decrypted, as JSON (secrets/tokens excluded)."""
    out = {"exported_at": datetime.now(timezone.utc).isoformat(), "user": {"email": user.email, "name": user.name, "settings": get_user_settings(user)}}
    mems = (await db.execute(select(Memory).where(Memory.user_id == user.id))).scalars().all()
    out["memories"] = [store.to_dict(m) for m in mems]
    for key, model in [("conversations", Conversation), ("messages", Message), ("entities", Entity), ("relations", Relation),
                       ("tasks", Task), ("reminders", Reminder), ("projects", Project), ("career", CareerItem),
                       ("documents", Document), ("notifications", Notification)]:
        rows = (await db.execute(select(model).where(model.user_id == user.id))).scalars().all()
        out[key] = [_row(r) for r in rows]
    return out


@router.get("/export/memories")
async def export_memories(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    mems = (await db.execute(select(Memory).where(Memory.user_id == user.id).order_by(Memory.category))).scalars().all()
    return {"memories": [store.to_dict(m) for m in mems]}


class WipeIn(BaseModel):
    password: str
    scope: str = Field(default="memories", pattern="^(memories|conversations|everything)$")


@router.post("/data/wipe")
async def wipe(body: WipeIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Irreversible deletion. 'memories' = memories + graph; 'conversations' = chat history; 'everything' = all personal data (account kept)."""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(400, "Password is wrong.")
    uid = user.id
    if body.scope in ("memories", "everything"):
        from app.models import MemoryEntity

        mids = select(Memory.id).where(Memory.user_id == uid)
        await db.execute(delete(MemoryEntity).where(MemoryEntity.memory_id.in_(mids)))
        await db.execute(delete(Relation).where(Relation.user_id == uid))
        await db.execute(delete(Entity).where(Entity.user_id == uid))
        await db.execute(delete(Memory).where(Memory.user_id == uid))
        await db.execute(delete(ProfileSnapshot).where(ProfileSnapshot.user_id == uid))
        await vectors.delete_where(ALL[0], uid)
    if body.scope in ("conversations", "everything"):
        await db.execute(delete(Message).where(Message.user_id == uid))
        await db.execute(delete(PendingAction).where(PendingAction.user_id == uid))
        await db.execute(delete(Conversation).where(Conversation.user_id == uid))
        await vectors.delete_where(ALL[2], uid)
    if body.scope == "everything":
        for model in (Task, Reminder, Project, CareerItem, Document, ImportJob, Notification, UsageLog):
            await db.execute(delete(model).where(model.user_id == uid))
        await vectors.delete_where(ALL[1], uid)
        user.onboarded = False
    await db.commit()
    return {"wiped": body.scope}
