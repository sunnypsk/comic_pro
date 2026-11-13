from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from app.services import bangumi
from app.services.bangumi import BangumiTitles, source_queries
from app.services.http_client import SourceError, SourceHTTP
from app.sources.base import SearchPage, SearchResult, Source
from app.sources.registry import SourceRegistry

# Representative fields from the public manga-series response (not an app dictionary).
NARUTO = {
    "id": 34373, "type": 1, "platform": "漫画", "series": True,
    "name": "NARUTO -ナルト-", "name_cn": "火影忍者",
    "infobox": [
        {"key": "作者", "value": "岸本齐史"},
        {"key": "版本:正文版", "value": [{"k": "版本名", "v": "狐忍"}, {"k": "出版社", "v": "正文社"}]},
    ],
}


def _titles(client: httpx.AsyncClient, **kwargs) -> BangumiTitles:
    return BangumiTitles(client, timeout=kwargs.get("timeout", 1), ttl=86400, version="test")


def _handler(subject: dict, calls: list):
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["filter"] == {"type": [1]}
            assert body["sort"] == "heat"
            assert request.headers["User-Agent"].startswith("sunnypsk/ComicPro/")
            assert request.url.params["limit"] == "10"
            summary = {key: value for key, value in subject.items() if key != "infobox"}
            return httpx.Response(200, json={"data": [summary]})
        return httpx.Response(200, json=subject)
    return handle


@pytest.mark.parametrize("query,expected", [("火影忍者", "NARUTO"), ("naruto", "火影忍者")])
async def test_bangumi_resolves_both_directions_and_caches(query, expected) -> None:
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(NARUTO, calls))) as client:
        titles = _titles(client)
        aliases = await titles.resolve(query)
        assert expected in aliases
        assert "狐忍" in aliases
        assert "岸本齐史" not in aliases
        assert "正文社" not in aliases
        aliases.clear()  # Callers must not mutate the cache.
        assert expected in await titles.resolve(query.upper())
    assert len(calls) == 2


async def test_lookup_uses_infobox_aliases_and_preserves_subtitles() -> None:
    subject = deepcopy(NARUTO)
    subject.update(id=99, name="進撃の巨人", name_cn="进击的巨人")
    subject["infobox"] = [{"key": "别名", "value": [{"v": "Attack on Titan"}, {"v": "進擊的巨人"}]}]
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(subject, calls))) as client:
        titles = _titles(client)
        assert "进击的巨人" in await titles.resolve("Attack on Titan")
        assert "Attack on Titan" in await titles.resolve("進擊的巨人")
        assert await titles.resolve("Attack") == []  # No guesses for partial keywords.
    assert "NARUTO" not in bangumi._names({"name": "NARUTO -ナルト- (01)"})
    assert "NARUTO" not in bangumi._names({"name": "NARUTO -ナルト- 外伝"})


async def test_no_mapping_from_volume_novel_anime_or_ambiguous_title() -> None:
    candidates = [dict(NARUTO, series=False), dict(NARUTO, platform="小说"), dict(NARUTO, type=2)]
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "POST"
        return httpx.Response(200, json={"data": candidates})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await _titles(client).resolve("Naruto") == []
        candidates[:] = [NARUTO, dict(NARUTO, id=88)]
        assert await _titles(client).resolve("Naruto") == []
    assert len(calls) == 2


@pytest.mark.parametrize("body,status", [(None, 503), ([], 200), ({"data": None}, 200), ({}, 200)])
async def test_unavailable_or_malformed_bangumi_is_cached_as_fallback(body, status) -> None:
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        titles = _titles(client)
        assert await titles.resolve("Naruto") == []
        assert await titles.resolve("Naruto") == []
    assert len(calls) == 1


async def test_rate_limit_cooldown_and_cache_expiry(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(bangumi, "time", SimpleNamespace(monotonic=lambda: now[0]))
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "60"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        titles = _titles(client)
        assert await titles.resolve("Naruto") == []
        assert await titles.resolve("One Piece") == []
        assert len(calls) == 1
        now[0] += 61
        assert await titles.resolve("Naruto") == []
        assert len(calls) == 2


async def test_timeout_is_bounded_and_duplicate_lookups_share_cached_result() -> None:
    async def stalled(request):
        await asyncio.Event().wait()

    async with httpx.AsyncClient(transport=httpx.MockTransport(stalled)) as client:
        assert await asyncio.wait_for(_titles(client, timeout=0.01).resolve("Naruto"), timeout=0.5) == []

    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(NARUTO, calls))) as client:
        titles = _titles(client)
        left, right = await asyncio.gather(titles.resolve("Naruto"), titles.resolve("naruto"))
        assert left == right
        assert "火影忍者" in left
    assert len(calls) == 2


def test_queries_prefer_source_language_and_bound_fanout() -> None:
    aliases = ["火影忍者", "ナルト", "Naruto", "狐忍"]
    assert source_queries("original", aliases, "en") == ["original", "Naruto", "火影忍者"]
    assert source_queries("original", aliases, "zh-CN") == ["original", "火影忍者", "狐忍"]
    assert len(source_queries("original", aliases, "ja")) == 3


class RecordingSource(Source):
    name = "Test source"

    def __init__(self, client, source_id="english", lang="en", responses=None):
        super().__init__(SourceHTTP(client))
        self.id, self.lang = source_id, lang
        self.calls = []
        self.responses = responses or {}

    async def search(self, query, page=1):
        self.calls.append((query, page))
        result = self.responses.get(query, SearchPage(items=[], page=page))
        if isinstance(result, Exception):
            raise result
        return result

    async def get_manga(self, key):
        raise NotImplementedError

    async def get_pages(self, chapter_url):
        raise NotImplementedError


def _item(source_id, key, title):
    return SearchResult(source_id=source_id, key=key, title=title, url=f"https://example.org/{key}")


@pytest.mark.parametrize("query,target,lang", [("火影忍者", "NARUTO", "en"), ("Naruto", "火影忍者", "zh")])
async def test_search_api_expands_names_in_both_directions(app, client, settings, query, target, lang) -> None:
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(NARUTO, calls))) as metadata:
        registry = SourceRegistry(settings, metadata)
        registry.titles = _titles(metadata)
        source = RecordingSource(metadata, lang=lang, responses={
            target: SearchPage(items=[_item("english", "naruto", target)], page=2, has_next=True)
        })
        registry.sources = {source.id: source}
        registry.enabled = {source.id: True}
        app.state.registry = registry
        response = await client.get("/api/search", params={"q": query, "page": 2, "sources": source.id})
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == query
    assert target in payload["aliases"]
    assert payload["sources"][0]["items"][0]["title"] == target
    assert payload["sources"][0]["page"] == 2
    assert payload["sources"][0]["has_next"] is True
    assert source.calls[0] == (query, 2)
    assert 2 <= len(source.calls) <= 3


async def test_alias_failures_and_duplicates_preserve_original_results(settings) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(NARUTO, []))) as client:
        registry = SourceRegistry(settings, client)
        source = RecordingSource(client, responses={
            "Naruto": SearchPage(items=[_item("english", "one", "Original")]),
            "火影忍者": SearchPage(items=[_item("english", "one", "Duplicate"), _item("english", "two", "Extra")]),
            "NARUTO -ナルト-": SourceError("alias blocked"),
        })
        registry.sources, registry.enabled = {source.id: source}, {source.id: True}
        payload = await registry.search("Naruto")
    outcome = payload["sources"][0]
    assert outcome["status"] == "ok"
    assert [item["title"] for item in outcome["items"]] == ["Original", "Extra"]


@pytest.mark.parametrize("mode", ["disabled", "demo", "none", "operator"])
async def test_no_metadata_request_when_expansion_not_applicable(settings, mode) -> None:
    def no_network(request):
        pytest.fail("metadata API must not be called")

    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        settings.bangumi_enabled = mode != "disabled"
        registry = SourceRegistry(settings, client)
        source = RecordingSource(client, source_id="demo" if mode == "demo" else "english")
        registry.sources, registry.enabled = {source.id: source}, {source.id: mode != "none"}
        query = "language:chinese yuri" if mode == "operator" else "Naruto"
        payload = await registry.search(query)
        assert payload["aliases"] == []
        assert source.calls == ([] if mode == "none" else [(query, 1)])


async def test_bangumi_failure_still_returns_source_results(settings) -> None:
    async def handle(request):
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        registry = SourceRegistry(settings, client)
        source = RecordingSource(client, responses={"Naruto": SearchPage(items=[_item("english", "one", "Naruto")])})
        registry.sources, registry.enabled = {source.id: source}, {source.id: True}
        payload = await registry.search("Naruto")
    assert payload["aliases"] == []
    assert payload["sources"][0]["status"] == "ok"
    assert payload["sources"][0]["items"][0]["title"] == "Naruto"


async def test_metadata_lookup_and_original_source_search_run_concurrently(settings) -> None:
    original_started = asyncio.Event()

    async def handle(request):
        await asyncio.wait_for(original_started.wait(), timeout=0.5)
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        registry = SourceRegistry(settings, client)
        source = RecordingSource(client)
        original_search = source.search

        async def search(query, page=1):
            original_started.set()
            return await original_search(query, page)

        source.search = search
        registry.sources, registry.enabled = {source.id: source}, {source.id: True}
        payload = await registry.search("Naruto")
    assert original_started.is_set()
    assert payload["sources"][0]["status"] == "ok"
