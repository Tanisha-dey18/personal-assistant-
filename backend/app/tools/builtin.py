"""Core tools JARVIS can call: memory, tasks, reminders, projects, career, documents,
weather, web search and page reading."""
from __future__ import annotations

import ipaddress
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.core.config import settings
from app.memory import store
from app.memory.vectors import DOCUMENTS, vectors
from app.models import CareerItem, Document, DocumentChunk, Project, Reminder, Task
from app.services.integrations_store import get_secret
from app.tools.registry import ToolContext, ToolError, tool


def _iso(dt):
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- memory
@tool("search_memory", "Search the user's long-term memory semantically. Use when you need details not in context.",
      {"query": {"type": "string"}, "limit": {"type": "integer", "default": 8}}, ["query"], category="memory")
async def search_memory(ctx: ToolContext, a: dict):
    hits = await store.semantic_search(ctx.db, ctx.provider, ctx.user.id, a["query"], limit=min(int(a.get("limit", 8)), 20), min_score=0.15)
    return [{"id": m.id, "content": store.text_of(m), "category": m.category, "type": m.memory_type, "score": round(s, 2)} for m, s in hits] or "No matching memories."


@tool("save_memory", "Save a fact about the user to long-term memory. Use when the user explicitly asks you to remember something.",
      {"content": {"type": "string", "description": "Standalone sentence about the user"},
       "category": {"type": "string", "enum": store.CATEGORIES},
       "memory_type": {"type": "string", "enum": ["confirmed", "assumption", "temporary"]},
       "importance": {"type": "number"}}, ["content", "category"], category="memory")
async def save_memory(ctx: ToolContext, a: dict):
    m, created = await store.create_memory(ctx.db, ctx.provider, ctx.user.id, a["content"], a.get("category"),
                                           a.get("memory_type", "confirmed"), float(a.get("importance", 0.7)), source="manual")
    return {"saved": True, "id": m.id, "deduplicated": not created}


@tool("update_memory", "Correct or update an existing memory (e.g. user says a stored fact is wrong/outdated).",
      {"memory_id": {"type": "string"}, "content": {"type": "string"}}, ["memory_id", "content"], category="memory")
async def update_memory(ctx: ToolContext, a: dict):
    m = await store.get_user_memory(ctx.db, ctx.user.id, a["memory_id"])
    if not m:
        raise ToolError("Memory not found")
    await store.update_memory(ctx.db, ctx.provider, m, content=a["content"], memory_type="confirmed")
    return {"updated": True}


async def _forget(ctx: ToolContext, a: dict):
    m = await store.get_user_memory(ctx.db, ctx.user.id, a["memory_id"])
    if not m:
        raise ToolError("Memory not found")
    await store.delete_memory(ctx.db, m)
    return "Memory deleted."

tool("forget_memory", "Permanently delete a memory. Requires user confirmation.", {"memory_id": {"type": "string"}, "reason": {"type": "string"}},
     ["memory_id"], consequential=True, summarize=lambda a: f"Delete memory {a.get('memory_id')} — {a.get('reason', '')}", category="memory")(_forget)


# ---------------------------------------------------------------- tasks
def _task(t: Task) -> dict:
    return {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority, "due_at": _iso(t.due_at), "notes": t.notes}


@tool("create_task", "Create a task in the user's task list.",
      {"title": {"type": "string"}, "due_at": {"type": "string", "description": "ISO datetime in user's local time, optional"},
       "priority": {"type": "string", "enum": ["low", "medium", "high"]}, "notes": {"type": "string"},
       "project_name": {"type": "string"}}, ["title"], category="productivity")
async def create_task(ctx: ToolContext, a: dict):
    project_id = None
    if a.get("project_name"):
        r = await ctx.db.execute(select(Project).where(Project.user_id == ctx.user.id, Project.name.ilike(a["project_name"])))
        p = r.scalars().first()
        project_id = p.id if p else None
    t = Task(user_id=ctx.user.id, title=a["title"][:300], notes=a.get("notes", ""), priority=a.get("priority", "medium"),
             due_at=ctx.parse_dt(a.get("due_at")), project_id=project_id)
    ctx.db.add(t)
    await ctx.db.commit()
    return {"created": _task(t)}


@tool("list_tasks", "List the user's tasks.", {"status": {"type": "string", "enum": ["open", "done", "all"]}}, category="productivity")
async def list_tasks(ctx: ToolContext, a: dict):
    q = select(Task).where(Task.user_id == ctx.user.id)
    st = a.get("status", "open")
    if st == "open":
        q = q.where(Task.status != "done")
    elif st == "done":
        q = q.where(Task.status == "done")
    rows = (await ctx.db.execute(q.order_by(Task.due_at.is_(None), Task.due_at).limit(50))).scalars().all()
    return [_task(t) for t in rows] or "No tasks."


@tool("update_task", "Update or complete a task.",
      {"task_id": {"type": "string"}, "status": {"type": "string", "enum": ["todo", "doing", "done"]},
       "title": {"type": "string"}, "due_at": {"type": "string"}, "priority": {"type": "string", "enum": ["low", "medium", "high"]}},
      ["task_id"], category="productivity")
async def update_task(ctx: ToolContext, a: dict):
    t = await ctx.db.get(Task, a["task_id"])
    if not t or t.user_id != ctx.user.id:
        raise ToolError("Task not found")
    if a.get("status"):
        t.status = a["status"]
        t.completed_at = datetime.now(timezone.utc) if a["status"] == "done" else None
    if a.get("title"):
        t.title = a["title"]
    if a.get("priority"):
        t.priority = a["priority"]
    if a.get("due_at"):
        t.due_at = ctx.parse_dt(a["due_at"])
    await ctx.db.commit()
    return {"updated": _task(t)}


@tool("create_reminder", "Set a reminder that JARVIS will notify the user about at a given time.",
      {"text": {"type": "string"}, "remind_at": {"type": "string", "description": "ISO datetime in user's local time"}},
      ["text", "remind_at"], category="productivity")
async def create_reminder(ctx: ToolContext, a: dict):
    when = ctx.parse_dt(a["remind_at"])
    r = Reminder(user_id=ctx.user.id, text=a["text"][:500], remind_at=when)
    ctx.db.add(r)
    await ctx.db.commit()
    return {"created": {"id": r.id, "text": r.text, "remind_at": _iso(when)}}


@tool("list_reminders", "List upcoming reminders.", {}, category="productivity")
async def list_reminders(ctx: ToolContext, a: dict):
    rows = (await ctx.db.execute(select(Reminder).where(Reminder.user_id == ctx.user.id, Reminder.done.is_(False))
                                 .order_by(Reminder.remind_at).limit(30))).scalars().all()
    return [{"id": r.id, "text": r.text, "remind_at": _iso(r.remind_at)} for r in rows] or "No upcoming reminders."


# ---------------------------------------------------------------- projects & career
@tool("upsert_project", "Create or update one of the user's projects (matched by name).",
      {"name": {"type": "string"}, "description": {"type": "string"}, "tech_stack": {"type": "array", "items": {"type": "string"}},
       "status": {"type": "string", "enum": ["idea", "active", "paused", "done"]}, "progress": {"type": "integer"},
       "repo_url": {"type": "string"}, "deadline": {"type": "string"}, "notes": {"type": "string", "description": "Appended to docs"}},
      ["name"], category="projects")
async def upsert_project(ctx: ToolContext, a: dict):
    r = await ctx.db.execute(select(Project).where(Project.user_id == ctx.user.id, Project.name.ilike(a["name"])))
    p = r.scalars().first()
    created = p is None
    if created:
        p = Project(user_id=ctx.user.id, name=a["name"][:200])
        ctx.db.add(p)
    for k in ("description", "status", "repo_url"):
        if a.get(k):
            setattr(p, k, a[k])
    if a.get("tech_stack"):
        p.tech_stack = sorted(set((p.tech_stack or []) + a["tech_stack"]))
    if a.get("progress") is not None:
        p.progress = max(0, min(100, int(a["progress"])))
    if a.get("deadline"):
        p.deadline = ctx.parse_dt(a["deadline"])
    if a.get("notes"):
        p.docs = (p.docs + "\n\n" if p.docs else "") + f"[{datetime.now(timezone.utc).date()}] {a['notes']}"
    p.updated_at = datetime.now(timezone.utc)
    await ctx.db.commit()
    return {"created" if created else "updated": {"id": p.id, "name": p.name, "status": p.status, "progress": p.progress}}


@tool("list_projects", "List the user's projects.", {}, category="projects")
async def list_projects(ctx: ToolContext, a: dict):
    rows = (await ctx.db.execute(select(Project).where(Project.user_id == ctx.user.id).order_by(Project.updated_at.desc()))).scalars().all()
    return [{"id": p.id, "name": p.name, "status": p.status, "progress": p.progress, "tech": p.tech_stack,
             "repo": p.repo_url, "updated": _iso(p.updated_at), "deadline": _iso(p.deadline)} for p in rows] or "No projects yet."


@tool("add_career_item", "Track a career item: an internship/job application, internship, achievement, skill or milestone.",
      {"kind": {"type": "string", "enum": ["application", "internship", "achievement", "skill", "milestone"]},
       "title": {"type": "string"}, "organization": {"type": "string"}, "status": {"type": "string"},
       "date": {"type": "string"}, "notes": {"type": "string"}, "level": {"type": "integer", "description": "skill level 0-100"}},
      ["kind", "title"], category="career")
async def add_career_item(ctx: ToolContext, a: dict):
    c = CareerItem(user_id=ctx.user.id, kind=a["kind"], title=a["title"][:300], organization=a.get("organization", ""),
                   status=a.get("status", ""), date=a.get("date"), notes=a.get("notes", ""), level=int(a.get("level") or 0))
    ctx.db.add(c)
    await ctx.db.commit()
    return {"created": {"id": c.id, "kind": c.kind, "title": c.title}}


@tool("list_career_items", "List career tracker items (applications, internships, achievements, skills).",
      {"kind": {"type": "string"}}, category="career")
async def list_career_items(ctx: ToolContext, a: dict):
    q = select(CareerItem).where(CareerItem.user_id == ctx.user.id)
    if a.get("kind"):
        q = q.where(CareerItem.kind == a["kind"])
    rows = (await ctx.db.execute(q.order_by(CareerItem.updated_at.desc()).limit(50))).scalars().all()
    return [{"id": c.id, "kind": c.kind, "title": c.title, "org": c.organization, "status": c.status, "date": c.date} for c in rows] or "Nothing tracked yet."


# ---------------------------------------------------------------- documents
@tool("search_documents", "Search the content of documents the user uploaded (CV, notes, PDFs).",
      {"query": {"type": "string"}}, ["query"], category="documents")
async def search_documents(ctx: ToolContext, a: dict):
    vec = await store.embed_one(ctx.provider, a["query"])
    out = []
    for cid, score, _ in await vectors.search(DOCUMENTS, vec, ctx.user.id, limit=6):
        ch = await ctx.db.get(DocumentChunk, cid)
        if ch and ch.user_id == ctx.user.id:
            d = await ctx.db.get(Document, ch.document_id)
            out.append({"document": d.filename if d else "?", "score": round(score, 2), "text": ch.content})
    return out or "No relevant document content found (has the user uploaded any documents?)."


# ---------------------------------------------------------------- briefing
@tool("daily_briefing", "Gather today's tasks, reminders, deadlines and stale projects to produce a daily summary/plan.", {}, category="productivity")
async def daily_briefing(ctx: ToolContext, a: dict):
    now = datetime.now(timezone.utc)
    tasks = (await ctx.db.execute(select(Task).where(Task.user_id == ctx.user.id, Task.status != "done")
                                  .order_by(Task.due_at.is_(None), Task.due_at).limit(20))).scalars().all()
    rem = (await ctx.db.execute(select(Reminder).where(Reminder.user_id == ctx.user.id, Reminder.done.is_(False),
                                                       Reminder.remind_at <= now + timedelta(days=2)))).scalars().all()
    projects = (await ctx.db.execute(select(Project).where(Project.user_id == ctx.user.id, Project.status == "active"))).scalars().all()
    stale = []
    for p in projects:
        upd = p.updated_at if p.updated_at.tzinfo else p.updated_at.replace(tzinfo=timezone.utc)
        if (now - upd).days >= 10:
            stale.append({"name": p.name, "days_since_update": (now - upd).days})
    done_today = (await ctx.db.execute(select(Task).where(Task.user_id == ctx.user.id, Task.status == "done",
                                                          Task.completed_at >= now - timedelta(days=1)))).scalars().all()
    return {"now_utc": now.isoformat(), "open_tasks": [_task(t) for t in tasks], "reminders_next_48h": [{"text": r.text, "at": _iso(r.remind_at)} for r in rem],
            "stale_projects": stale, "completed_last_24h": [t.title for t in done_today],
            "note": "Calendar/email need the Google integration; call calendar_list_events if connected."}


# ---------------------------------------------------------------- weather (Open-Meteo, no key needed)
WMO = {0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog", 51: "light drizzle", 53: "drizzle",
       55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow",
       80: "rain showers", 81: "rain showers", 82: "violent showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail"}


@tool("get_weather", "Current weather and 3-day forecast for a place.", {"location": {"type": "string"}}, ["location"], category="web")
async def get_weather(ctx: ToolContext, a: dict):
    async with httpx.AsyncClient(timeout=15) as c:
        g = (await c.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": a["location"], "count": 1})).json()
        if not g.get("results"):
            raise ToolError(f"Couldn't find a place called {a['location']}")
        loc = g["results"][0]
        f = (await c.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": "auto", "forecast_days": 3,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"})).json()
    cur = f.get("current", {})
    d = f.get("daily", {})
    return {"place": f"{loc['name']}, {loc.get('country', '')}",
            "now": {"temp_c": cur.get("temperature_2m"), "feels_like_c": cur.get("apparent_temperature"),
                    "humidity": cur.get("relative_humidity_2m"), "wind_kmh": cur.get("wind_speed_10m"), "sky": WMO.get(cur.get("weather_code"), "?")},
            "forecast": [{"date": d["time"][i], "max": d["temperature_2m_max"][i], "min": d["temperature_2m_min"][i],
                          "rain_chance": d["precipitation_probability_max"][i], "sky": WMO.get(d["weather_code"][i], "?")}
                         for i in range(len(d.get("time", [])))]}


# ---------------------------------------------------------------- web
async def _tavily_key(ctx: ToolContext) -> str:
    s = await get_secret(ctx.db, ctx.user.id, "tavily")
    return (s or {}).get("api_key") or settings.TAVILY_API_KEY


@tool("web_search", "Search the web for current information. Returns titles, URLs and snippets.",
      {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 5}}, ["query"], category="web")
async def web_search(ctx: ToolContext, a: dict):
    key = await _tavily_key(ctx)
    if not key:
        raise ToolError("Web search isn't configured. Add a Tavily API key in Integrations (free tier at tavily.com).")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {key}"},
                         json={"api_key": key, "query": a["query"], "max_results": min(int(a.get("max_results", 5)), 10), "include_answer": True})
    if r.status_code != 200:
        raise ToolError(f"Search provider error {r.status_code}: {r.text[:200]}")
    data = r.json()
    return {"answer": data.get("answer"), "results": [{"title": x.get("title"), "url": x.get("url"), "snippet": (x.get("content") or "")[:500]} for x in data.get("results", [])]}


def _assert_public_url(url: str) -> None:
    """Blocks SSRF: only http(s) to public IPs."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ToolError("Only http(s) URLs are allowed")
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror as e:
        raise ToolError("Couldn't resolve that host") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ToolError("That URL points to a private network address — blocked for security.")


@tool("read_webpage", "Fetch a web page and return its readable text (for summarising articles, docs, etc).",
      {"url": {"type": "string"}}, ["url"], category="web")
async def read_webpage(ctx: ToolContext, a: dict):
    url = a["url"]
    _assert_public_url(url)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0 (JARVIS personal assistant)"}) as c:
        for _ in range(4):  # follow redirects manually so each hop is SSRF-checked
            r = await c.get(url)
            if r.is_redirect and r.headers.get("location"):
                url = str(r.url.join(r.headers["location"]))
                _assert_public_url(url)
                continue
            break
    if r.status_code >= 400:
        raise ToolError(f"Page returned HTTP {r.status_code}")
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        raise ToolError(f"Unsupported content type {ctype}")
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else url
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    return {"url": url, "title": title, "text": text[:10000], "truncated": len(text) > 10000}


@tool("current_datetime", "Get the current date and time in the user's timezone.", {}, category="core")
async def current_datetime(ctx: ToolContext, a: dict):
    n = datetime.now(ctx.tz)
    return {"local": n.isoformat(), "weekday": n.strftime("%A"), "timezone": str(ctx.tz)}
