from __future__ import annotations

import time
from urllib.parse import quote

from ..services.http_client import SourceHTTP
from ..services.placeholder import render_cover, render_page
from .base import (
    ChapterRef,
    MangaDetail,
    PageRef,
    SearchPage,
    SearchResult,
    Source,
    encode_key,
    resolve_key,
)

SERIES: list[dict] = [
    {
        "slug": "starfall",
        "title": "Starfall Chronicles",
        "author": "A. Writer",
        "tags": ["Fantasy", "Adventure"],
        "status": "Ongoing",
        "description": (
            "When the sky starts falling one star at a time, a cartographer and a retired "
            "astronaut must map the holes in the night before the last light goes out."
        ),
        "chapters": ["Chapter 1: The First Star", "Chapter 2: Falling Slowly", "Chapter 3: The Last Light"],
    },
    {
        "slug": "quiet-hours",
        "title": "Quiet Hours",
        "author": "Mina Ito",
        "tags": ["Slice of Life", "Drama"],
        "status": "Completed",
        "description": (
            "A night-shift librarian catalogues the small, strange lives that pass through her reading room."
        ),
        "chapters": ["Chapter 1: Night Shift", "Chapter 2: Regulars", "Chapter 3: Closing Time", "Chapter 4: Dawn"],
    },
    {
        "slug": "iron-garden",
        "title": "Iron Garden",
        "author": "R. Calder",
        "tags": ["Sci-Fi", "Mecha"],
        "status": "Ongoing",
        "description": "Maintenance crews keep a generation ship alive by growing machines instead of crops.",
        "chapters": ["Chapter 1: Seed Bank", "Chapter 2: Rust Bloom"],
    },
    {
        "slug": "paper-moon",
        "title": "Paper Moon Detective",
        "author": "K. Sato",
        "tags": ["Mystery", "Comedy"],
        "status": "Ongoing",
        "description": "A detective who can only solve crimes written on paper takes the strangest case of her career.",
        "chapters": ["Chapter 1: The Folded Clue", "Chapter 2: Red Ink"],
    },
    {
        "slug": "salt-and-signal",
        "title": "Salt and Signal",
        "author": "L. Moreno",
        "tags": ["Adventure", "Romance"],
        "status": "Ongoing",
        "description": "Two lighthouse keepers communicate across a sea that should not be there.",
        "chapters": ["Chapter 1: Low Tide", "Chapter 2: Static"],
    },
    {
        "slug": "tiny-giants",
        "title": "Tiny Giants",
        "author": "B. Okafor",
        "tags": ["Sports", "Coming of Age"],
        "status": "Completed",
        "description": (
            "A middle-school basketball team of unexpected heights learns that size is a strategy, not a limit."
        ),
        "chapters": ["Chapter 1: Tryouts", "Chapter 2: Full Court", "Chapter 3: Overtime"],
    },
]

PAGES_PER_CHAPTER = 6
_page_cache: dict[str, bytes] = {}
_cover_cache: dict[str, bytes] = {}


def find_series(slug: str) -> dict | None:
    return next((item for item in SERIES if item["slug"] == slug), None)


def _series_key(slug: str) -> str:
    return f"demo://{slug}"


def _chapter_key(slug: str, index: int) -> str:
    return f"demo://{slug}/{index}"


def demo_page_bytes(chapter_key: str, number: int) -> bytes:
    key = f"{chapter_key}#{number}"
    if key in _page_cache:
        return _page_cache[key]
    raw = resolve_key(chapter_key) if not chapter_key.startswith("demo://") else chapter_key
    parts = raw.replace("demo://", "").split("/")
    slug = parts[0]
    index = parts[1] if len(parts) > 1 else "0"
    series = find_series(slug) or SERIES[0]
    chapter_index = int(index)
    chapters = series["chapters"]
    chapter_title = chapters[min(chapter_index, len(chapters) - 1)]
    data = render_page(series["title"], chapter_title, number, PAGES_PER_CHAPTER)
    _page_cache[key] = data
    return data


def demo_cover_bytes(series_key: str) -> bytes:
    if series_key in _cover_cache:
        return _cover_cache[series_key]
    raw = resolve_key(series_key) if not series_key.startswith("demo://") else series_key
    series = find_series(raw.replace("demo://", "")) or SERIES[0]
    data = render_cover(series["title"], series.get("author", ""))
    _cover_cache[series_key] = data
    return data


class DemoSource(Source):
    id = "demo"
    name = "Demo Library (offline)"
    lang = "en"
    nsfw = False
    engine = "demo"
    direction = "ltr"
    base_url = "demo://demo"
    enabled_by_default = True

    def __init__(self, http: SourceHTTP) -> None:
        super().__init__(http)
        self._started = time.monotonic()

    def _result(self, series: dict) -> SearchResult:
        key = encode_key(_series_key(series["slug"]))
        return SearchResult(
            source_id=self.id,
            key=key,
            title=series["title"],
            url=_series_key(series["slug"]),
            cover=f"/api/demo/cover?key={quote(key)}",
            description=series["description"],
            tags=list(series["tags"]),
        )

    async def search(self, query: str, page: int = 1) -> SearchPage:
        needle = (query or "").strip().lower()
        items = [self._result(series) for series in SERIES]
        if needle:
            items = [
                item
                for item in items
                if needle in item.title.lower()
                or needle in item.description.lower()
                or any(needle in tag.lower() for tag in item.tags)
            ]
        return SearchPage(items=items, page=page)

    async def popular(self, page: int = 1) -> SearchPage:
        return SearchPage(items=[self._result(series) for series in SERIES], page=page)

    async def get_manga(self, key: str) -> MangaDetail:
        raw = resolve_key(key)
        slug = raw.replace("demo://", "").split("/")[0]
        series = find_series(slug)
        if series is None:
            raise ValueError(f"unknown demo series: {slug}")
        chapters = [
            ChapterRef(
                key=encode_key(_chapter_key(slug, index)),
                title=title,
                url=_chapter_key(slug, index),
                number=float(index + 1),
            )
            for index, title in enumerate(series["chapters"])
        ]
        return MangaDetail(
            key=key,
            title=series["title"],
            url=raw,
            cover=f"/api/demo/cover?key={quote(encode_key(raw))}",
            description=series["description"],
            author=series["author"],
            status=series["status"],
            tags=list(series["tags"]),
            chapters=chapters,
        )

    async def get_pages(self, chapter_url: str) -> list[PageRef]:
        raw = resolve_key(chapter_url) if not chapter_url.startswith("demo://") else chapter_url
        parts = raw.replace("demo://", "").split("/")
        slug = parts[0]
        index = int(parts[1]) if len(parts) > 1 else 0
        series = find_series(slug) or SERIES[0]
        chapter_title = series["chapters"][min(index, len(series["chapters"]) - 1)]
        pages: list[PageRef] = []
        for number in range(1, PAGES_PER_CHAPTER + 1):
            pages.append(
                PageRef(
                    url=f"/api/demo/page?key={quote(encode_key(raw))}&n={number}",
                    inline=render_page(series["title"], chapter_title, number, PAGES_PER_CHAPTER),
                    ext="jpg",
                )
            )
        return pages
