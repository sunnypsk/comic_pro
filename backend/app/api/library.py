from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select

from ..deps import SessionDep
from ..models import LibraryItem
from ..services import cbz as cbz_service
from ..services import library_scan
from ..services.slugs import b64d, b64e, ensure_within

router = APIRouter(prefix="/library", tags=["library"])

RANGE_HEADERS = {"Cache-Control": "private, max-age=3600"}


def _decode_series(value: str) -> str:
    try:
        series = b64d(value)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"code": "BAD_ID", "message": "invalid series id"}) from exc
    if not series or series.startswith("/") or ".." in Path(series).parts:
        raise HTTPException(status_code=400, detail={"code": "BAD_ID", "message": "invalid series id"})
    return series


async def _series_items(session, series_dir: str) -> list[LibraryItem]:
    return list(
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


@router.get("")
async def list_library(
    request: Request,
    session: SessionDep,
    q: str = Query("", max_length=200),
    scan: bool = False,
) -> dict:
    settings = request.app.state.settings
    if scan:
        await library_scan.sync_library(request.app.state.db, settings.library_dir)
    rows = (await session.execute(select(LibraryItem))).scalars().all()
    groups: dict[str, list[LibraryItem]] = {}
    for row in rows:
        groups.setdefault(row.series_dir, []).append(row)

    needle = q.lower().strip()
    series = []
    for series_dir, items in groups.items():
        items.sort(key=lambda item: (item.chapter_index, item.rel_path))
        latest = items[-1]
        title = latest.series_title
        if needle and needle not in title.lower():
            continue
        series_id = b64e(series_dir)
        series.append(
            {
                "id": series_id,
                "title": title,
                "source_dir": series_dir.split("/")[0] if "/" in series_dir else "",
                "chapter_count": len(items),
                "page_count": sum(item.page_count for item in items),
                "size_bytes": sum(item.size_bytes for item in items),
                "updated_at": latest.mtime,
                "cover": f"/api/library/{series_id}/cover?v={int(latest.mtime)}",
            }
        )
    series.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"series": series, "total": len(series)}


@router.post("/scan")
async def scan_library(request: Request) -> dict:
    return await library_scan.sync_library(request.app.state.db, request.app.state.settings.library_dir)


@router.get("/{series_id}")
async def library_detail(series_id: str, request: Request, session: SessionDep) -> dict:
    series_dir = _decode_series(series_id)
    items = await _series_items(session, series_dir)
    if not items:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "series not found"})
    return {
        "id": series_id,
        "title": items[0].series_title,
        "cover": f"/api/library/{series_id}/cover?v={int(items[-1].mtime)}",
        "chapters": [
            {
                "index": index,
                "title": item.chapter_title,
                "page_count": item.page_count,
                "size_bytes": item.size_bytes,
                "updated_at": item.mtime,
            }
            for index, item in enumerate(items)
        ],
    }


@router.get("/{series_id}/cover")
async def library_cover(series_id: str, request: Request, session: SessionDep):
    settings = request.app.state.settings
    series_dir = _decode_series(series_id)
    items = await _series_items(session, series_dir)
    if not items:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "series not found"})
    latest = items[-1]
    path = library_scan.ensure_series_cover(
        settings.library_dir, settings.covers_dir, series_dir, latest.rel_path
    )
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail={"code": "NO_COVER", "message": "cover unavailable"})
    return FileResponse(path, media_type="image/jpeg", headers=RANGE_HEADERS)


@router.get("/{series_id}/chapters/{index}/pages/{number}")
async def library_page(
    series_id: str,
    index: int,
    number: int,
    request: Request,
    session: SessionDep,
) -> Response:
    settings = request.app.state.settings
    series_dir = _decode_series(series_id)
    items = await _series_items(session, series_dir)
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail={"code": "NO_CHAPTER", "message": "chapter not found"})
    item = items[index]
    path = ensure_within(settings.library_dir, settings.library_dir / item.rel_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail={"code": "NO_FILE", "message": "file missing on disk"})
    page = cbz_service.extract_page(path, number)
    if page is None:
        raise HTTPException(status_code=404, detail={"code": "NO_PAGE", "message": "page not found"})
    data, media = page
    etag = f'"{item.rel_path}:{number}:{item.size_bytes}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, **RANGE_HEADERS})
    return Response(content=data, media_type=media, headers={"ETag": etag, **RANGE_HEADERS})


@router.delete("/{series_id}")
async def delete_series(
    series_id: str,
    request: Request,
    session: SessionDep,
    confirm: bool = Query(False),
) -> dict:
    if not confirm:
        raise HTTPException(status_code=400, detail={"code": "CONFIRM_REQUIRED", "message": "pass confirm=1"})
    settings = request.app.state.settings
    series_dir = _decode_series(series_id)
    target = ensure_within(settings.library_dir, settings.library_dir / series_dir)
    items = await _series_items(session, series_dir)
    if target.exists() and target.is_dir():
        shutil.rmtree(target)
    else:
        for item in items:
            path = settings.library_dir / item.rel_path
            if path.exists():
                path.unlink()
    for item in items:
        await session.delete(item)
    await session.commit()
    await library_scan.sync_library(request.app.state.db, settings.library_dir)
    return {"ok": True, "deleted_chapters": len(items)}
