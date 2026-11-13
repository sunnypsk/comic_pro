from __future__ import annotations

import re
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from ..deps import RegistryDep, SessionDep
from ..models import Chapter, Manga, dumps, loads, utcnow
from ..schemas import FollowIn, ProbeIn, SourceConfigIn, SourcePatch
from ..services.http_client import SourceError
from ..services.store import set_json
from ..sources.base import MangaDetail
from ..sources.probe import probe_site
from ..sources.registry import SourceRegistry
from ..sources.yaml_source import YamlSource

router = APIRouter(prefix="/sources", tags=["sources"])

STATE_KEY = "source_state"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", value)[:64]


async def _persist_state(session, registry: SourceRegistry) -> None:
    await set_json(session, STATE_KEY, dict(registry.enabled))
    await session.commit()


def _cover(request: Request, source_id: str, cover: str) -> str:
    if not cover:
        return ""
    if cover.startswith("http"):
        return request.app.state.image_proxy.signed_url(source_id, cover)
    return cover


async def _upsert_detail(session, source_id: str, detail: MangaDetail) -> Manga:
    manga = (
        await session.execute(
            select(Manga).where(Manga.source_id == source_id, Manga.source_key == detail.key)
        )
    ).scalar_one_or_none()
    if manga is None:
        manga = Manga(source_id=source_id, source_key=detail.key, title=detail.title or detail.key)
        session.add(manga)
        await session.flush()
    manga.title = detail.title or manga.title
    manga.cover_url = detail.cover
    manga.description = detail.description
    manga.author = detail.author
    manga.status = detail.status
    manga.tags = dumps(detail.tags)
    manga.last_synced_at = utcnow()

    existing = {
        chapter.source_key: chapter
        for chapter in (
            (await session.execute(select(Chapter).where(Chapter.manga_id == manga.id))).scalars().all()
        )
    }
    for ref in detail.chapters:
        chapter = existing.get(ref.key)
        if chapter is None:
            chapter = Chapter(manga_id=manga.id, source_key=ref.key, title=ref.title, url=ref.url)
            session.add(chapter)
        chapter.title = ref.title
        chapter.url = ref.url
        chapter.number = ref.number
        chapter.published_at = ref.published_at
    await session.commit()
    return manga


async def _detail_payload(request: Request, session, source_id: str, manga: Manga) -> dict[str, Any]:
    chapters = (
        (await session.execute(select(Chapter).where(Chapter.manga_id == manga.id).order_by(Chapter.id)))
        .scalars()
        .all()
    )
    source = request.app.state.registry.sources.get(source_id)
    return {
        "id": manga.id,
        "source_id": source_id,
        "source_name": source.name if source else source_id,
        "key": manga.source_key,
        "title": manga.title,
        "cover": _cover(request, source_id, manga.cover_url),
        "description": manga.description,
        "author": manga.author,
        "status": manga.status,
        "tags": loads(manga.tags, []),
        "follow": bool(manga.follow),
        "auto_download": bool(manga.auto_download),
        "direction": source.direction if source else "rtl",
        "chapters": [
            {
                "id": chapter.id,
                "key": chapter.source_key,
                "title": chapter.title,
                "number": chapter.number,
                "downloaded": bool(chapter.downloaded),
                "page_count": chapter.page_count,
            }
            for chapter in chapters
        ],
    }


@router.get("")
async def list_sources(registry: RegistryDep) -> dict:
    return {"sources": registry.describe(), "errors": registry.errors}


@router.post("/reload")
async def reload_sources(registry: RegistryDep, session: SessionDep) -> dict:
    errors = registry.load(state=dict(registry.enabled))
    await _persist_state(session, registry)
    return {"sources": len(registry.sources), "errors": errors}


@router.post("/probe")
async def probe(request: Request, payload: ProbeIn, registry: RegistryDep) -> dict:
    try:
        result = await probe_site(registry.client, payload.url, request.app.state.settings.user_agent)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "PROBE_FAILED", "message": str(exc)}) from exc
    return result


@router.patch("/{source_id}")
async def patch_source(source_id: str, payload: SourcePatch, registry: RegistryDep, session: SessionDep) -> dict:
    try:
        registry.set_enabled(source_id, payload.enabled)
    except SourceError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": exc.message}) from exc
    await _persist_state(session, registry)
    return {"id": source_id, "enabled": payload.enabled}


@router.get("/{source_id}/popular")
async def popular(source_id: str, request: Request, registry: RegistryDep) -> dict:
    try:
        source = registry.get(source_id)
        page = await source.popular(1)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail={"code": exc.code, "message": exc.message}) from exc
    return {
        "source_id": source_id,
        "items": [
            {
                "source_id": item.source_id,
                "key": item.key,
                "title": item.title,
                "cover": _cover(request, source_id, item.cover),
                "description": item.description,
                "tags": item.tags,
            }
            for item in page.items
        ],
    }


@router.get("/{source_id}/manga/{key:path}")
async def manga_detail(
    source_id: str, key: str, request: Request, registry: RegistryDep, session: SessionDep
) -> dict:
    try:
        source = registry.get(source_id)
        detail = await source.get_manga(key)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail={"code": exc.code, "message": exc.message}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_KEY", "message": str(exc)}) from exc
    manga = await _upsert_detail(session, source_id, detail)
    return await _detail_payload(request, session, source_id, manga)


@router.post("/{source_id}/manga/{key:path}/follow")
async def follow_manga(source_id: str, key: str, payload: FollowIn, session: SessionDep) -> dict:
    manga = (
        await session.execute(
            select(Manga).where(Manga.source_id == source_id, Manga.source_key == key)
        )
    ).scalar_one_or_none()
    if manga is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "open the manga first"})
    if payload.follow is not None:
        manga.follow = payload.follow
    if payload.auto_download is not None:
        manga.auto_download = payload.auto_download
    await session.commit()
    return {"follow": bool(manga.follow), "auto_download": bool(manga.auto_download)}


@router.get("/{source_id}/config")
async def get_source_config(source_id: str, registry: RegistryDep) -> dict:
    raw = registry.raw.get(source_id)
    if raw is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "no config for this source"})
    return {"id": source_id, "yaml": yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)}


@router.put("/{source_id}/config")
async def save_source_config(
    source_id: str, payload: SourceConfigIn, registry: RegistryDep, session: SessionDep
) -> dict:
    try:
        config = yaml.safe_load(payload.yaml) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_YAML", "message": str(exc)}) from exc
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail={"code": "BAD_YAML", "message": "top level must be a mapping"})
    config["id"] = source_id
    if not config.get("base_url"):
        raise HTTPException(status_code=400, detail={"code": "BAD_CONFIG", "message": "base_url is required"})
    try:
        YamlSource(registry._http_for(config), config)  # noqa: SLF001 - validation only
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"code": "BAD_CONFIG", "message": str(exc)}) from exc

    path = registry.settings.sources_dir / f"{_safe_id(source_id)}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = source_id in registry.enabled
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    state = dict(registry.enabled)
    if not existed:
        state[source_id] = bool(config.get("enabled", True))
    errors = registry.load(state=state)
    await _persist_state(session, registry)
    return {"ok": True, "id": source_id, "errors": errors, "path": path.name}


@router.delete("/{source_id}/config")
async def delete_source_config(source_id: str, registry: RegistryDep, session: SessionDep) -> dict:
    path = registry.settings.sources_dir / f"{_safe_id(source_id)}.yaml"
    if path.exists():
        path.unlink()
    errors = registry.load(state=dict(registry.enabled))
    await _persist_state(session, registry)
    return {"ok": True, "errors": errors}
