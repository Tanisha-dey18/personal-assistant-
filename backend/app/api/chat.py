"""Chat over WebSocket (streaming) + conversation history endpoints."""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.engine import run_turn
from app.core.cache import cache
from app.core.config import settings
from app.core.db import SessionLocal, get_db
from app.core.deps import get_current_user, user_from_token
from app.memory.vectors import CONVERSATIONS, vectors
from app.models import Conversation, Message, User
from app.services import conversations as convs

router = APIRouter(prefix="/api", tags=["chat"])
log = logging.getLogger("astra.ws")


@router.websocket("/chat/ws")
async def chat_ws(ws: WebSocket):
    """Protocol:
    client → {"type":"auth","token":...} first, then {"type":"chat","content":...,"conversation_id":?, "mode":"auto", "voice":false}
    server → start | context | token | tool | pending_action | done | title | memory_update | error"""
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=15))
    except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
        await ws.close(code=4401)
        return
    async with SessionLocal() as db:
        user = await user_from_token(first.get("token", ""), db) if first.get("type") == "auth" else None
        user_id = user.id if user else None
    if not user_id:
        await ws.send_json({"type": "error", "code": "unauthorized", "message": "Invalid session"})
        await ws.close(code=4401)
        return
    await ws.send_json({"type": "ready"})

    lock = asyncio.Lock()

    async def send(data: dict):
        async with lock:
            await ws.send_json(data)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                await send({"type": "pong"})
                continue
            if msg.get("type") != "chat":
                continue
            n = await cache.incr(f"rl:user:{user_id}", 60)
            if n > settings.RATE_LIMIT_PER_MINUTE:
                await send({"type": "error", "message": "Rate limit reached — give me a minute."})
                continue
            async with SessionLocal() as db:
                user = await db.get(User, user_id)
                if not user:
                    await ws.close(code=4401)
                    return
                try:
                    await run_turn(db, user, msg.get("content", ""), send, msg.get("conversation_id"),
                                   msg.get("mode", "auto"), bool(msg.get("voice")))
                except WebSocketDisconnect:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.exception("turn failed")
                    await send({"type": "error", "message": f"Something broke on my side: {e}"})
    except WebSocketDisconnect:
        return
    except RuntimeError:  # socket closed while sending
        return


@router.get("/conversations")
async def list_conversations(q: str | None = None, source: str | None = None, limit: int = 50, offset: int = 0,
                             user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Conversation).where(Conversation.user_id == user.id)
    if q:
        stmt = stmt.where(Conversation.title.ilike(f"%{q}%"))
    if source:
        stmt = stmt.where(Conversation.source == source)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc()).limit(min(limit, 200)).offset(offset))).scalars().all()
    return {"items": [convs.conv_dict(c) for c in rows], "total": total}


@router.get("/conversations/{cid}")
async def get_conversation(cid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await convs.get_owned(db, user.id, cid)
    if not c:
        raise HTTPException(404, "Conversation not found")
    msgs = (await db.execute(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).scalars().all()
    return {"conversation": convs.conv_dict(c), "messages": [convs.msg_dict(m) for m in msgs]}


class ConvPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None


@router.patch("/conversations/{cid}")
async def patch_conversation(cid: str, body: ConvPatch, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await convs.get_owned(db, user.id, cid)
    if not c:
        raise HTTPException(404, "Conversation not found")
    if body.title is not None:
        c.title = body.title
    if body.pinned is not None:
        c.pinned = body.pinned
    await db.commit()
    return convs.conv_dict(c)


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await convs.get_owned(db, user.id, cid)
    if not c:
        raise HTTPException(404, "Conversation not found")
    await db.execute(delete(Message).where(Message.conversation_id == cid))
    await db.delete(c)
    await db.commit()
    await vectors.delete(CONVERSATIONS, [cid])
    return {"deleted": True}
