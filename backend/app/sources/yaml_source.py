from __future__ import annotations

import re
import time
from typing import Any
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

GENERIC_DEFAULTS: dict[str, Any] = {
    "engine": "generic",
    "direction": "rtl",
    "search": {
        "url": "/?s={q}",
        "item": ".post",
        "title": "h2 a",
        "link": "h2 a@href",
        "cover": "img@src",
    },
    "manga": {
        "title": "h1",
        "cover": "meta:og:image",
        "description": ".entry-content",
        "chapters": {"item": ".chapter-list a", "title": "", "link": "@href"},
    },
    "chapter": {
        "images": [".reading-content img", ".entry-content img", "article img"],
        "attrs": ["data-src", "data-lazy-src", "data-original", "src"],
    },
}

MADARA_DEFAULTS: dict[str, Any] = {
    "engine": "madara",
    "direction": "rtl",
    "search": {
        "url": "/?s={q}&post_type=wp-manga",
        "item": ".c-tabs-item__content, .row.c-tabs-item__content",
        "title": ".post-title h3 a, .post-title a",
        "link": ".post-title h3 a@href, .post-title a@href",
        "cover": "img@src",
        "description": ".post-content_item .summary-content, .latest-chap .chapter a",
    },
    "manga": {
        "title": ".post-title h1",
        "cover": ".summary_image img@src",
        "description": ".description-summary, .summary-content",
        "author": ".author-content",
        "status": ".post-status .summary-content",
        "tags": ".genres-content a",
        "chapters": {
            "item": ".wp-manga-chapter, li.wp-manga-chapter",
            "title": "a",
            "link": "a@href",
            "date": "span.chapter-release-date, span",
        },
    },
    "chapter": {
        "images": [".reading-content img", ".reading-content .page-break img"],
        "attrs": ["data-src", "data-lazy-src", "data-original", "src"],
    },
    "popular": {
        "url": "/?post_type=wp-manga&m_orderby=views",
        "item": ".c-tabs-item__content",
        "title": ".post-title h3 a, .post-title a",
        "link": ".post-title h3 a@href, .post-title a@href",
        "cover": "img@src",
    },
}

MANGASTREAM_DEFAULTS: dict[str, Any] = {
    "engine": "mangastream",
    "direction": "ltr",
    "search": {
        "url": "/?s={q}",
        "item": ".bs .bsx, .listupd .bsx",
        "title": ".tt",
        "link": "a@href",
        "cover": "img@src",
    },
    "manga": {
        "title": ".entry-title, h1",
        "cover": ".thumb img@src, meta:og:image",
        "description": ".entry-content[itemprop=description], .desc",
        "chapters": {"item": "#chapterlist li a, .eplister li a", "title": "", "link": "@href"},
    },
    "chapter": {
        "images": ["#readerarea img", ".entry-content img"],
        "attrs": ["src", "data-src", "data-lazy-src"],
    },
    "popular": {
        "url": "/manga/?order=popular",
        "item": ".listupd .bsx",
        "title": ".tt",
        "link": "a@href",
        "cover": "img@src",
    },
}

ENGINE_DEFAULTS = {
    "generic": GENERIC_DEFAULTS,
    "madara": MADARA_DEFAULTS,
    "mangastream": MANGASTREAM_DEFAULTS,
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        elif value is not None:
            result[key] = value
    return result


def _fmt(template: str, **values: str) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


class YamlSource(Source):
    """Declarative source driven by a YAML config (CSS selectors + optional regex)."""

    def __init__(self, http: SourceHTTP, config: dict[str, Any]) -> None:
        engine = str(config.get("engine") or "generic").lower()
        defaults = ENGINE_DEFAULTS.get(engine, GENERIC_DEFAULTS)
        merged = deep_merge(defaults, config)
        super().__init__(http)
        self.config = merged
        self.id = str(merged.get("id") or "").strip()
        self.name = str(merged.get("name") or self.id).strip()
        self.base_url = str(merged.get("base_url") or "").rstrip("/")
        self.lang = str(merged.get("lang") or "en")
        self.nsfw = bool(merged.get("nsfw"))
        self.engine = engine
        self.direction = str(merged.get("direction") or "rtl")
        self.enabled_by_default = bool(merged.get("enabled", True))
        self._cache: dict[str, tuple[float, MangaDetail]] = {}
        if not self.id or not self.base_url:
            raise ValueError("source config needs both id and base_url")

    # ------------------------------------------------------------------ helpers
    def _abs(self, value: str, base: str | None = None) -> str:
        if not value:
            return ""
        return urljoin(base or self.base_url + "/", value)

    def _cfg(self, *path: str) -> Any:
        node: Any = self.config
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    def _headers(self) -> dict[str, str]:
        headers = dict(self._cfg("headers") or {})
        if self.base_url.startswith("http"):
            headers.setdefault("Referer", self.base_url + "/")
        return headers

    async def _page(self, url: str, referer: str | None = None):
        headers = self._headers()
        if referer:
            headers["Referer"] = referer
        html = await self.http.text(url, headers=headers)
        return selectors.parse(html)

    def _to_result(self, node, cfg: dict[str, Any]) -> SearchResult | None:
        link = selectors.extract(node, cfg.get("link"))
        if not link:
            return None
        url = self._abs(link)
        title = selectors.extract(node, cfg.get("title")) or selectors.text_of(node)
        cover = selectors.extract(node, cfg.get("cover")) or selectors.first_image(node)
        description = selectors.extract(node, cfg.get("description"))
        return SearchResult(
            source_id=self.id,
            key=encode_key(url),
            title=title.strip(),
            url=url,
            cover=self._abs(cover) if cover else "",
            description=description,
        )

    def _collect(self, root, cfg: dict[str, Any]) -> list[SearchResult]:
        items: list[SearchResult] = []
        seen: set[str] = set()
        for node in root.css(cfg.get("item", "")):
            result = self._to_result(node, cfg)
            if result and result.url not in seen:
                seen.add(result.url)
                items.append(result)
        return items

    # ----------------------------------------------------------------- actions
    async def search(self, query: str, page: int = 1) -> SearchPage:
        cfg = self._cfg("search") or {}
        template = cfg.get("url")
        if not template:
            return SearchPage(items=[], page=page)
        url = self._abs(_fmt(template, q=quote_plus(query), page=str(page)))
        root = await self._page(url)
        items = self._collect(root, cfg)
        next_spec = cfg.get("next")
        has_next = bool(next_spec and selectors.extract(root, next_spec))
        if not has_next:
            has_next = len(items) > 0 and cfg.get("paginated", False)
        return SearchPage(items=items, page=page, has_next=has_next)

    async def popular(self, page: int = 1) -> SearchPage:
        cfg = self._cfg("popular")
        if not cfg:
            return SearchPage(items=[], page=page)
        url = self._abs(_fmt(cfg.get("url", ""), q="", page=str(page)))
        root = await self._page(url)
        return SearchPage(items=self._collect(root, cfg), page=page)

    async def get_manga(self, key: str) -> MangaDetail:
        url = resolve_key(key)
        cached = self._cache.get(url)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        root = await self._page(url)
        cfg = self._cfg("manga") or {}
        title = selectors.extract(root, cfg.get("title")) or selectors.extract(root, "meta:og:title")
        cover = selectors.extract(root, cfg.get("cover")) or selectors.extract(root, "meta:og:image")
        description = selectors.extract(root, cfg.get("description"))
        author = selectors.extract(root, cfg.get("author"))
        status = selectors.extract(root, cfg.get("status"))
        tags = selectors.extract_all(root, cfg.get("tags"))

        chapters: list[ChapterRef] = []
        seen: set[str] = set()
        chapter_cfg = cfg.get("chapters") or {}
        for node in root.css(chapter_cfg.get("item", "")):
            link = selectors.extract(node, chapter_cfg.get("link"))
            if not link and getattr(node, "tag", "") == "a":
                link = node.attrs.get("href") or ""
            if not link:
                continue
            chapter_url = self._abs(link)
            if chapter_url in seen:
                continue
            seen.add(chapter_url)
            chapter_title = selectors.extract(node, chapter_cfg.get("title")) or selectors.text_of(node)
            chapter_title = chapter_title.strip() or "Chapter"
            date = selectors.extract(node, chapter_cfg.get("date")) or None
            chapters.append(
                ChapterRef(
                    key=encode_key(chapter_url),
                    title=chapter_title,
                    url=chapter_url,
                    number=chapter_number(chapter_title),
                    published_at=date,
                )
            )
        chapters.reverse()  # most sites list newest first

        detail = MangaDetail(
            key=encode_key(url),
            title=title.strip() or url,
            url=url,
            cover=self._abs(cover) if cover else "",
            description=description,
            author=author,
            status=status,
            tags=tags,
            chapters=chapters,
        )
        self._cache[url] = (time.monotonic() + 300, detail)
        return detail

    async def get_pages(self, chapter_url: str) -> list[PageRef]:
        url = self._abs(chapter_url) if not chapter_url.startswith("http") else chapter_url
        cfg = self._cfg("chapter") or {}
        attrs = tuple(cfg.get("attrs") or ("data-src", "data-lazy-src", "src"))
        root = await self._page(url, referer=self.base_url)
        urls: list[str] = []

        regex = cfg.get("regex")
        if regex:
            for match in re.finditer(regex, selectors.html_of(root), re.S):
                urls.append(match.group(1))

        for selector in cfg.get("images") or []:
            for node in root.css(selector):
                target = node if getattr(node, "tag", "") == "img" else None
                if target is None:
                    imgs = node.css("img")
                    target = imgs[0] if imgs else None
                if target is None:
                    continue
                for attr in attrs:
                    value = (target.attrs.get(attr) or "").strip()
                    if value and not value.startswith(("data:", "about:", "javascript:")):
                        urls.append(value)
                        break
            if urls:
                break

        pages: list[PageRef] = []
        seen: set[str] = set()
        for raw in urls:
            absolute = self._abs(raw)
            if not absolute or absolute in seen or len(absolute) < 8:
                continue
            if absolute.endswith((".gif",)) and "loading" in absolute.lower():
                continue
            seen.add(absolute)
            pages.append(PageRef(url=absolute, headers={"Referer": self.base_url + "/"}))
        return pages
