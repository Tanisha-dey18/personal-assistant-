"""Google Calendar + Gmail via OAuth 2.0. Tokens are stored encrypted per user.
Reading is direct; creating events and sending email require user confirmation."""
from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.integrations_store import get_secret, set_secret
from app.tools.registry import ToolContext, ToolError, tool

SCOPES = [
    "openid", "email",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
TOKEN_URL = "https://oauth2.googleapis.com/token"


def google_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def auth_url(state: str) -> str:
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": settings.GOOGLE_CLIENT_ID, "redirect_uri": settings.google_redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "state": state, "include_granted_scopes": "true"})


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(TOKEN_URL, data={"code": code, "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET,
                                          "redirect_uri": settings.google_redirect_uri, "grant_type": "authorization_code"})
        r.raise_for_status()
        tok = r.json()
        info = (await c.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {tok['access_token']}"})).json()
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    tok["email"] = info.get("email")
    return tok


async def access_token(ctx: ToolContext) -> str:
    tok = await get_secret(ctx.db, ctx.user.id, "google")
    if not tok:
        raise ToolError("Google isn't connected. Ask the user to connect Google in Integrations.")
    if tok.get("expires_at", 0) > time.time():
        return tok["access_token"]
    if not tok.get("refresh_token"):
        raise ToolError("Google session expired — please reconnect Google in Integrations.")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(TOKEN_URL, data={"client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET,
                                          "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise ToolError("Google token refresh failed — please reconnect Google in Integrations.")
    new = r.json()
    tok["access_token"] = new["access_token"]
    tok["expires_at"] = time.time() + int(new.get("expires_in", 3600)) - 60
    await set_secret(ctx.db, ctx.user.id, "google", tok, meta={"email": tok.get("email")})
    return tok["access_token"]


async def _gget(ctx, url, params=None):
    tok = await access_token(ctx)
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(url, params=params, headers={"Authorization": f"Bearer {tok}"})
    if r.status_code >= 400:
        raise ToolError(f"Google API error {r.status_code}: {r.text[:200]}")
    return r.json()


async def _gpost(ctx, url, body):
    tok = await access_token(ctx)
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(url, json=body, headers={"Authorization": f"Bearer {tok}"})
    if r.status_code >= 400:
        raise ToolError(f"Google API error {r.status_code}: {r.text[:200]}")
    return r.json()


@tool("calendar_list_events", "List upcoming Google Calendar events.", {"days": {"type": "integer", "default": 7}}, category="google")
async def calendar_list_events(ctx: ToolContext, a: dict):
    now = datetime.now(timezone.utc)
    data = await _gget(ctx, "https://www.googleapis.com/calendar/v3/calendars/primary/events", {
        "timeMin": now.isoformat(), "timeMax": (now + timedelta(days=int(a.get("days", 7)))).isoformat(),
        "singleEvents": "true", "orderBy": "startTime", "maxResults": 50})
    return [{"title": e.get("summary"), "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
             "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"), "location": e.get("location")}
            for e in data.get("items", [])] or "No events in that range."


async def _create_event(ctx: ToolContext, a: dict):
    start = ctx.parse_dt(a["start"])
    end = ctx.parse_dt(a.get("end")) if a.get("end") else start + timedelta(minutes=int(a.get("duration_minutes", 60)))
    ev = await _gpost(ctx, "https://www.googleapis.com/calendar/v3/calendars/primary/events", {
        "summary": a["title"], "description": a.get("description", ""), "location": a.get("location", ""),
        "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}})
    return {"created": True, "link": ev.get("htmlLink"), "title": ev.get("summary")}

tool("calendar_create_event", "Create a Google Calendar event (requires user confirmation).",
     {"title": {"type": "string"}, "start": {"type": "string", "description": "ISO local datetime"}, "end": {"type": "string"},
      "duration_minutes": {"type": "integer"}, "description": {"type": "string"}, "location": {"type": "string"}},
     ["title", "start"], consequential=True, category="google",
     summarize=lambda a: f"Create calendar event “{a.get('title')}” at {a.get('start')}")(_create_event)


@tool("gmail_search", "Search/list the user's recent Gmail messages (subject, sender, snippet).",
      {"query": {"type": "string", "description": "Gmail search syntax, e.g. 'is:unread newer_than:2d'"}, "max_results": {"type": "integer", "default": 10}},
      category="google")
async def gmail_search(ctx: ToolContext, a: dict):
    data = await _gget(ctx, "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                       {"q": a.get("query", "newer_than:3d"), "maxResults": min(int(a.get("max_results", 10)), 25)})
    out = []
    for m in data.get("messages", []):
        msg = await _gget(ctx, f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}",
                          [("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject"), ("metadataHeaders", "Date")])
        h = {x["name"]: x["value"] for x in msg.get("payload", {}).get("headers", [])}
        out.append({"from": h.get("From"), "subject": h.get("Subject"), "date": h.get("Date"), "snippet": msg.get("snippet")})
    return out or "No matching emails."


async def _send_email(ctx: ToolContext, a: dict):
    msg = EmailMessage()
    msg["To"] = a["to"]
    msg["Subject"] = a["subject"]
    msg.set_content(a["body"])
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    r = await _gpost(ctx, "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", {"raw": raw})
    return {"sent": True, "id": r.get("id"), "to": a["to"]}

tool("gmail_send", "Send an email from the user's Gmail (requires user confirmation). Draft the full text first.",
     {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, ["to", "subject", "body"],
     consequential=True, category="google",
     summarize=lambda a: f"Send email to {a.get('to')} — “{a.get('subject')}”\n\n{a.get('body', '')[:1500]}")(_send_email)
