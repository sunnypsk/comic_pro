from __future__ import annotations

import asyncio
import contextlib
import logging
import random

from sqlalchemy import select

from ..config import Settings
from ..db import Database
from ..models import Chapter, Manga, utcnow
from ..sources.registry import SourceRegistry
from .downloader import DownloadManager

log = logging.getLogger("comicpro.subscriptions")


class Subscriptions:
    """Periodically refresh followed series and enqueue new chapters."""

    def __init__(
        self,
        *,
        db: Database,
        settings: Settings,
        registry: SourceRegistry,
        downloader: DownloadManager,
        interval_min: int = 360,
    ) -> None:
        self.db = db
        self.settings = settings
        self.registry = registry
        self.downloader = downloader
        self.interval_min = max(0, interval_min)
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if self.interval_min <= 0:
            return
        self._task = asyncio.create_task(self._loop(), name="subscriptions")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(90)
        while not self._stopping:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("subscription pass failed: %s", exc)
            delay = max(60, self.interval_min * 60) * random.uniform(0.9, 1.1)
            await asyncio.sleep(delay)

    async def run_once(self) -> dict:
        async with self.db.session() as session:
            mangas = (
                (await session.execute(select(Manga).where(Manga.follow.is_(True)))).scalars().all()
            )
        checked = 0
        new_chapters = 0
        for manga in mangas:
            try:
                source = self.registry.get(manga.source_id)
                refs = await source.get_chapters(manga.source_key)
            except Exception as exc:  # noqa: BLE001
                log.info("refresh failed for manga %s: %s", manga.id, exc)
                continue
            checked += 1
            new_ids: list[int] = []
            async with self.db.session() as session:
                existing = {
                    row.source_key: row
                    for row in (
                        (await session.execute(select(Chapter).where(Chapter.manga_id == manga.id)))
                        .scalars()
                        .all()
                    )
                }
                for ref in refs:
                    chapter = existing.get(ref.key)
                    if chapter is None:
                        chapter = Chapter(
                            manga_id=manga.id,
                            source_key=ref.key,
                            title=ref.title,
                            url=ref.url,
                            number=ref.number,
                            published_at=ref.published_at,
                        )
                        session.add(chapter)
                        await session.flush()
                        new_ids.append(chapter.id)
                    else:
                        chapter.title = ref.title
                        chapter.url = ref.url
                        chapter.number = ref.number
                fresh = await session.get(Manga, manga.id)
                if fresh is not None:
                    fresh.last_synced_at = utcnow()
                await session.commit()
            new_chapters += len(new_ids)
            if manga.auto_download and new_ids:
                await self.downloader.enqueue(list(dict.fromkeys(new_ids)))
        return {"checked": checked, "new_chapters": new_chapters}
