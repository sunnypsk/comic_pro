from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .api import auth as auth_api
from .api import demo as demo_api
from .api import downloads as downloads_api
from .api import health as health_api
from .api import images as images_api
from .api import library as library_api
from .api import progress as progress_api
from .api import reader as reader_api
from .api import search as search_api
from .api import settings as settings_api
from .api import sources as sources_api
from .config import Settings, get_settings
from .db import Database
from .deps import require_auth
from .services import library_scan
from .services.auth import AuthService
from .services.downloader import DownloadManager
from .services.events import Broadcaster
from .services.image_proxy import ImageProxy
from .services.page_cache import PageCache
from .services.store import get_json
from .services.subscriptions import Subscriptions
from .sources.registry import SourceRegistry

log = logging.getLogger("comicpro")


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def frontend_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    _configure_logging(settings.log_level)
    secret = settings.load_secret()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await _startup(app, settings, secret)
        try:
            yield
        finally:
            await _shutdown(app)

    app = FastAPI(
        title="ComicPro",
        version=settings.version,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.secret = secret
    app.state.started_at = time.time()

    protected = [Depends(require_auth)]
    app.include_router(health_api.router, prefix="/api")
    app.include_router(auth_api.router, prefix="/api")
    for module in (
        search_api,
        sources_api,
        images_api,
        demo_api,
        library_api,
        reader_api,
        progress_api,
        downloads_api,
        settings_api,
    ):
        app.include_router(module.router, prefix="/api", dependencies=protected)

    dist = frontend_dist()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str, request: Request):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "no such endpoint"})
        index = dist / "index.html"
        if index.exists():
            html = index.read_text(encoding="utf-8")
            base_href = (settings.root_path() or "") + "/"
            html = html.replace("<head>", f'<head>\n    <base href="{base_href}" />', 1)
            config = {
                "basePath": settings.root_path(),
                "authRequired": await app.state.auth.enabled(),
                "version": settings.version,
            }
            script = f"<script>window.__COMICPRO__ = {json.dumps(config)};</script>"
            html = html.replace("<!--COMICPRO_CONFIG-->", script, 1)
            return Response(content=html, media_type="text/html", headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            {"detail": {"code": "NO_FRONTEND", "message": "frontend is not built"}}, status_code=404
        )

    return app


async def _startup(app: FastAPI, settings: Settings, secret: str) -> None:
    logging.getLogger().setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    log.info("starting ComicPro %s with data dir %s", settings.version, settings.data_dir)

    database = Database(settings.db_path)
    await database.init()
    app.state.db = database

    async with database.session() as session:
        source_state = await get_json(session, "source_state", {})
        runtime = await get_json(session, "runtime", {})
        stored = await get_json(session, "auth_password_hash", "")
    app.state.auth_required = bool(settings.auth_password) or bool(stored)

    client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": settings.user_agent},
        proxy=settings.http_proxy or None,
    )
    app.state.http = client

    cache_max_gb = float(runtime.get("cache_max_gb", settings.cache_max_gb))
    interval = int(runtime.get("check_interval_min", settings.check_interval_min))
    app.state.runtime = {"cache_max_gb": cache_max_gb, "check_interval_min": interval}

    registry = SourceRegistry(settings, client)
    registry.load(state=source_state if isinstance(source_state, dict) else {})
    app.state.registry = registry

    page_cache = PageCache(settings.page_cache_dir, int(cache_max_gb * 1024**3))
    app.state.page_cache = page_cache
    app.state.image_proxy = ImageProxy(
        settings, client, page_cache, secret, base_path=settings.root_path()
    )

    events = Broadcaster()
    app.state.events = events
    downloader = DownloadManager(
        db=database, settings=settings, registry=registry, client=client, events=events
    )
    await downloader.start()
    app.state.downloader = downloader

    app.state.auth = AuthService(settings, database, secret)
    app.state.subscriptions = Subscriptions(
        db=database,
        settings=settings,
        registry=registry,
        downloader=downloader,
        interval_min=interval,
    )
    await app.state.subscriptions.start()

    await library_scan.sync_library(database, settings.library_dir)

    cleanup = asyncio.create_task(page_cache.cleanup_loop(), name="page-cache-cleanup")
    app.state.tasks = [cleanup]

    try:
        await page_cache.prune_async()
    except Exception:  # noqa: BLE001
        pass


async def _shutdown(app: FastAPI) -> None:
    for task in getattr(app.state, "tasks", []):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    if hasattr(app.state, "subscriptions"):
        await app.state.subscriptions.stop()
    if hasattr(app.state, "downloader"):
        await app.state.downloader.stop()
    if hasattr(app.state, "http"):
        await app.state.http.aclose()
    if hasattr(app.state, "db"):
        await app.state.db.close()
    log.info("stopped ComicPro")
