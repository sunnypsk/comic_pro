from __future__ import annotations

import shutil
import time

from fastapi import APIRouter, Request
from sqlalchemy import func, select, text

from ..models import LibraryItem, Manga

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    app = request.app
    settings = app.state.settings
    database = app.state.db
    db_ok = True
    try:
        async with database.session() as session:
            await session.execute(text("SELECT 1"))
            manga_count = (await session.execute(select(func.count()).select_from(Manga))).scalar() or 0
            library_count = (
                await session.execute(select(func.count()).select_from(LibraryItem))
            ).scalar() or 0
    except Exception:  # noqa: BLE001
        db_ok = False
        manga_count = library_count = 0

    try:
        usage = shutil.disk_usage(settings.data_dir)
        disk = {
            "free_gb": round(usage.free / 1024**3, 2),
            "total_gb": round(usage.total / 1024**3, 2),
        }
    except OSError:
        disk = {"free_gb": 0, "total_gb": 0}

    downloader = getattr(app.state, "downloader", None)
    queue = await downloader.stats() if downloader else {}
    registry = app.state.registry
    return {
        "status": "ok" if db_ok else "degraded",
        "version": settings.version,
        "db": "ok" if db_ok else "error",
        "uptime_s": int(time.time() - app.state.started_at),
        "disk": disk,
        "queue": queue,
        "counts": {"manga": manga_count, "library_chapters": library_count},
        "sources": {
            "total": len(registry.sources),
            "enabled": sum(1 for value in registry.enabled.values() if value),
            "errors": registry.errors,
        },
        "auth_required": bool(getattr(app.state, "auth_required", False)),
    }
