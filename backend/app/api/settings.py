from __future__ import annotations

from fastapi import APIRouter, Request

from ..deps import SessionDep
from ..schemas import SettingsIn
from ..services.store import set_json

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def read_settings(request: Request) -> dict:
    app = request.app
    settings = app.state.settings
    return {
        "cache_max_gb": app.state.runtime["cache_max_gb"],
        "check_interval_min": app.state.runtime["check_interval_min"],
        "env": {
            "download_concurrency": settings.download_concurrency,
            "page_concurrency": settings.page_concurrency,
            "source_timeout": settings.source_timeout,
            "search_timeout": settings.search_timeout,
            "data_dir": str(settings.data_dir),
            "base_path": settings.root_path(),
            "auth_password_set": bool(settings.auth_password),
        },
        "auth_required": await app.state.auth.enabled(),
        "version": settings.version,
        "source_count": len(app.state.registry.sources),
    }


@router.patch("")
async def update_settings(payload: SettingsIn, request: Request, session: SessionDep) -> dict:
    app = request.app
    runtime = dict(app.state.runtime)
    if payload.cache_max_gb is not None:
        runtime["cache_max_gb"] = float(payload.cache_max_gb)
        app.state.page_cache.max_bytes = int(payload.cache_max_gb * 1024**3)
    if payload.check_interval_min is not None:
        runtime["check_interval_min"] = int(payload.check_interval_min)
    if app.state.subscriptions is not None:
        app.state.subscriptions.interval_min = runtime["check_interval_min"]
    app.state.runtime = runtime
    await set_json(session, "runtime", runtime)
    await session.commit()
    return {"ok": True, **runtime}
