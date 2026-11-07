"""Per-user preferences with sensible defaults. Stored as JSON on the user row."""
from copy import deepcopy

from app.core.config import settings

DEFAULTS = {
    "model": None,  # None = server default (CHAT_MODEL)
    "temperature": 0.7,
    "default_mode": "auto",
    "personality": {
        "sarcasm": 0.4,  # 0..1
        "verbosity": "balanced",  # concise | balanced | detailed
        "hinglish": True,
        "custom_instructions": "",
    },
    "voice": {"voice": settings.DEFAULT_VOICE, "speed": 1.0, "auto_speak": False, "hands_free": False},
    "memory": {"auto_save": True, "ask_before_sensitive": True, "max_context_memories": 12},
    "proactive": {
        "enabled": True,
        "reminders": True,
        "task_deadlines": True,
        "stale_projects": True,
        "career_followups": True,
        "weekly_report": True,
    },
    "learning": {"level": "intermediate", "style": "intuition first, then math, then code"},
    "location": "",
    "timezone": "Asia/Kolkata",
}


def _merge(base: dict, over: dict) -> dict:
    out = deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def get_user_settings(user) -> dict:
    return _merge(DEFAULTS, user.settings or {})


def update_user_settings(user, patch: dict) -> dict:
    merged = _merge(get_user_settings(user), patch)
    user.settings = merged
    return merged
