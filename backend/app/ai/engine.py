"""The chat orchestrator — one call = one user turn.

  user message → pick mode → retrieve relevant memory → build prompt → stream LLM
  → run tools (loop) → save reply → (background) extract memories, summarise, title."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select

import app.tools  # noqa: F401  (registers tools)
from app.ai.modes import MODES, classify_mode, identity_prompt
from app.ai.provider import AIError, AIUnavailable, get_provider
from app.core.config import settings
from app.core.db import SessionLocal
from app.memory import retriever
from app.memory.extractor import extract_and_store
from app.models import Conversation, Integration, Message, User
from app.services import conversations as convs
from app.services.usage import log_usage
from app.services.user_settings import get_user_settings
from app.tools.registry import ToolContext, all_schemas, run_tool
from app.tools.google import google_configured

log = logging.getLogger("astra.engine")
Send = Callable[[dict], Awaitable[None]]
MAX_TOOL_ROUNDS = 6
_background: set[asyncio.Task] = set()


async def _integration_status(db, user_id: str) -> str:
    rows = (await db.execute(select(Integration.provider).where(Integration.user_id == user_id))).scalars().all()
    have = set(rows)
    parts = [
        f"Google Calendar/Gmail: {'connected' if 'google' in have else ('not connected' if google_configured() else 'not set up on server')}",
        f"GitHub: {'connected' if 'github' in have else 'not connected (public usernames still work)'}",
        f"Web search: {'available' if ('tavily' in have or settings.TAVILY_API_KEY) else 'not configured'}",
        "Weather: available",
    ]
    return "; ".join(parts)


async def run_turn(db, user: User, content: str, send: Send, conversation_id: str | None = None,
                   mode: str = "auto", voice: bool = False) -> dict | None:
    content = (content or "").strip()
    if not content:
        await send({"type": "error", "message": "Empty message."})
        return None
    if len(content) > 20000:
        await send({"type": "error", "message": "Message too long (20k characters max)."})
        return None
    try:
        provider = await get_provider(db, user.id)
    except AIUnavailable as e:
        await send({"type": "error", "code": "ai_unavailable", "message": str(e)})
        return None

    prefs = get_user_settings(user)
    conv = await convs.get_owned(db, user.id, conversation_id) if conversation_id else None
    is_new = conv is None
    if conv is None:
        conv = Conversation(user_id=user.id, mode=mode)
        db.add(conv)
        await db.flush()

    prev = (await db.execute(select(Message.mode).where(Message.conversation_id == conv.id, Message.role == "assistant")
                             .order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()
    resolved = classify_mode(content, prev) if mode in ("auto", "", None) else mode
    if resolved not in MODES:
        resolved = "companion"

    user_msg = Message(conversation_id=conv.id, user_id=user.id, role="user", content=content, meta={"voice": voice})
    db.add(user_msg)
    conv.mode = mode
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await send({"type": "start", "conversation_id": conv.id, "user_message_id": user_msg.id, "mode": resolved,
                "mode_source": "auto" if mode in ("auto", "", None) else "manual", "title": conv.title})

    hist = await convs.history(db, conv.id)
    prior_user = [m.content for m in hist[:-1] if m.role == "user"][-1:]
    query = content if len(content.split()) > 6 or not prior_user else f"{prior_user[0][:500]}\n{content}"

    try:
        ctx = await retriever.build_context(db, provider, user, query, conv.id)
    except AIError as e:
        await send({"type": "error", "message": str(e)})
        return None
    await send({"type": "context", "memories": ctx["memories_used"], "past_conversations": ctx["past_conversations"], "documents": ctx["documents"]})

    try:
        tz = ZoneInfo(prefs.get("timezone") or "UTC")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    now_local = datetime.now(tz)
    system = "\n\n".join([
        identity_prompt(user.name, prefs),
        "CURRENT MODE — " + MODES[resolved]["prompt"],
        f"Current date/time for the user: {now_local.strftime('%A %d %B %Y, %H:%M')} ({tz}). When creating tasks/reminders use ISO datetimes in this local time.",
        f"Integrations: {await _integration_status(db, user.id)}.",
        ("The user is talking by VOICE: answer in a natural spoken style, short sentences, no markdown tables or code unless asked." if voice else ""),
        "=== WHAT YOU KNOW (retrieved for this message) ===\n" + ctx["text"],
    ])
    messages: list[dict] = [{"role": "system", "content": system}]
    if conv.summary and await convs.message_count(db, conv.id) > convs.HISTORY_WINDOW:
        messages.append({"role": "system", "content": f"Summary of the earlier part of this conversation:\n{conv.summary}"})
    messages += [{"role": m.role, "content": m.content} for m in hist]

    model = prefs.get("model") or settings.CHAT_MODEL
    tctx = ToolContext(db=db, provider=provider, user=user, conversation_id=conv.id)
    tools = all_schemas()
    full_text, tools_used, pending = "", [], []

    try:
        for round_ in range(MAX_TOOL_ROUNDS):
            text, calls = "", None
            async for ev in provider.stream_chat(messages, tools, model, float(prefs.get("temperature", 0.7))):
                if ev["type"] == "token":
                    if not text and full_text:
                        await send({"type": "token", "content": "\n\n"})
                    text += ev["content"]
                    await send({"type": "token", "content": ev["content"]})
                elif ev["type"] == "tool_calls":
                    calls = ev["calls"]
                elif ev["type"] == "usage":
                    log_usage(db, user.id, "chat", ev["usage"])
            if text:
                full_text = f"{full_text}\n\n{text}" if full_text else text
            if not calls:
                break
            messages.append({"role": "assistant", "content": text or None, "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}} for c in calls]})
            for c in calls:
                await send({"type": "tool", "name": c.name, "status": "running", "args": c.arguments})
                result, event = await run_tool(tctx, c.name, c.arguments)
                tools_used.append({"name": c.name, "status": event["status"]})
                if event.get("action"):
                    pending.append(event["action"])
                    await send({"type": "pending_action", "action": event["action"]})
                await send({"type": "tool", **{k: v for k, v in event.items() if k != "action"}})
                messages.append({"role": "tool", "tool_call_id": c.id, "content": result})
            if round_ == MAX_TOOL_ROUNDS - 1:
                tools = None  # force a final text answer
    except AIError as e:
        await db.commit()
        await send({"type": "error", "message": str(e)})
        if not full_text:
            return None

    reply = Message(conversation_id=conv.id, user_id=user.id, role="assistant", content=full_text, mode=resolved,
                    meta={"tools": tools_used, "memory_ids": [m["id"] for m in ctx["memories_used"]],
                          "pending_actions": [p["id"] for p in pending]})
    db.add(reply)
    await db.commit()
    await send({"type": "done", "message": convs.msg_dict(reply), "conversation_id": conv.id})

    task = asyncio.create_task(post_turn(user.id, conv.id, content, full_text, is_new, send))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return convs.msg_dict(reply)


async def post_turn(user_id: str, conv_id: str, user_text: str, reply: str, is_new: bool, send: Send | None) -> None:
    """Memory extraction + summarisation + title, in a fresh DB session after the reply is sent."""
    async with SessionLocal() as db:
        try:
            user = await db.get(User, user_id)
            conv = await db.get(Conversation, conv_id)
            provider = await get_provider(db, user_id)
            if is_new:
                title = await convs.maybe_title(db, provider, user, conv, user_text)
                if title and send:
                    await _safe_send(send, {"type": "title", "conversation_id": conv_id, "title": title})
            result = await extract_and_store(db, provider, user, user_text, reply, kind="chat", source="chat", source_ref=conv_id)
            if send and (result["created"] or result["updated"] or result["pending"]):
                await _safe_send(send, {"type": "memory_update", **{k: result[k] for k in ("created", "updated", "pending")}})
            await convs.maybe_summarize(db, provider, user, conv)
        except Exception:  # noqa: BLE001
            log.exception("post-turn processing failed")


async def _safe_send(send: Send, data: dict) -> None:
    try:
        await send(data)
    except Exception:  # noqa: BLE001 — socket may be closed
        pass


async def wait_background() -> None:
    """Used by tests to wait for memory extraction to finish."""
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)
