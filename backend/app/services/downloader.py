from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import func, select

from ..config import Settings
from ..db import Database
from ..models import Chapter, DownloadJob, Manga, loads
from ..sources.base import PageRef
from ..sources.registry import SourceRegistry
from . import cbz as cbz_service
from . import library_scan
from .events import Broadcaster
from .fetcher import FetchError, get_image
from .slugs import ensure_within, short_hash, slugify

log = logging.getLogger("comicpro.downloader")
MAX_ATTEMPTS = 2


def _now() -> datetime:
    return datetime.now(UTC)


class DownloadManager:
    """Persistent chapter download queue backed by SQLite."""

    def __init__(
        self,
        *,
        db: Database,
        settings: Settings,
        registry: SourceRegistry,
        client: httpx.AsyncClient,
        events: Broadcaster,
    ) -> None:
        self.db = db
        self.settings = settings
        self.registry = registry
        self.client = client
        self.events = events
        self._wake = asyncio.Event()
        self._cancel: set[int] = set()
        self._workers: list[asyncio.Task] = []
        self._claim_lock = asyncio.Lock()
        self._page_sem = asyncio.Semaphore(max(1, settings.page_concurrency))
        self._running = False

    # --------------------------------------------------------------- lifecycle
    async def recover(self) -> int:
        """Requeue jobs that were interrupted by a restart."""
        async with self.db.session() as session:
            running = (
                (await session.execute(select(DownloadJob).where(DownloadJob.status == "running")))
                .scalars()
                .all()
            )
            for job in running:
                job.status = "queued"
            await session.commit()
        return len(running)

    async def start(self) -> None:
        self._running = True
        await self.recover()
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"download-worker-{index}")
            for index in range(max(1, self.settings.download_concurrency))
        ]
        self._wake.set()

    async def stop(self) -> None:
        self._running = False
        self._wake.set()
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await worker
        self._workers.clear()
        async with self.db.session() as session:
            running = (
                (await session.execute(select(DownloadJob).where(DownloadJob.status == "running")))
                .scalars()
                .all()
            )
            for job in running:
                job.status = "queued"
            await session.commit()

    # ---------------------------------------------------------------- enqueue
    async def enqueue(self, chapter_ids: list[int]) -> list[dict]:
        unique = list(dict.fromkeys(chapter_ids))
        created: list[dict] = []
        async with self.db.session() as session:
            chapters = (
                (await session.execute(select(Chapter).where(Chapter.id.in_(unique)))).scalars().all()
            )
            existing = (
                (
                    await session.execute(
                        select(DownloadJob).where(DownloadJob.chapter_id.in_([c.id for c in chapters]))
                    )
                )
                .scalars()
                .all()
            )
            by_chapter = {job.chapter_id: job for job in existing}
            for chapter in chapters:
                job = by_chapter.get(chapter.id)
                if job is not None:
                    if job.status in ("error", "canceled"):
                        job.status = "queued"
                        job.attempts = 0
                        job.pages_done = 0
                        job.error = ""
                    created.append({"job_id": job.id, "chapter_id": chapter.id, "status": job.status})
                    continue
                job = DownloadJob(manga_id=chapter.manga_id, chapter_id=chapter.id)
                session.add(job)
                await session.flush()
                created.append({"job_id": job.id, "chapter_id": chapter.id, "status": job.status})
            await session.commit()
        self._wake.set()
        return created

    async def cancel(self, job_id: int) -> bool:
        self._cancel.add(job_id)
        async with self.db.session() as session:
            job = await session.get(DownloadJob, job_id)
            if job is None:
                return False
            if job.status == "queued":
                job.status = "canceled"
                await session.commit()
                self._publish(job)
            return True

    async def retry(self, job_id: int) -> bool:
        self._cancel.discard(job_id)
        async with self.db.session() as session:
            job = await session.get(DownloadJob, job_id)
            if job is None:
                return False
            job.status = "queued"
            job.attempts = 0
            job.pages_done = 0
            job.error = ""
            await session.commit()
            self._publish(job)
        self._wake.set()
        return True

    async def stats(self) -> dict:
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(DownloadJob.status, func.count()).group_by(DownloadJob.status)
                )
            ).all()
        counts = {status: count for status, count in rows}
        return {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "done": counts.get("done", 0),
            "partial": counts.get("partial", 0),
            "error": counts.get("error", 0),
            "canceled": counts.get("canceled", 0),
        }

    # ------------------------------------------------------------------ worker
    async def _worker(self, index: int) -> None:
        log.info("download worker %s started", index)
        while self._running:
            job_id = await self._claim()
            if job_id is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=5.0)
                except TimeoutError:
                    pass
                continue
            try:
                await self._run(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep the worker alive
                log.warning("download job %s failed: %s", job_id, exc)
                await self._fail(job_id, exc)

    async def _claim(self) -> int | None:
        async with self._claim_lock:
            async with self.db.session() as session:
                job = (
                    (
                        await session.execute(
                            select(DownloadJob)
                            .where(DownloadJob.status == "queued")
                            .order_by(DownloadJob.id)
                            .limit(1)
                        )
                    )
                    .scalars()
                    .first()
                )
                if job is None:
                    return None
                job.status = "running"
                job.updated_at = _now()
                await session.commit()
                self._publish(job)
                return job.id

    async def _run(self, job_id: int) -> None:
        async with self.db.session() as session:
            job = await session.get(DownloadJob, job_id)
            if job is None:
                return
            chapter = await session.get(Chapter, job.chapter_id)
            manga = await session.get(Manga, job.manga_id)
            if chapter is None or manga is None:
                raise RuntimeError("chapter or manga row disappeared")

            source_id = manga.source_id
            chapter_url = chapter.url
            chapter_title = chapter.title
            chapter_number = chapter.number
            series_title = manga.title
            series_description = manga.description
            author = manga.author
            tags = loads(manga.tags, [])
            manga_key = manga.source_key
            chapter_ids = (
                (
                    await session.execute(
                        select(Chapter.id).where(Chapter.manga_id == manga.id).order_by(Chapter.id)
                    )
                )
                .scalars()
                .all()
            )
            order_index = (list(chapter_ids).index(chapter.id) + 1) if chapter.id in chapter_ids else 1

        source = self.registry.get(source_id)
        pages = await source.get_pages(chapter_url)
        if not pages:
            raise RuntimeError("source returned no pages for this chapter")

        series_slug = f"{slugify(series_title, 60)}-{short_hash(manga_key, 6)}"
        target = self.settings.library_dir / source_id / series_slug
        target = ensure_within(self.settings.library_dir, target)
        target_file = target / f"{order_index:04d} {slugify(chapter_title, 70)}.cbz"
        parts_dir = target / ".parts" / f"{order_index:04d}"
        parts_dir.mkdir(parents=True, exist_ok=True)

        page_total = len(pages)
        await self._update_job(job_id, pages_total=page_total, pages_done=0, error="")
        page_files: list[Path] = []
        missing: list[int] = []
        error_note = ""
        batch_size = max(1, self.settings.page_concurrency)

        for start in range(0, page_total, batch_size):
            if job_id in self._cancel:
                await self._mark_canceled(job_id)
                return
            chunk = [
                (number, pages[number - 1])
                for number in range(start + 1, min(start + batch_size, page_total) + 1)
            ]
            pending: list[tuple[int, PageRef]] = []
            for number, page in chunk:
                existing = sorted(parts_dir.glob(f"p{number:04d}.*"))
                if existing:
                    page_files.append(existing[0])
                else:
                    pending.append((number, page))

            if pending:
                results = await asyncio.gather(
                    *(self._fetch_with_slot(page) for _number, page in pending),
                    return_exceptions=True,
                )
                for (number, _page), result in zip(pending, results, strict=False):
                    if isinstance(result, asyncio.CancelledError):
                        raise result
                    if isinstance(result, Exception):
                        log.info("page %s of job %s failed: %s", number, job_id, result)
                        missing.append(number)
                        error_note = f"page {number}: {result}"
                        continue
                    data, ext = result
                    path = parts_dir / f"p{number:04d}.{ext}"
                    path.write_bytes(data)
                    page_files.append(path)

            await self._update_job(job_id, pages_done=chunk[-1][0], error=error_note)

        if not page_files:
            raise RuntimeError("all page downloads failed")

        comic_info = cbz_service.comic_info_xml(
            series=series_title,
            number=str(chapter_number) if chapter_number is not None else str(order_index),
            title=chapter_title,
            summary=series_description,
            writer=author,
            publisher=f"ComicPro · {source_id}",
            page_count=len(page_files),
            web=chapter_url,
            language=source.lang,
            tags=tags,
            notes=("missing pages: " + ", ".join(map(str, missing))) if missing else "",
        )
        metadata = {
            "source_id": source_id,
            "manga_key": manga_key,
            "chapter_key": chapter_url,
            "chapter_title": chapter_title,
            "pages_missing": missing,
            "downloaded_at": _now().isoformat(),
        }
        cbz_service.write_cbz(target_file, page_files, comic_info=comic_info, metadata=metadata)
        shutil.rmtree(parts_dir, ignore_errors=True)

        status = "partial" if missing else "done"
        async with self.db.session() as session:
            chapter = await session.get(Chapter, job.chapter_id)
            job = await session.get(DownloadJob, job_id)
            if chapter is not None:
                chapter.downloaded = True
                chapter.page_count = len(page_files)
            if job is not None:
                job.status = "canceled" if job_id in self._cancel else status
                job.pages_done = page_total
                job.error = job.error[:1000]
                job.target_path = str(target_file.relative_to(self.settings.library_dir))
                job.updated_at = _now()
                self._publish(job)
            await session.commit()

        await library_scan.sync_library(self.db, self.settings.library_dir)
        self._cancel.discard(job_id)

    async def _fetch_with_slot(self, page: PageRef) -> tuple[bytes, str]:
        async with self._page_sem:
            return await self._fetch_page(page)

    async def _fetch_page(self, page: PageRef) -> tuple[bytes, str]:
        if page.inline is not None:
            return page.inline, page.ext
        data, ext, _media = await get_image(
            self.client,
            page.url,
            headers=page.headers,
            max_bytes=self.settings.max_image_mb * 1024 * 1024,
        )
        return data, ext

    # ------------------------------------------------------------------ helpers
    async def _update_job(self, job_id: int, **fields) -> None:
        async with self.db.session() as session:
            job = await session.get(DownloadJob, job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = _now()
            await session.commit()
            self._publish(job)

    async def _mark_canceled(self, job_id: int) -> None:
        async with self.db.session() as session:
            job = await session.get(DownloadJob, job_id)
            if job is not None:
                job.status = "canceled"
                job.updated_at = _now()
                await session.commit()
                self._publish(job)
        self._cancel.discard(job_id)

    async def _fail(self, job_id: int, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {exc}" if not isinstance(exc, (FetchError, RuntimeError)) else str(exc)
        async with self.db.session() as session:
            job = await session.get(DownloadJob, job_id)
            if job is None:
                return
            job.attempts += 1
            job.error = message[:1500]
            if job.attempts < MAX_ATTEMPTS and job.status != "canceled":
                job.status = "queued"
            else:
                job.status = "error"
            job.updated_at = _now()
            await session.commit()
            self._publish(job)
        self._wake.set()

    def _publish(self, job: DownloadJob) -> None:
        self.events.publish(
            {
                "type": "job",
                "job": {
                    "id": job.id,
                    "chapter_id": job.chapter_id,
                    "manga_id": job.manga_id,
                    "status": job.status,
                    "pages_done": job.pages_done,
                    "pages_total": job.pages_total,
                    "error": job.error,
                },
            }
        )
