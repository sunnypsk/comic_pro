from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from ..deps import SessionDep
from ..models import Chapter, LibraryItem, Manga, ReadingProgress
from ..schemas import ProgressIn
from ..services.slugs import b64e

router = APIRouter(tags=["progress"])


@router.post("/progress")
async def save_progress(payload: ProgressIn, session: SessionDep) -> dict:
    if payload.page < 1:
        raise HTTPException(status_code=400, detail={"code": "BAD_PAGE", "message": "page must be >= 1"})
    row = (
        await session.execute(
            select(ReadingProgress).where(
                ReadingProgress.kind == payload.kind, ReadingProgress.item_ref == payload.item_ref
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ReadingProgress(kind=payload.kind, item_ref=payload.item_ref)
        session.add(row)
    row.chapter_ref = payload.chapter_ref
    row.page = payload.page
    row.page_total = payload.page_total
    row.updated_at = datetime.now(UTC)
    await session.commit()
    return {"ok": True}


@router.get("/progress")
async def get_progress(session: SessionDep, kind: str, item_ref: str) -> dict:
    row = (
        await session.execute(
            select(ReadingProgress).where(
                ReadingProgress.kind == kind, ReadingProgress.item_ref == item_ref
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"page": 1, "chapter_ref": "", "page_total": 0}
    return {"page": row.page, "chapter_ref": row.chapter_ref, "page_total": row.page_total}


@router.get("/home")
async def home(request: Request, session: SessionDep) -> dict:
    proxy = request.app.state.image_proxy
    rows = (
        (await session.execute(select(ReadingProgress).order_by(ReadingProgress.updated_at.desc()).limit(24)))
        .scalars()
        .all()
    )

    continue_items = []
    for row in rows:
        if len(continue_items) >= 8:
            break
        entry = await _progress_entry(request, session, proxy, row)
        if entry:
            continue_items.append(entry)

    items = (
        (await session.execute(select(LibraryItem).order_by(LibraryItem.added_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    recent: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if item.series_dir in seen:
            continue
        seen.add(item.series_dir)
        series_id = b64e(item.series_dir)
        recent.append(
            {
                "id": series_id,
                "title": item.series_title,
                "chapter_count": 1,
                "cover": f"/api/library/{series_id}/cover?v={int(item.mtime)}",
                "href": f"/library/{series_id}",
            }
        )
        if len(recent) >= 8:
            break

    downloader = request.app.state.downloader
    return {
        "continue": continue_items,
        "recent": recent,
        "queue": await downloader.stats(),
    }


async def _progress_entry(request: Request, session, proxy, row: ReadingProgress) -> dict | None:
    if row.kind == "online":
        source_id, _, key = row.item_ref.partition(":")
        manga = (
            await session.execute(
                select(Manga).where(Manga.source_id == source_id, Manga.source_key == key)
            )
        ).scalar_one_or_none()
        if manga is None:
            return None
        chapter = None
        if row.chapter_ref.isdigit():
            chapter = await session.get(Chapter, int(row.chapter_ref))
        cover = manga.cover_url
        if cover.startswith("http"):
            cover = proxy.signed_url(manga.source_id, cover)
        return {
            "kind": "online",
            "title": manga.title,
            "subtitle": chapter.title if chapter else "",
            "cover": cover,
            "href": (
                f"/reader/online/{manga.id}/{chapter.id}"
                if chapter is not None
                else f"/manga/{manga.source_id}/{manga.source_key}"
            ),
            "page": row.page,
            "page_total": row.page_total,
            "updated_at": row.updated_at.isoformat(),
        }

    items = list(
        (
            await session.execute(
                select(LibraryItem)
                .where(LibraryItem.series_dir == row.item_ref)
                .order_by(LibraryItem.chapter_index, LibraryItem.rel_path)
            )
        )
        .scalars()
        .all()
    )
    if not items:
        return None
    chapter_index = min(int(row.chapter_ref) if row.chapter_ref.isdigit() else 0, len(items) - 1)
    series_id = b64e(row.item_ref)
    return {
        "kind": "library",
        "title": items[chapter_index].series_title,
        "subtitle": items[chapter_index].chapter_title,
        "cover": f"/api/library/{series_id}/cover?v={int(items[chapter_index].mtime)}",
        "href": f"/reader/library/{series_id}/{chapter_index}",
        "page": row.page,
        "page_total": row.page_total,
        "updated_at": row.updated_at.isoformat(),
    }
