"""Proactive intelligence: a background loop that turns data into timely nudges.
Every rule is switchable per user in Settings → Proactive. Nudges are de-duplicated with
dedupe keys so you don't get the same one twice."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.ai.provider import AIUnavailable, get_provider
from app.core.config import settings
from app.core.db import SessionLocal
from app.memory import store
from app.models import CareerItem, Memory, Notification, Project, Reminder, Task, User
from app.services.usage import log_usage
from app.services.user_settings import get_user_settings

log = logging.getLogger("astra.proactive")


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _notify(db, user_id: str, kind: str, title: str, body: str = "", dedupe: str | None = None) -> bool:
    if dedupe:
        exists = (await db.execute(select(Notification.id).where(Notification.user_id == user_id, Notification.dedupe_key == dedupe))).first()
        if exists:
            return False
    db.add(Notification(user_id=user_id, kind=kind, title=title, body=body, dedupe_key=dedupe))
    return True


async def run_for_user(db, user: User) -> int:
    p = get_user_settings(user)["proactive"]
    if not p.get("enabled", True):
        return 0
    now = datetime.now(timezone.utc)
    week = now.strftime("%G-W%V")
    n = 0

    if p.get("reminders", True):
        due = (await db.execute(select(Reminder).where(Reminder.user_id == user.id, Reminder.done.is_(False),
                                                       Reminder.notified.is_(False), Reminder.remind_at <= now))).scalars().all()
        for r in due:
            n += await _notify(db, user.id, "reminder", f"⏰ {r.text}", "", f"reminder:{r.id}")
            r.notified = True

    if p.get("task_deadlines", True):
        soon = (await db.execute(select(Task).where(Task.user_id == user.id, Task.status != "done", Task.due_at.is_not(None),
                                                    Task.due_at <= now + timedelta(hours=24)))).scalars().all()
        for t in soon:
            overdue = _aware(t.due_at) < now
            n += await _notify(db, user.id, "task", f"{'Overdue' if overdue else 'Due soon'}: {t.title}",
                               f"Due {_aware(t.due_at).strftime('%d %b %H:%M')} UTC", f"task:{t.id}:{'over' if overdue else 'soon'}")

    if p.get("stale_projects", True):
        projects = (await db.execute(select(Project).where(Project.user_id == user.id, Project.status == "active"))).scalars().all()
        for pr in projects:
            days = (now - _aware(pr.updated_at)).days
            if days >= 14:
                n += await _notify(db, user.id, "project", f"{pr.name} hasn't moved in {days} days",
                                   "Want to plan the next step, or mark it paused?", f"stale:{pr.id}:{week}")
        for pr in projects:
            if pr.deadline and now < _aware(pr.deadline) <= now + timedelta(days=3):
                n += await _notify(db, user.id, "project", f"{pr.name} deadline in {(_aware(pr.deadline) - now).days + 1} day(s)",
                                   f"Progress is at {pr.progress}%.", f"deadline:{pr.id}")

    if p.get("career_followups", True):
        apps = (await db.execute(select(CareerItem).where(CareerItem.user_id == user.id, CareerItem.kind == "application",
                                                          CareerItem.status.in_(("applied", "interviewing"))))).scalars().all()
        for a in apps:
            if (now - _aware(a.updated_at)).days >= 10:
                n += await _notify(db, user.id, "career", f"Follow up on {a.title}" + (f" at {a.organization}" if a.organization else ""),
                                   "It's been 10+ days since the last update. A polite follow-up email often helps.", f"followup:{a.id}:{week}")

    if p.get("weekly_report", True) and now.weekday() == 6 and now.hour >= 12:  # Sunday afternoon UTC
        key = f"weekly:{week}"
        exists = (await db.execute(select(Notification.id).where(Notification.user_id == user.id, Notification.dedupe_key == key))).first()
        if not exists:
            body = await weekly_report(db, user)
            if body:
                n += await _notify(db, user.id, "report", "Your weekly report from ASTRA", body, key)

    await db.commit()
    return n


async def weekly_report(db, user: User) -> str | None:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    mems = (await db.execute(select(Memory).where(Memory.user_id == user.id, Memory.status == "active", Memory.updated_at >= since)
                             .order_by(Memory.importance.desc()).limit(40))).scalars().all()
    done = (await db.execute(select(Task).where(Task.user_id == user.id, Task.status == "done", Task.completed_at >= since))).scalars().all()
    open_ = (await db.execute(select(Task).where(Task.user_id == user.id, Task.status != "done"))).scalars().all()
    if not mems and not done:
        return None
    try:
        provider = await get_provider(db, user.id)
    except AIUnavailable:
        return f"This week: {len(done)} tasks completed, {len(open_)} still open, {len(mems)} new things learned about you."
    facts = "\n".join(f"- [{m.category}] {store.text_of(m)}" for m in mems if not m.sensitive)
    text, usage = await provider.complete([
        {"role": "system", "content": "You are ASTRA writing a short, warm, honest weekly progress report (max 150 words) for your owner. "
                                      "Highlight learning, building and career progress, call out one thing to improve, suggest one focus for next week. Only use the data given."},
        {"role": "user", "content": f"New/updated memories this week:\n{facts or '(none)'}\n\nCompleted tasks: {[t.title for t in done]}\nOpen tasks: {[t.title for t in open_][:15]}"}])
    log_usage(db, user.id, "report", usage)
    return text.strip()


async def loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with SessionLocal() as db:
                users = (await db.execute(select(User))).scalars().all()
                for u in users:
                    try:
                        await run_for_user(db, u)
                    except Exception:  # noqa: BLE001
                        log.exception("proactive run failed for user")
                        await db.rollback()
        except Exception:  # noqa: BLE001
            log.exception("proactive loop error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.PROACTIVE_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
