from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from app.services.http_client import SourceHTTP
from app.sources.base import encode_key
from app.sources.dongman import DongmanSource
from app.sources.mangapill import MangapillSource
from app.sources.nhentai import NhEntaiSource
from app.sources.weebcentral import WeebCentralSource

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _json(name: str) -> dict:
    import json

    return json.loads(_read(name))


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def _source(cls, handler):
    client = _client(handler)
    return cls(SourceHTTP(client, timeout=5.0, min_interval=0.0)), client


PILL_MANGA_URL = "https://mangapill.com/manga/2/one-piece"
PILL_CHAPTER_URL = "https://mangapill.com/chapters/2-1/one-piece-chapter-1"


def pill_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/search":
        return httpx.Response(200, text=_read("mangapill_search.html"), headers={"content-type": "text/html"})
    if path == "/manga/2/one-piece":
        return httpx.Response(200, text=_read("mangapill_manga.html"), headers={"content-type": "text/html"})
    if path == "/chapters/2-1/one-piece-chapter-1":
        return httpx.Response(200, text=_read("mangapill_chapter.html"), headers={"content-type": "text/html"})
    return httpx.Response(404)


WC_SERIES_URL = "https://weebcentral.com/series/UID/One-Piece"
WC_CHAPTER_URL = "https://weebcentral.com/chapters/CH1"


def wc_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/search/data":
        return httpx.Response(200, text=_read("weebcentral_search.html"), headers={"content-type": "text/html"})
    if path == "/series/UID/One-Piece":
        return httpx.Response(200, text=_read("weebcentral_series.html"), headers={"content-type": "text/html"})
    if path == "/series/UID/full-chapter-list":
        return httpx.Response(200, text=_read("weebcentral_chapters.html"), headers={"content-type": "text/html"})
    if path == "/chapters/CH1/images":
        return httpx.Response(200, text=_read("weebcentral_images.html"), headers={"content-type": "text/html"})
    return httpx.Response(404)


DONGMAN_DETAIL_URL = "https://www.dongmanmanhua.cn/episodeList?titleNo=1403"
DONGMAN_CHAPTER_URL = (
    "https://www.dongmanmanhua.cn/LOVE/lianaixingqun/%E7%AC%AC1%E8%AF%9D/viewer"
    "?title_no=1403&episode_no=1"
)


def dongman_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/search":
        return httpx.Response(200, text=_read("dongman_search.html"), headers={"content-type": "text/html"})
    if path == "/episodeList":
        return httpx.Response(200, text=_read("dongman_detail.html"), headers={"content-type": "text/html"})
    if path.endswith("/viewer"):
        return httpx.Response(200, text=_read("dongman_viewer.html"), headers={"content-type": "text/html"})
    return httpx.Response(404)


NHENTAI_URL = "https://nhentai.net/g/1/"
NHENTAI_CHAPTER_URL = "https://nhentai.net/g/1/"


def nhentai_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/v2/cdn":
        return httpx.Response(200, json=_json("nhentai_cdn.json"))
    if path == "/api/v2/search":
        return httpx.Response(200, json=_json("nhentai_search.json"))
    if path == "/api/v2/galleries/1":
        return httpx.Response(200, json=_json("nhentai_gallery.json"))
    return httpx.Response(404)


async def test_mangapill_search() -> None:
    source, client = _source(MangapillSource, pill_handler)
    async with client:
        page = await source.search("one piece", 1)
    assert [item.title for item in page.items] == ["One Piece", "Naruto"]
    assert page.items[0].cover.startswith("https://cdn.example.org/")
    assert page.items[0].key == encode_key(PILL_MANGA_URL)
    assert page.has_next is True


async def test_mangapill_detail_and_pages() -> None:
    source, client = _source(MangapillSource, pill_handler)
    async with client:
        detail = await source.get_manga(encode_key(PILL_MANGA_URL))
        assert detail.title == "One Piece"
        assert detail.cover.startswith("https://cdn.example.org/")
        assert "pirate named Luffy" in detail.description
        assert [chapter.title for chapter in detail.chapters] == ["Chapter 1", "Chapter 2", "Chapter 3"]
        assert detail.chapters[0].number == 1.0

        pages = await source.get_pages(PILL_CHAPTER_URL)
    assert [page.url for page in pages] == [
        "https://cdn.example.org/page/1.jpeg",
        "https://cdn.example.org/page/2.jpeg",
        "https://cdn.example.org/page/3.jpeg",
    ]
    assert pages[0].headers["Referer"] == "https://mangapill.com/"


async def test_weebcentral_search() -> None:
    source, client = _source(WeebCentralSource, wc_handler)
    async with client:
        page = await source.search("one piece", 1)
    assert [item.title for item in page.items] == ["One Piece", "Naruto"]
    assert page.items[0].cover.startswith("https://temp.example.org/")
    assert page.items[0].key == encode_key(WC_SERIES_URL)


async def test_weebcentral_detail_and_pages() -> None:
    source, client = _source(WeebCentralSource, wc_handler)
    async with client:
        detail = await source.get_manga(encode_key(WC_SERIES_URL))
        assert detail.title == "One Piece"
        assert detail.author == "ODA Eiichiro"
        assert "King of the Pirates" in detail.description
        assert [chapter.title for chapter in detail.chapters] == ["Chapter 1", "Chapter 2", "Chapter 3"]
        assert detail.chapters[0].number == 1.0

        pages = await source.get_pages(WC_CHAPTER_URL)
    assert [page.url for page in pages] == [
        "https://scans-hot.example.org/manga/One-Piece/0001-001.png",
        "https://scans-hot.example.org/manga/One-Piece/0001-002.png",
        "https://scans-hot.example.org/manga/One-Piece/0001-003.png",
    ]


async def test_dongman_search() -> None:
    source, client = _source(DongmanSource, dongman_handler)
    async with client:
        page = await source.search("恋爱", 1)
    assert [item.title for item in page.items] == ["恋爱星群", "谢绝职场恋爱！"]
    assert page.items[0].cover.startswith("https://cdn.example.org/")
    assert page.items[0].key == encode_key(DONGMAN_DETAIL_URL)
    assert "恋爱" in page.items[0].description


async def test_dongman_detail_and_pages() -> None:
    source, client = _source(DongmanSource, dongman_handler)
    async with client:
        detail = await source.get_manga(encode_key(DONGMAN_DETAIL_URL))
        assert detail.title == "恋爱星群"
        assert detail.cover.startswith("http://cdn-sns.example.org/")
        assert "星群与恋爱" in detail.description
        assert [chapter.title for chapter in detail.chapters] == ["第1话", "第2话", "第3话"]
        assert detail.chapters[0].number == 1.0

        pages = await source.get_pages(DONGMAN_CHAPTER_URL)
    assert [page.url for page in pages] == [
        "https://cdn.example.org/pages/001.jpg?type=q90",
        "https://cdn.example.org/pages/002.jpg?type=q90",
        "https://cdn.example.org/pages/003.jpg?type=q90",
    ]


async def test_nhentai_search() -> None:
    source, client = _source(NhEntaiSource, nhentai_handler)
    source.http.min_interval = 0.0
    async with client:
        page = await source.search("yuri", 1)
    assert [item.title for item in page.items] == ["Test Gallery One", "Test Gallery Two"]
    assert page.items[0].cover == "https://t1.example.org/galleries/9/thumb.jpg"
    assert page.items[0].key == encode_key(NHENTAI_URL)
    assert page.has_next is True


async def test_nhentai_detail_and_pages() -> None:
    source, client = _source(NhEntaiSource, nhentai_handler)
    source.http.min_interval = 0.0
    async with client:
        detail = await source.get_manga(encode_key(NHENTAI_URL))
        assert detail.title == "Test Gallery"
        assert detail.cover == "https://i1.example.org/galleries/9/cover.jpg"
        assert detail.tags == ["chinese", "yuri"]
        assert len(detail.chapters) == 1
        assert detail.chapters[0].title == "Test Gallery"

        pages = await source.get_pages(NHENTAI_CHAPTER_URL)
    assert [page.url for page in pages] == [
        "https://i1.example.org/galleries/9/1.jpg",
        "https://i1.example.org/galleries/9/2.jpg",
    ]


@pytest.mark.parametrize("source_id", ["mangapill", "weebcentral", "dongman", "nhentai"])
async def test_builtin_real_sources_registered(tmp_path, source_id: str) -> None:
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        data_dir=tmp_path / "data",
        demo_source=False,
        mangapill=True,
        weebcentral=True,
        dongman=True,
        nhentai=True,
        secret_key="real-source-test",
        check_interval_min=0,
        log_level="WARNING",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            sources = (await http.get("/api/sources")).json()["sources"]
    source = next((item for item in sources if item["id"] == source_id), None)
    assert source is not None
    assert source["enabled"] is True
    assert source["has_config"] is False
    assert source["base_url"].startswith("https://")
