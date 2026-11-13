from __future__ import annotations

import re
import time
from html import unescape
from urllib.parse import urljoin

from ..services.http_client import SourceHTTP
from . import selectors
from .base import (
    ChapterRef,
    MangaDetail,
    PageRef,
    SearchPage,
    SearchResult,
    Source,
    chapter_number,
    encode_key,
    resolve_key,
)

_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_html_text(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", value)
    text = _TAG.sub(" ", text)
    text = unescape(text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES.sub("\n\n", text).strip()


class MangapillSource(Source):
    """Mangapill (manga aggregator) — static HTML, no browser required."""

    id = "mangapill"
    name = "Mangapill"
    lang = "en"
    nsfw = False
    engine = "html"
    direction = "rtl"
    base_url = "https://mangapill.com"
    enabled_by_default = True

    def __init__(self, http: SourceHTTP) -> None:
        super().__init__(http)
        self._cache: dict[str, tuple[float, MangaDetail]] = {}

    async def _fetch(self, url: str):
        html = await self.http.text(url, headers={"Referer": self.base_url + "/"})
        return selectors.parse(html)

    async def search(self, query: str, page: int = 1) -> SearchPage:
        html = await self.http.text(
            f"{self.base_url}/search",
            params={"q": query, "page": page},
            headers={"Referer": self.base_url + "/"},
        )
        root = selectors.parse(html)
        cards: dict[str, SearchResult] = {}
        for node in root.css("a[href^='/manga/']"):
            href = node.attrs.get("href", "")
            if not href:
                continue
            url = urljoin(self.base_url, href)
            title = selectors.text_of(node)
            cover = selectors.first_image(node)
            existing = cards.get(url)
            if existing is None:
                cards[url] = SearchResult(
                    source_id=self.id,
                    key=encode_key(url),
                    title=title,
                    url=url,
                    cover=urljoin(self.base_url, cover) if cover else "",
                )
            else:
                if not existing.title and title:
                    existing.title = title
                if not existing.cover and cover:
                    existing.cover = urljoin(self.base_url, cover)
        items = [item for item in cards.values() if item.title]
        has_next = bool(root.css(f"a[href*='page={page + 1}']"))
        return SearchPage(items=items, page=page, has_next=has_next)

    async def get_manga(self, key: str) -> MangaDetail:
        url = resolve_key(key)
        cached = self._cache.get(url)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        root = await self._fetch(url)
        chapters: list[ChapterRef] = []
        seen: set[str] = set()
        for node in root.css("a[href^='/chapters/']"):
            href = node.attrs.get("href", "")
            if not href or href.rstrip("/") == "/chapters":
                continue
            chapter_url = urljoin(self.base_url, href)
            if chapter_url in seen:
                continue
            seen.add(chapter_url)
            title = selectors.text_of(node) or "Chapter"
            chapters.append(
                ChapterRef(
                    key=encode_key(chapter_url),
                    title=title,
                    url=chapter_url,
                    number=chapter_number(title),
                )
            )
        chapters.reverse()  # site lists newest first

        detail = MangaDetail(
            key=encode_key(url),
            title=selectors.extract(root, "h1") or selectors.extract(root, "meta:og:title") or url,
            url=url,
            cover=selectors.extract(root, "meta:og:image"),
            description=clean_html_text(selectors.extract(root, "meta:description")),
            author=selectors.extract(root, "a[href*='/search?q=']"),
            chapters=chapters,
        )
        self._cache[url] = (time.monotonic() + 300, detail)
        return detail

    async def get_pages(self, chapter_url: str) -> list[PageRef]:
        url = resolve_key(chapter_url)
        root = await self._fetch(url)
        nodes = root.css("img.js-page")
        if not nodes:
            nodes = root.css("img[data-src]")
        pages: list[PageRef] = []
        seen: set[str] = set()
        for node in nodes:
            source = node.attrs.get("data-src") or node.attrs.get("src") or ""
            if not source or source.startswith("data:"):
                continue
            absolute = urljoin(self.base_url, source)
            if absolute in seen:
                continue
            seen.add(absolute)
            pages.append(PageRef(url=absolute, headers={"Referer": self.base_url + "/"}))
        return pages
