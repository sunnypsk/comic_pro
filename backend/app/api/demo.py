from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ..sources import demo

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/page")
async def page(key: str, n: int = Query(1, ge=1, le=200)) -> Response:
    try:
        data = demo.demo_page_bytes(key, n)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/cover")
async def cover(key: str) -> Response:
    try:
        data = demo.demo_cover_bytes(key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
