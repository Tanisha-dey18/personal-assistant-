"""Encrypted per-user credential storage (OAuth tokens, API keys)."""
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt, encrypt
from app.models import Integration


async def get_integration(db: AsyncSession, user_id: str, provider: str) -> Integration | None:
    r = await db.execute(select(Integration).where(Integration.user_id == user_id, Integration.provider == provider))
    return r.scalar_one_or_none()


async def get_secret(db: AsyncSession, user_id: str, provider: str) -> dict | None:
    integ = await get_integration(db, user_id, provider)
    if not integ or not integ.secret:
        return None
    try:
        return json.loads(decrypt(integ.secret))
    except json.JSONDecodeError:
        return None


async def set_secret(db: AsyncSession, user_id: str, provider: str, secret: dict, meta: dict | None = None) -> Integration:
    integ = await get_integration(db, user_id, provider)
    if not integ:
        integ = Integration(user_id=user_id, provider=provider)
        db.add(integ)
    integ.secret = encrypt(json.dumps(secret))
    if meta is not None:
        integ.meta = meta
    await db.commit()
    return integ


async def delete_integration(db: AsyncSession, user_id: str, provider: str) -> bool:
    integ = await get_integration(db, user_id, provider)
    if not integ:
        return False
    await db.delete(integ)
    await db.commit()
    return True
