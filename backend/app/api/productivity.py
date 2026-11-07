"""Tasks, reminders, projects, career tracker, notifications and the home dashboard."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import ai_configured
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models import CareerItem, Conversation, Memory, Notification, PendingAction, Project, Reminder, Task, User
from app.services import conversations as convs
from app.tools.registry import action_dict

router = APIRouter(prefix="/api", tags=["productivity"])


def _iso(d):
    return d.isoformat() if d else None


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


async def _owned(db, model, oid: str, user_id: str):
    obj = await db.get(model, oid)
    if not obj or obj.user_id != user_id:
        raise HTTPException(404, "Not found")
    return obj


# ------------------------------------------------------------------ tasks
class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = ""
    status: Literal["todo", "doing", "done"] = "todo"
    priority: Literal["low", "medium", "high"] = "medium"
    due_at: datetime | None = None
    project_id: str | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    notes: str | None = None
    status: Literal["todo", "doing", "done"] | None = None
    priority: Literal["low", "medium", "high"] | None = None
    due_at: datetime | None = None
    project_id: str | None = None


def task_out(t: Task) -> dict:
    return {"id": t.id, "title": t.title, "notes": t.notes, "status": t.status, "priority": t.priority, "due_at": _iso(t.due_at),
            "project_id": t.project_id, "completed_at": _iso(t.completed_at), "created_at": _iso(t.created_at)}


@router.get("/tasks")
async def list_tasks(status: str | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    q = select(Task).where(Task.user_id == user.id)
    if status:
        q = q.where(Task.status == status)
    rows = (await db.execute(q.order_by(Task.status == "done", Task.due_at.is_(None), Task.due_at, Task.created_at.desc()))).scalars().all()
    return {"items": [task_out(t) for t in rows]}


@router.post("/tasks")
async def create_task(body: TaskIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.project_id:
        await _owned(db, Project, body.project_id, user.id)
    t = Task(user_id=user.id, **body.model_dump())
    if t.status == "done":
        t.completed_at = datetime.now(timezone.utc)
    db.add(t)
    await db.commit()
    return task_out(t)


@router.patch("/tasks/{tid}")
async def patch_task(tid: str, body: TaskPatch, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    t = await _owned(db, Task, tid, user.id)
    data = body.model_dump(exclude_unset=True)
    if data.get("project_id"):
        await _owned(db, Project, data["project_id"], user.id)
    for k, v in data.items():
        setattr(t, k, v)
    if "status" in data:
        t.completed_at = datetime.now(timezone.utc) if t.status == "done" else None
    await db.commit()
    return task_out(t)


@router.delete("/tasks/{tid}")
async def delete_task(tid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Task, tid, user.id))
    await db.commit()
    return {"deleted": True}


# ------------------------------------------------------------------ reminders
class ReminderIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    remind_at: datetime


def rem_out(r: Reminder) -> dict:
    return {"id": r.id, "text": r.text, "remind_at": _iso(r.remind_at), "done": r.done, "notified": r.notified}


@router.get("/reminders")
async def list_reminders(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Reminder).where(Reminder.user_id == user.id).order_by(Reminder.done, Reminder.remind_at))).scalars().all()
    return {"items": [rem_out(r) for r in rows]}


@router.post("/reminders")
async def create_reminder(body: ReminderIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = Reminder(user_id=user.id, text=body.text, remind_at=_aware(body.remind_at))
    db.add(r)
    await db.commit()
    return rem_out(r)


@router.patch("/reminders/{rid}")
async def patch_reminder(rid: str, done: bool = True, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await _owned(db, Reminder, rid, user.id)
    r.done = done
    await db.commit()
    return rem_out(r)


@router.delete("/reminders/{rid}")
async def delete_reminder(rid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Reminder, rid, user.id))
    await db.commit()
    return {"deleted": True}


# ------------------------------------------------------------------ projects
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    tech_stack: list[str] = []
    status: Literal["idea", "active", "paused", "done"] = "active"
    progress: int = Field(default=0, ge=0, le=100)
    repo_url: str = ""
    deadline: datetime | None = None
    docs: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    tech_stack: list[str] | None = None
    status: Literal["idea", "active", "paused", "done"] | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    repo_url: str | None = None
    deadline: datetime | None = None
    docs: str | None = None


def proj_out(p: Project, tasks: list[Task] | None = None) -> dict:
    d = {"id": p.id, "name": p.name, "description": p.description, "tech_stack": p.tech_stack or [], "status": p.status,
         "progress": p.progress, "repo_url": p.repo_url, "deadline": _iso(p.deadline), "docs": p.docs,
         "created_at": _iso(p.created_at), "updated_at": _iso(p.updated_at)}
    if tasks is not None:
        d["tasks"] = [task_out(t) for t in tasks]
    return d


@router.get("/projects")
async def list_projects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Project).where(Project.user_id == user.id).order_by(Project.updated_at.desc()))).scalars().all()
    tasks = (await db.execute(select(Task).where(Task.user_id == user.id, Task.project_id.is_not(None)))).scalars().all()
    by = {}
    for t in tasks:
        by.setdefault(t.project_id, []).append(t)
    return {"items": [proj_out(p, by.get(p.id, [])) for p in rows]}


@router.post("/projects")
async def create_project(body: ProjectIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = Project(user_id=user.id, **body.model_dump())
    db.add(p)
    await db.commit()
    return proj_out(p, [])


@router.patch("/projects/{pid}")
async def patch_project(pid: str, body: ProjectPatch, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _owned(db, Project, pid, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    p.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return proj_out(p)


@router.delete("/projects/{pid}")
async def delete_project(pid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Project, pid, user.id))
    await db.commit()
    return {"deleted": True}


# ------------------------------------------------------------------ career
class CareerIn(BaseModel):
    kind: Literal["application", "internship", "achievement", "skill", "milestone"]
    title: str = Field(min_length=1, max_length=300)
    organization: str = ""
    status: str = ""
    level: int = Field(default=0, ge=0, le=100)
    date: str | None = None
    notes: str = ""
    link: str = ""


class CareerPatch(BaseModel):
    title: str | None = None
    organization: str | None = None
    status: str | None = None
    level: int | None = Field(default=None, ge=0, le=100)
    date: str | None = None
    notes: str | None = None
    link: str | None = None


def career_out(c: CareerItem) -> dict:
    return {"id": c.id, "kind": c.kind, "title": c.title, "organization": c.organization, "status": c.status, "level": c.level,
            "date": c.date, "notes": c.notes, "link": c.link, "updated_at": _iso(c.updated_at)}


@router.get("/career")
async def list_career(kind: str | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    q = select(CareerItem).where(CareerItem.user_id == user.id)
    if kind:
        q = q.where(CareerItem.kind == kind)
    rows = (await db.execute(q.order_by(CareerItem.updated_at.desc()))).scalars().all()
    return {"items": [career_out(c) for c in rows]}


@router.post("/career")
async def create_career(body: CareerIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = CareerItem(user_id=user.id, **body.model_dump())
    db.add(c)
    await db.commit()
    return career_out(c)


@router.patch("/career/{cid}")
async def patch_career(cid: str, body: CareerPatch, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _owned(db, CareerItem, cid, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    c.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return career_out(c)


@router.delete("/career/{cid}")
async def delete_career(cid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, CareerItem, cid, user.id))
    await db.commit()
    return {"deleted": True}


# ------------------------------------------------------------------ notifications
@router.get("/notifications")
async def notifications(unread_only: bool = False, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read.is_(False))
    rows = (await db.execute(q.order_by(Notification.created_at.desc()).limit(50))).scalars().all()
    unread = (await db.execute(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read.is_(False)))).scalar_one()
    return {"items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "read": n.read, "created_at": _iso(n.created_at)} for n in rows],
            "unread": unread}


@router.post("/notifications/read-all")
async def read_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(update(Notification).where(Notification.user_id == user.id).values(read=True))
    await db.commit()
    return {"ok": True}


@router.post("/notifications/{nid}/read")
async def read_one(nid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    n = await _owned(db, Notification, nid, user.id)
    n.read = True
    await db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard")
async def dashboard(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    tasks = (await db.execute(select(Task).where(Task.user_id == user.id, Task.status != "done")
                              .order_by(Task.due_at.is_(None), Task.due_at).limit(50))).scalars().all()
    prio = {"high": 0, "medium": 1, "low": 2}
    priorities = sorted(tasks, key=lambda t: (prio.get(t.priority, 1), _aware(t.due_at) or now + timedelta(days=3650)))[:6]
    reminders = (await db.execute(select(Reminder).where(Reminder.user_id == user.id, Reminder.done.is_(False))
                                  .order_by(Reminder.remind_at).limit(5))).scalars().all()
    recent = (await db.execute(select(Conversation).where(Conversation.user_id == user.id, Conversation.source == "astra")
                               .order_by(Conversation.updated_at.desc()).limit(5))).scalars().all()
    week_ago = now - timedelta(days=7)
    done_week = (await db.execute(select(func.count()).select_from(Task).where(Task.user_id == user.id, Task.status == "done",
                                                                                Task.completed_at >= week_ago))).scalar_one()
    mem_total = (await db.execute(select(func.count()).select_from(Memory).where(Memory.user_id == user.id, Memory.status == "active"))).scalar_one()
    mem_week = (await db.execute(select(func.count()).select_from(Memory).where(Memory.user_id == user.id, Memory.created_at >= week_ago))).scalar_one()
    projects = (await db.execute(select(Project).where(Project.user_id == user.id, Project.status == "active")
                                 .order_by(Project.updated_at.desc()).limit(4))).scalars().all()
    pending = (await db.execute(select(PendingAction).where(PendingAction.user_id == user.id, PendingAction.status == "pending")
                                .order_by(PendingAction.created_at.desc()))).scalars().all()
    # tasks completed per day (last 7 days) for the weekly progress chart
    done = (await db.execute(select(Task.completed_at).where(Task.user_id == user.id, Task.completed_at >= week_ago))).scalars().all()
    days = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]
    per_day = {d.isoformat(): 0 for d in days}
    for c in done:
        k = _aware(c).date().isoformat()
        if k in per_day:
            per_day[k] += 1
    return {
        "user": {"name": user.name, "onboarded": user.onboarded},
        "ai_configured": await ai_configured(db, user.id),
        "priorities": [task_out(t) for t in priorities],
        "open_tasks": len(tasks),
        "reminders": [rem_out(r) for r in reminders],
        "recent_conversations": [convs.conv_dict(c) for c in recent],
        "stats": {"tasks_done_week": done_week, "memories": mem_total, "memories_week": mem_week},
        "projects": [proj_out(p) for p in projects],
        "pending_actions": [action_dict(a) for a in pending],
        "weekly_progress": [{"date": k, "done": v} for k, v in per_day.items()],
    }
