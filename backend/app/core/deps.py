"""FastAPI dependencies: current user + rate limiting."""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.core.db import get_db
from app.core.security import decode_token
from app.models import User

bearer = HTTPBearer(auto_error=False)


async def user_from_token(token: str, db: AsyncSession) -> User | None:
    data = decode_token(token)
    if not data:
        return None
    return await db.get(User, data["sub"])


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = await user_from_token(creds.credentials, db)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return user


async def check_rate(key: str, limit: int) -> None:
    n = await cache.incr(f"rl:{key}", 60)
    if n > limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Slow down a little — rate limit reached. Try again in a minute.")


async def rate_limited_user(user: User = Depends(get_current_user)) -> User:
    await check_rate(f"user:{user.id}", settings.RATE_LIMIT_PER_MINUTE)
    return user


async def auth_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    await check_rate(f"auth:{ip}", settings.AUTH_RATE_LIMIT_PER_MINUTE)
