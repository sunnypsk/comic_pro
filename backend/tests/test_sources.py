from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from app.services.http_client import SourceHTTP
from app.sources.base import encode_key
from app.sources.probe import probe_site
from app.sources.yaml_source import YamlSource

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def _madara_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/manga/blue-sky/":
        return httpx.Response(200, text=_read("madara_manga.html"), headers={"content-type": "text/html"})
    if path == "/blue-sky/chapter-1/":
        return httpx.Response(200, text=_read("madara_chapter.html"), headers={"content-type": "text/html"})
    if path == "/":
        return httpx.Response(200, text=_read("madara_search.html"), headers={"content-type": "text/html"})
    return httpx.Response(404)


def _mangastream_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/manga/iron-garden/":
        return httpx.Response(200, text=_read("mangastream_manga.html"), headers={"content-type": "text/html"})
    if path == "/iron-garden/chapter-1/":
        return httpx.Response(200, text=_read("mangastream_chapter.html"), headers={"content-type": "text/html"})
    if path == "/":
        return httpx.Response(200, text=_read("mangastream_search.html"), headers={"content-type": "text/html"})
    return httpx.Response(404)


def _source(config: dict, handler) -> tuple[YamlSource, httpx.AsyncClient]:
    client = _client(handler)
    http = SourceHTTP(client, timeout=3.0, concurrency=2, min_interval=0.0)
    return YamlSource(http, config), client


@pytest.mark.parametrize(
    "config,handler",
    [
        (
            {"id": "madara", "name": "M", "base_url": "https://example.org", "engine": "madara"},
            _madara_handler,
        ),
        (
            {"id": "stream", "name": "S", "base_url": "https://stream.example.org", "engine": "mangastream"},
            _mangastream_handler,
        ),
    ],
)
async def test_search_parsing(config, handler) -> None:
    source, client = _source(config, handler)
    async with client:
        page = await source.search("sky" if config["engine"] == "madara" else "iron")
    assert page.items, "search should return at least one item"
    first = page.items[0]
    assert first.title
    assert first.url.startswith("https://")
    assert first.cover


async def test_madara_detail_and_pages() -> None:
    source, client = _source(
        {"id": "madara", "name": "M", "base_url": "https://example.org", "engine": "madara"},
        _madara_handler,
    )
    async with client:
        detail = await source.get_manga(encode_key("https://example.org/manga/blue-sky/"))
        assert detail.title == "Blue Sky"
        assert detail.author == "Jane Doe"
        assert detail.tags == ["Drama", "Fantasy"]
        assert [chapter.title for chapter in detail.chapters] == [
            "Chapter 1: Beginnings",
            "Chapter 2: Upward",
        ]
        assert detail.chapters[0].number == 1.0

        pages = await source.get_pages("/blue-sky/chapter-1/")
    assert [page.url for page in pages] == [
        "https://example.org/pages/001.jpg",
        "https://example.org/pages/002.jpg",
        "https://example.org/pages/003.jpg",
    ]
    assert pages[0].headers["Referer"].startswith("https://example.org")


async def test_mangastream_detail_and_pages() -> None:
    source, client = _source(
        {"id": "stream", "name": "S", "base_url": "https://stream.example.org", "engine": "mangastream"},
        _mangastream_handler,
    )
    async with client:
        detail = await source.get_manga(encode_key("https://stream.example.org/manga/iron-garden/"))
        assert detail.title == "Iron Garden"
        assert [chapter.number for chapter in detail.chapters] == [1.0, 2.0]
        pages = await source.get_pages("https://stream.example.org/iron-garden/chapter-1/")
    assert len(pages) == 2


async def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError):
        YamlSource(SourceHTTP(_client(_madara_handler)), {"id": "x"})


async def test_probe_detects_engine() -> None:
    html = _read("madara_chapter.html")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    client = _client(handler)
    async with client:
        result = await probe_site(client, "https://manga.example.org", "ComicProTest/1.0")
    assert result["engine"] == "madara"
    assert "id: manga-example-org" in result["yaml"]
    assert result["base_url"] == "https://manga.example.org"
