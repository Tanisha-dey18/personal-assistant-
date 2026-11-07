"""Tool registry. Each tool declares a JSON schema (for LLM tool-calling), a handler and
whether it is CONSEQUENTIAL. Consequential tools never run directly from the model: they
create a PendingAction that the user must approve in the UI."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from app.models import PendingAction
from app.services.user_settings import get_user_settings

log = logging.getLogger("astra.tools")


class ToolError(Exception):
    pass


@dataclass
class ToolContext:
    db: Any
    provider: Any
    user: Any
    conversation_id: str | None = None

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(get_user_settings(self.user).get("timezone") or "UTC")
        except Exception:  # noqa: BLE001
            return ZoneInfo("UTC")

    def parse_dt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as e:
            raise ToolError(f"Invalid datetime '{value}'. Use ISO 8601 like 2026-11-08T18:00") from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.tz)
        return dt.astimezone(timezone.utc)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[ToolContext, dict], Awaitable[Any]]
    consequential: bool = False
    summarize: Callable[[dict], str] | None = None
    category: str = "core"
    required_keys: list[str] = field(default_factory=list)

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, properties: dict, required: list[str] | None = None,
         consequential: bool = False, summarize: Callable[[dict], str] | None = None, category: str = "core"):
    def deco(fn):
        REGISTRY[name] = Tool(
            name=name, description=description,
            parameters={"type": "object", "properties": properties, "required": required or []},
            handler=fn, consequential=consequential, summarize=summarize, category=category,
        )
        return fn
    return deco


def all_schemas() -> list[dict]:
    return [t.schema() for t in REGISTRY.values()]


def _to_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, default=str, ensure_ascii=False)[:12000]


async def run_tool(ctx: ToolContext, name: str, args: dict) -> tuple[str, dict]:
    """Returns (text result for the model, event for the UI)."""
    t = REGISTRY.get(name)
    if not t:
        return f"Unknown tool {name}", {"name": name, "status": "error"}
    if t.consequential:
        summary = t.summarize(args) if t.summarize else f"{name}({json.dumps(args)[:200]})"
        action = PendingAction(user_id=ctx.user.id, conversation_id=ctx.conversation_id, tool=name, args=args, summary=summary)
        ctx.db.add(action)
        await ctx.db.commit()
        event = {"name": name, "status": "awaiting_confirmation", "action": action_dict(action)}
        return (json.dumps({"status": "awaiting_user_confirmation", "action_id": action.id, "summary": summary,
                            "note": "NOT executed yet. Tell the user it's prepared and waiting for their confirmation on screen."}), event)
    try:
        result = await t.handler(ctx, args)
        return _to_text(result), {"name": name, "status": "ok"}
    except ToolError as e:
        return f"Tool error: {e}", {"name": name, "status": "error", "error": str(e)}
    except Exception as e:  # noqa: BLE001
        log.exception("tool %s failed", name)
        return f"Tool failed unexpectedly: {e}", {"name": name, "status": "error", "error": str(e)}


async def execute_action(ctx: ToolContext, action: PendingAction) -> str:
    t = REGISTRY.get(action.tool)
    if not t:
        raise ToolError("Tool no longer exists")
    return _to_text(await t.handler(ctx, action.args or {}))


def action_dict(a: PendingAction) -> dict:
    return {"id": a.id, "tool": a.tool, "args": a.args, "summary": a.summary, "status": a.status, "result": a.result,
            "conversation_id": a.conversation_id, "created_at": a.created_at.isoformat() if a.created_at else None}
