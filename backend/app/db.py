from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


class Database:
    """Async SQLite database with WAL and a tiny schema bootstrap."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{path.as_posix()}",
            connect_args={"timeout": 30.0},
            pool_pre_ping=True,
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
            await conn.exec_driver_sql("PRAGMA busy_timeout=5000")
            await conn.run_sync(Base.metadata.create_all)
            version = (await conn.exec_driver_sql("PRAGMA user_version")).scalar() or 0
            if version < self.SCHEMA_VERSION:
                await conn.exec_driver_sql(f"PRAGMA user_version={self.SCHEMA_VERSION}")

    def session(self) -> AsyncSession:
        return self.sessions()

    async def close(self) -> None:
        await self.engine.dispose()


async def session_scope(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.session() as session:
        yield session
