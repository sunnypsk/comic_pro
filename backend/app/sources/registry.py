from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from ..config import Settings
from ..services.bangumi import BangumiTitles, source_queries
from ..services.http_client import SourceError, SourceHTTP
from .base import SearchPage, Source
from .demo import DemoSource
from .dongman import DongmanSource
from .mangapill import MangapillSource
from .nhentai import NhEntaiSource
from .weebcentral import WeebCentralSource
from .yaml_source import YamlSource

BUILTIN_DIR = Path(__file__).parent / "builtin"


class SourceRegistry:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client
        self.sources: dict[str, Source] = {}
        self.raw: dict[str, dict[str, Any]] = {}
        self.enabled: dict[str, bool] = {}
        self.errors: dict[str, str] = {}
        self.last_error: dict[str, str] = {}
        self.last_ok: dict[str, float] = {}
        self.titles = BangumiTitles(
            client, timeout=min(settings.bangumi_timeout, settings.search_timeout),
            ttl=settings.bangumi_cache_ttl, version=settings.version,
        )

    # --------------------------------------------------------------- lifecycle
    def load(self, state: dict[str, bool] | None = None) -> dict[str, str]:
        self.sources.clear()
        self.raw.clear()
        self.errors.clear()
        state = state or {}
        files = sorted(BUILTIN_DIR.glob("*.yaml")) + sorted(self.settings.sources_dir.glob("*.y*ml"))
        for path in files:
            try:
                config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not isinstance(config, dict):
                    raise ValueError("top level must be a mapping")
                source = YamlSource(self._http_for(config), config)
                self.sources[source.id] = source
                self.raw[source.id] = config
                self.enabled[source.id] = bool(state.get(source.id, source.enabled_by_default))
            except Exception as exc:  # noqa: BLE001 - a broken file must not kill startup
                self.errors[path.name] = f"{type(exc).__name__}: {exc}"

        if self.settings.demo_source:
            demo = DemoSource(self._http_for({"id": "demo"}))
            self.sources.setdefault("demo", demo)
            self.enabled.setdefault("demo", bool(state.get("demo", True)))

        builtin_classes = []
        if self.settings.mangapill:
            builtin_classes.append(MangapillSource)
        if self.settings.weebcentral:
            builtin_classes.append(WeebCentralSource)
        if self.settings.dongman:
            builtin_classes.append(DongmanSource)
        if self.settings.nhentai:
            builtin_classes.append(NhEntaiSource)
        for source_class in builtin_classes:
            source = source_class(self._http_for({"id": source_class.id}))
            self.sources.setdefault(source.id, source)
            self.enabled.setdefault(source.id, bool(state.get(source.id, source.enabled_by_default)))

        for source_id in list(self.enabled):
            if source_id not in self.sources:
                self.enabled.pop(source_id, None)
        return dict(self.errors)

    def _http_for(self, config: dict[str, Any]) -> SourceHTTP:
        headers = dict(config.get("headers") or {})
        headers.setdefault("User-Agent", self.settings.user_agent)
        return SourceHTTP(
            self.client,
            timeout=self.settings.source_timeout,
            concurrency=2,
            min_interval=self.settings.source_min_interval,
            default_headers=headers,
        )

    # ------------------------------------------------------------------ access
    def get(self, source_id: str) -> Source:
        source = self.sources.get(source_id)
        if source is None:
            raise SourceError(f"unknown source: {source_id}", "UNKNOWN_SOURCE")
        return source

    def describe(self) -> list[dict[str, Any]]:
        items = []
        for source_id, source in self.sources.items():
            info = source.describe()
            info.update(
                {
                    "enabled": bool(self.enabled.get(source_id)),
                    "last_error": self.last_error.get(source_id, ""),
                    "last_ok": self.last_ok.get(source_id),
                    "has_config": source_id in self.raw,
                }
            )
            items.append(info)
        items.sort(key=lambda item: (item["id"] != "demo", item["name"].lower()))
        return items

    def set_enabled(self, source_id: str, enabled: bool) -> None:
        self.get(source_id)
        self.enabled[source_id] = enabled

    # ------------------------------------------------------------------ search
    async def search(self, query: str, page: int = 1, ids: list[str] | None = None) -> dict[str, Any]:
        selected = [
            source
            for source_id, source in self.sources.items()
            if self.enabled.get(source_id) and (not ids or source_id in ids)
        ]
        lookup = None
        if self.settings.bangumi_enabled and any(source.id != "demo" for source in selected):
            lookup = asyncio.create_task(self.titles.resolve(query))

        async def run(source: Source) -> dict[str, Any]:
            started = time.monotonic()
            timeout = min(self.settings.source_timeout + 2, self.settings.search_timeout)
            deadline = started + timeout

            async def fetch(term: str) -> SearchPage:
                return await asyncio.wait_for(source.search(term, page), timeout=max(0, deadline - time.monotonic()))

            # Original searches start immediately, alongside optional title lookup.
            primary = asyncio.create_task(fetch(query))
            try:
                aliases = await lookup if lookup is not None and source.id != "demo" else []
                queries = source_queries(query, aliases, source.lang) if source.id != "demo" else [query]
                results = await asyncio.gather(
                    primary, *(fetch(term) for term in queries[1:]),
                    return_exceptions=True,
                )
                pages = [result for result in results if isinstance(result, SearchPage)]
                if not pages:
                    raise results[0]
                # Original-query results come first and win duplicate keys.
                items = {}
                for result in pages:
                    for item in result.items:
                        items.setdefault(item.key, item)
                result = SearchPage(
                    items=list(items.values()), page=page, has_next=any(result.has_next for result in pages)
                )
                self.last_ok[source.id] = time.time()
                self.last_error.pop(source.id, None)
                return self._outcome(source, result, started, "ok")
            except TimeoutError:
                self.last_error[source.id] = "timeout"
                return self._outcome(source, SearchPage(items=[]), started, "timeout", "source timed out")
            except SourceError as exc:
                self.last_error[source.id] = exc.message
                return self._outcome(source, SearchPage(items=[]), started, "error", exc.message)
            except Exception as exc:  # noqa: BLE001
                self.last_error[source.id] = f"{type(exc).__name__}: {exc}"
                return self._outcome(source, SearchPage(items=[]), started, "error", str(exc))
            finally:
                if not primary.done():
                    primary.cancel()
                await asyncio.gather(primary, return_exceptions=True)

        try:
            outcomes = await asyncio.gather(*(run(source) for source in selected))
            aliases = lookup.result() if lookup is not None else []
        finally:
            if lookup is not None:
                if not lookup.done():
                    lookup.cancel()
                await asyncio.gather(lookup, return_exceptions=True)
        outcomes.sort(key=lambda item: (item["id"] != "demo", item["source_name"].lower()))
        return {"query": query, "page": page, "sources": outcomes, "aliases": aliases}

    @staticmethod
    def _outcome(
        source: Source, result: SearchPage, started: float, status: str, error: str = ""
    ) -> dict[str, Any]:
        elapsed = int((time.monotonic() - started) * 1000)
        return {
            "id": source.id,
            "source_name": source.name,
            "nsfw": source.nsfw,
            "status": status,
            "error": error,
            "elapsed_ms": elapsed,
            "page": result.page,
            "has_next": result.has_next,
            "items": [
                {
                    "source_id": item.source_id,
                    "key": item.key,
                    "title": item.title,
                    "cover": item.cover,
                    "description": item.description,
                    "tags": item.tags,
                }
                for item in result.items
            ],
        }
