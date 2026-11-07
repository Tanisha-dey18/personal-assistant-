"""Database engine + session. SQLAlchemy async works with both PostgreSQL (asyncpg) and SQLite (aiosqlite)."""
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


_url = settings.async_database_url
if _url.startswith("sqlite"):
    Path(_url.split(":///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(_url, connect_args={"check_same_thread": False})

    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # enforce ON DELETE CASCADE in SQLite
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()
else:
    # pool_pre_ping + pool_recycle survive Neon scale-to-zero (idle connections get dropped).
    # If someone still points at a -pooler (PgBouncer) host, disable asyncpg's statement cache.
    _args = {"statement_cache_size": 0, "prepared_statement_cache_size": 0} if "-pooler" in _url else {}
    engine = create_async_engine(_url, pool_pre_ping=True, pool_recycle=240, pool_size=5, max_overflow=5, connect_args=_args)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
