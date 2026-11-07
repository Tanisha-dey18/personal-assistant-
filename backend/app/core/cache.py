"""Tiny cache abstraction: Redis when REDIS_URL is set, in-process dict otherwise.
Used for rate limiting and short-lived data (OAuth state, etc.)."""
import time

from app.core.config import settings


class MemoryCache:
    def __init__(self):
        self._data: dict[str, tuple[float, str]] = {}

    async def incr(self, key: str, ttl: int) -> int:
        now = time.time()
        exp, val = self._data.get(key, (0, "0"))
        if exp < now:
            val = "0"
            exp = now + ttl
        n = int(val) + 1
        self._data[key] = (exp, str(n))
        if len(self._data) > 50_000:  # crude cleanup
            self._data = {k: v for k, v in self._data.items() if v[0] > now}
        return n

    async def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if not item or item[0] < time.time():
            return None
        return item[1]

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._data[key] = (time.time() + ttl, value)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


class RedisCache:
    def __init__(self, url: str):
        import redis.asyncio as redis

        self.r = redis.from_url(url, decode_responses=True)

    async def incr(self, key: str, ttl: int) -> int:
        pipe = self.r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        n, _ = await pipe.execute()
        return int(n)

    async def get(self, key: str) -> str | None:
        return await self.r.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        await self.r.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self.r.delete(key)


cache = RedisCache(settings.REDIS_URL) if settings.REDIS_URL else MemoryCache()
