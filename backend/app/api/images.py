from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from ..services.fetcher import FetchError

router = APIRouter(tags=["images"])


@router.get("/img")
async def proxy_image(
    request: Request,
    u: str = Query(..., description="absolute image URL"),
    s: str = Query(..., description="source id"),
    e: int = Query(..., description="expiry timestamp"),
    sig: str = Query(..., description="HMAC signature"),
) -> Response:
    proxy = request.app.state.image_proxy
    if not proxy.verify(s, u, e, sig):
        raise HTTPException(status_code=403, detail={"code": "BAD_SIGNATURE", "message": "invalid image link"})
    registry = request.app.state.registry
    source = registry.sources.get(s)
    referer = source.base_url if source is not None else ""
    try:
        data, ext, media = await proxy.fetch(s, u, referer)
    except FetchError as exc:
        status = 502 if exc.code not in ("BLOCKED_HOST", "BAD_URL") else 400
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc
    return Response(
        content=data,
        media_type=media,
        headers={
            "Cache-Control": "private, max-age=86400",
            "Content-Length": str(len(data)),
            "X-Image-Ext": ext,
        },
    )
