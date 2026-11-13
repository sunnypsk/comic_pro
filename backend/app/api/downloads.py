from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..deps import SessionDep
from ..models import Chapter, DownloadJob, Manga
from ..schemas import DownloadIn

router = APIRouter(prefix="/downloads", tags=["downloads"])


def _job_payload(job: DownloadJob, chapter: Chapter | None, manga: Manga | None) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "pages_done": job.pages_done,
        "pages_total": job.pages_total,
        "progress": round(job.pages_done / job.pages_total, 3) if job.pages_total else 0.0,
        "error": job.error,
        "attempts": job.attempts,
        "target_path": job.target_path,
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "updated_at": job.updated_at.isoformat() if job.updated_at else "",
        "chapter": (
            {"id": chapter.id, "title": chapter.title, "number": chapter.number} if chapter else None
        ),
        "manga": (
            {
                "id": manga.id,
                "title": manga.title,
                "source_id": manga.source_id,
                "key": manga.source_key,
            }
            if manga
            else None
        ),
    }


@router.post("")
async def enqueue(payload: DownloadIn, request: Request, session: SessionDep) -> dict:
    ids = list(payload.chapter_ids)
    if payload.all:
        if payload.manga_id is None:
            raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "manga_id required"})
        ids = list(
            (
                await session.execute(
                    select(Chapter.id).where(
                        Chapter.manga_id == payload.manga_id, Chapter.downloaded.is_(False)
                    )
                )
            )
            .scalars()
            .all()
        )
    if not ids:
        raise HTTPException(status_code=400, detail={"code": "NO_CHAPTERS", "message": "nothing to download"})
    downloader = request.app.state.downloader
    jobs = await downloader.enqueue(ids)
    return {"jobs": jobs, "count": len(jobs)}


@router.get("")
async def list_jobs(
    request: Request,
    session: SessionDep,
    status: str = Query("", description="filter by status"),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    stmt = (
        select(DownloadJob, Chapter, Manga)
        .join(Chapter, Chapter.id == DownloadJob.chapter_id, isouter=True)
        .join(Manga, Manga.id == DownloadJob.manga_id, isouter=True)
        .order_by(DownloadJob.created_at.desc(), DownloadJob.id.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(DownloadJob.status == status)
    rows = (await session.execute(stmt)).all()
    stats = await request.app.state.downloader.stats()
    return {
        "stats": stats,
        "jobs": [_job_payload(job, chapter, manga) for job, chapter, manga in rows],
    }


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    downloader = request.app.state.downloader
    broadcaster = request.app.state.events
    queue = broadcaster.subscribe()

    async def generator():
        try:
            snapshot = await downloader.stats()
            yield f"event: hello\ndata: {json.dumps({'stats': snapshot})}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(payload)}\n\n"
                if await request.is_disconnected():
                    break
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/{job_id}/cancel")
async def cancel(job_id: int, request: Request) -> dict:
    ok = await request.app.state.downloader.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "job not found"})
    return {"ok": True}


@router.post("/{job_id}/retry")
async def retry(job_id: int, request: Request) -> dict:
    ok = await request.app.state.downloader.retry(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "job not found"})
    return {"ok": True}
