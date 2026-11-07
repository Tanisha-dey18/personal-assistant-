from app.ai.provider import Usage
from app.models import UsageLog


def log_usage(db, user_id: str, kind: str, usage: Usage | None) -> None:
    """Adds a usage row to the session (caller commits)."""
    if not usage:
        return
    db.add(UsageLog(user_id=user_id, kind=kind, model=usage.model, prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens))
