from __future__ import annotations

import time
from urllib.parse import quote_plus, urljoin

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


class WeebCentralSource(Source):
    """Weeb Central — static HTML series pages plus an HTML image fragment endpoint."""

    id = "weebcentral"
    name = "Weeb Central"
    lang = "en"
    nsfw = False
    engine = "html"
    direction = "rtl"
    base_url = "https://weebcentral.com"
    enabled_by_default = True

    def __init__(self, http: SourceHTTP) -> None:
        super().__init__(http)
        self._cache: dict[str, tuple[float, MangaDetail]] = {}

    def _absolute(self, value: str) -> str:
        return urljoin(self.base_url + "/", value)

    async def _root(self, url: str, *, htmx: bool = False):
        headers = {"Referer": self.base_url + "/"}
        if htmx:
            headers["HX-Request"] = "true"
        html = await self.http.text(url, headers=headers)
        return selectors.parse(html)

    async def search(self, query: str, page: int = 1) -> SearchPage:
        if page > 1:
            return SearchPage(items=[], page=page)
        root = await self._root(
            f"{self.base_url}/search/data?text={quote_plus(query)}", htmx=True
        )
        items: list[SearchResult] = []
        seen: set[str] = set()
        for article in root.css("article"):
            link = None
            title = ""
            for anchor in article.css("a[href*='/series/']"):
                href = anchor.attrs.get("href", "")
                if not href:
                    continue
                link = link or href
                text = selectors.text_of(anchor).removeprefix("Official").strip()
                if text and len(text) > len(title):
                    title = text
            if not link:
                continue
            url = self._absolute(link)
            if url in seen:
                continue
            seen.add(url)
            img = article.css_first("img")
            cover = (img.attrs.get("src") or "") if img is not None else ""
            items.append(
                SearchResult(
                    source_id=self.id,
                    key=encode_key(url),
                    title=title or url.rsplit("/", 1)[-1].replace("-", " "),
                    url=url,
                    cover=self._absolute(cover) if cover else "",
                )
            )
        return SearchPage(items=items, page=page, has_next=False)

    async def get_manga(self, key: str) -> MangaDetail:
        url = resolve_key(key)
        if url.startswith("/"):
            url = self._absolute(url)
        cached = self._cache.get(url)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        root = await self._root(url)
        title = selectors.extract(root, "h1") or url.rsplit("/", 1)[-1].replace("-", " ")
        cover = selectors.extract(root, "meta:og:image")
        description = selectors.extract(root, "p.whitespace-pre-wrap")
        author = selectors.extract(root, "a[href^='/search?author=']")

        chapters: list[ChapterRef] = []
        seen: set[str] = set()
        series_id = url.rstrip("/").split("/series/")[-1].split("/")[0]
        list_url = f"{self.base_url}/series/{series_id}/full-chapter-list"
        listing = await self._root(list_url, htmx=True)
        for anchor in listing.css("a[href^='/chapters/']"):
            href = anchor.attrs.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            chapter_url = self._absolute(href)
            text = selectors.text_of(anchor).split("Last Read")[0].strip()
            chapter_title = text or "Chapter"
            chapters.append(
                ChapterRef(
                    key=encode_key(chapter_url),
                    title=chapter_title,
                    url=chapter_url,
                    number=chapter_number(chapter_title),
                )
            )
        chapters.reverse()  # newest first on the site

        detail = MangaDetail(
            key=encode_key(url),
            title=title,
            url=url,
            cover=cover,
            description=description,
            author=author,
            chapters=chapters,
        )
        self._cache[url] = (time.monotonic() + 300, detail)
        return detail

    async def get_pages(self, chapter_url: str) -> list[PageRef]:
        url = resolve_key(chapter_url)
        if url.startswith("/"):
            url = self._absolute(url)
        root = await self._root(url.rstrip("/") + "/images")
        nodes = root.css("img[alt^='Page']")
        if not nodes:
            nodes = [node for node in root.css("img") if "/manga/" in (node.attrs.get("src") or "")]
        pages: list[PageRef] = []
        seen: set[str] = set()
        for node in nodes:
            source = node.attrs.get("src") or node.attrs.get("data-src") or ""
            if not source or source.startswith("data:"):
                continue
            absolute = self._absolute(source)
            if absolute in seen:
                continue
            seen.add(absolute)
            pages.append(PageRef(url=absolute, headers={"Referer": self.base_url + "/"}))
        return pages
