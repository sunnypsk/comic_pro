from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from ..deps import RegistryDep, SessionDep
from ..models import Chapter, Manga, ReadingProgress
from ..services.http_client import SourceError
from ..services.slugs import b64d

router = APIRouter(prefix="/read", tags=["reader"])


def _chapter_ref(index: int, chapters: list[Chapter]) -> dict | None:
    if index < 0 or index >= len(chapters):
        return None
    chapter = chapters[index]
    return {"id": chapter.id, "title": chapter.title}


def _progress_of(rows: list[ReadingProgress], kind: str, item_ref: str) -> dict:
    row = next((item for item in rows if item.kind == kind and item.item_ref == item_ref), None)
    if row is None:
        return {"page": 1, "page_total": 0}
    return {"page": row.page, "page_total": row.page_total}


async def _progress_rows(session) -> list[ReadingProgress]:
    return list((await session.execute(select(ReadingProgress))).scalars().all())


@router.get("/online")
async def online_manifest(
    request: Request,
    session: SessionDep,
    registry: RegistryDep,
    manga_id: int,
    chapter_id: int,
) -> dict:
    manga = await session.get(Manga, manga_id)
    chapter = await session.get(Chapter, chapter_id)
    if manga is None or chapter is None or chapter.manga_id != manga.id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "chapter not found"})
    try:
        source = registry.get(manga.source_id)
        pages = await source.get_pages(chapter.url)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail={"code": exc.code, "message": exc.message}) from exc
    if not pages:
        raise HTTPException(
            status_code=502, detail={"code": "NO_PAGES", "message": "source returned no pages"}
        )

    chapters = list(
        (
            await session.execute(select(Chapter).where(Chapter.manga_id == manga.id).order_by(Chapter.id))
        )
        .scalars()
        .all()
    )
    position = next((index for index, item in enumerate(chapters) if item.id == chapter.id), -1)
    proxy = request.app.state.image_proxy
    page_urls = [
        page.url if page.inline is not None else proxy.signed_url(manga.source_id, page.url)
        for page in pages
    ]
    item_ref = f"{manga.source_id}:{manga.source_key}"
    progress = _progress_of(await _progress_rows(session), "online", item_ref)
    return {
        "kind": "online",
        "series": {"id": manga.id, "title": manga.title, "source_id": manga.source_id},
        "chapter": {"id": chapter.id, "title": chapter.title, "number": chapter.number},
        "item_ref": item_ref,
        "chapter_ref": str(chapter.id),
        "total": len(page_urls),
        "pages": [{"n": index + 1, "url": url} for index, url in enumerate(page_urls)],
        "prev": _chapter_ref(position - 1, chapters),
        "next": _chapter_ref(position + 1, chapters),
        "direction": source.direction,
        "progress": progress["page"],
    }


@router.get("/library")
async def library_manifest(
    request: Request,
    session: SessionDep,
    series: str,
    chapter: int = Query(0, ge=0),
) -> dict:
    from ..models import LibraryItem

    try:
        series_dir = b64d(series)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"code": "BAD_ID", "message": "invalid series id"}) from exc
    items = list(
        (
            await session.execute(
                select(LibraryItem)
                .where(LibraryItem.series_dir == series_dir)
                .order_by(LibraryItem.chapter_index, LibraryItem.rel_path)
            )
        )
        .scalars()
        .all()
    )
    if not items or chapter >= len(items):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "chapter not found"})
    item = items[chapter]
    page_total = item.page_count
    progress = _progress_of(await _progress_rows(session), "library", series_dir)
    return {
        "kind": "library",
        "series": {"id": series, "title": item.series_title},
        "chapter": {"id": chapter, "title": item.chapter_title, "number": chapter + 1},
        "item_ref": series_dir,
        "chapter_ref": str(chapter),
        "total": page_total,
        "pages": [
            {"n": number, "url": f"/api/library/{series}/chapters/{chapter}/pages/{number}"}
            for number in range(1, page_total + 1)
        ],
        "prev": {"id": chapter - 1, "title": items[chapter - 1].chapter_title} if chapter > 0 else None,
        "next": (
            {"id": chapter + 1, "title": items[chapter + 1].chapter_title}
            if chapter + 1 < len(items)
            else None
        ),
        "direction": "rtl",
        "progress": progress["page"],
    }
