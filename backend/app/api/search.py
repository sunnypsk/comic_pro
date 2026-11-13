from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..deps import RegistryDep

router = APIRouter(tags=["search"])


@router.get("/search")
async def search(
    request: Request,
    registry: RegistryDep,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1, le=50),
    sources: str = Query("", description="comma separated source ids"),
) -> dict:
    ids = [item.strip() for item in sources.split(",") if item.strip()]
    query = q.strip()
    if not query:
        return {"query": "", "page": page, "sources": []}

    payload = await registry.search(query, page=page, ids=ids or None)
    proxy = request.app.state.image_proxy
    for outcome in payload["sources"]:
        for item in outcome["items"]:
            cover = item.get("cover") or ""
            if cover.startswith("http"):
                item["cover"] = proxy.signed_url(item["source_id"], cover)
    return payload
