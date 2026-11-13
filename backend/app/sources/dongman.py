from __future__ import annotations

import re
import time
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

_EPISODE_NOISE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}.*$|like\d*#?\d*$")


class DongmanSource(Source):
    """咚漫 (Dongman Manhua) — official simplified-Chinese webtoon catalogue."""

    id = "dongman"
    name = "咚漫（简体）"
    lang = "zh"
    nsfw = False
    engine = "html"
    direction = "ltr"
    base_url = "https://www.dongmanmanhua.cn"
    enabled_by_default = True

    def __init__(self, http: SourceHTTP) -> None:
        super().__init__(http)
        self._cache: dict[str, tuple[float, MangaDetail]] = {}

    def _absolute(self, value: str) -> str:
        return urljoin(self.base_url + "/", value)

    async def _root(self, url: str, referer: str | None = None):
        headers = {"Referer": referer or self.base_url + "/"}
        html = await self.http.text(url, headers=headers)
        return selectors.parse(html)

    async def search(self, query: str, page: int = 1) -> SearchPage:
        if page > 1:
            return SearchPage(items=[], page=page)
        html = await self.http.text(
            f"{self.base_url}/search",
            params={"keyword": query},
            headers={"Referer": self.base_url + "/"},
        )
        root = selectors.parse(html)
        items: list[SearchResult] = []
        seen: set[str] = set()
        for anchor in root.css("ul.card_lst li a.card_item"):
            href = anchor.attrs.get("href", "")
            if not href:
                continue
            url = self._absolute(href)
            if url in seen:
                continue
            seen.add(url)
            cover = selectors.extract(anchor, "img@src")
            genre = selectors.extract(anchor, ".genre")
            author = selectors.extract(anchor, ".author")
            items.append(
                SearchResult(
                    source_id=self.id,
                    key=encode_key(url),
                    title=selectors.extract(anchor, ".subj") or selectors.text_of(anchor),
                    url=url,
                    cover=self._absolute(cover) if cover else "",
                    description=" · ".join(part for part in (genre, author) if part),
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
        chapters = self._episodes(root)
        if chapters:
            try:
                viewer = await self._root(chapters[0].url, referer=url)
                expanded = self._episodes(viewer)
                if expanded:
                    chapters = expanded
            except Exception:  # noqa: BLE001 - fall back to the detail list
                pass
        chapters.sort(key=lambda chapter: (chapter.number is None, chapter.number or 0))

        detail = MangaDetail(
            key=encode_key(url),
            title=selectors.extract(root, "h1") or selectors.extract(root, "meta:og:title") or url,
            url=url,
            cover=selectors.extract(root, "meta:og:image"),
            description=selectors.extract(root, "meta:og:description"),
            author=selectors.extract(root, "p.author, .author"),
            chapters=chapters,
        )
        self._cache[url] = (time.monotonic() + 300, detail)
        return detail

    def _episodes(self, root) -> list[ChapterRef]:
        chapters: list[ChapterRef] = []
        seen: set[str] = set()
        for anchor in root.css("a[href*='episode_no=']"):
            href = anchor.attrs.get("href", "")
            if not href:
                continue
            chapter_url = self._absolute(href)
            if chapter_url in seen:
                continue
            title = selectors.extract(anchor, ".subj") or selectors.text_of(anchor)
            title = _EPISODE_NOISE.sub("", title).strip()
            if not title or title in ("上一集", "下一集", "上一话", "下一话"):
                continue
            seen.add(chapter_url)
            chapters.append(
                ChapterRef(
                    key=encode_key(chapter_url),
                    title=title,
                    url=chapter_url,
                    number=chapter_number(title),
                )
            )
        return chapters

    async def get_pages(self, chapter_url: str) -> list[PageRef]:
        url = resolve_key(chapter_url)
        if url.startswith("/"):
            url = self._absolute(url)
        root = await self._root(url)
        pages: list[PageRef] = []
        seen: set[str] = set()
        for node in root.css("img._images"):
            source = node.attrs.get("data-url") or node.attrs.get("data-src") or ""
            if not source.startswith("http") or "bg_transparency" in source:
                continue
            if source in seen:
                continue
            seen.add(source)
            pages.append(PageRef(url=source, headers={"Referer": self.base_url + "/"}))
        return pages
