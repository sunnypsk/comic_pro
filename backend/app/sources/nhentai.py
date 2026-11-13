from __future__ import annotations

import re
import time

from ..services.http_client import SourceHTTP
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

_GALLERY_ID = re.compile(r"/(?:g|galleries)/(\d+)")


class NhEntaiSource(Source):
    """nhentai — adult doujinshi gallery, uses the public API v2 endpoints.

    Search and gallery reads are public; the API asks for a descriptive
    User-Agent and applies per-IP rate limits. Image paths come from the API
    and must be joined with a server from `/api/v2/cdn`.
    """

    id = "nhentai"
    name = "nhentai (NSFW)"
    lang = "ja"
    nsfw = True
    engine = "api"
    direction = "rtl"
    base_url = "https://nhentai.net"
    enabled_by_default = True

    def __init__(self, http: SourceHTTP) -> None:
        super().__init__(http)
        self.http.min_interval = max(self.http.min_interval, 1.0)
        self._cdn: tuple[float, list[str], list[str]] | None = None
        self._galleries: dict[int, tuple[float, dict]] = {}

    async def _servers(self) -> tuple[str, str]:
        if self._cdn and self._cdn[0] > time.monotonic():
            return self._cdn[1][0], self._cdn[2][0]
        try:
            data = await self.http.json(f"{self.base_url}/api/v2/cdn")
            images = [item.rstrip("/") for item in data.get("image_servers") or []]
            thumbs = [item.rstrip("/") for item in data.get("thumb_servers") or []]
            if images and thumbs:
                self._cdn = (time.monotonic() + 3600, images, thumbs)
                return images[0], thumbs[0]
        except Exception:  # noqa: BLE001 - fall back to the historical hosts
            pass
        return "https://i.nhentai.net", "https://t.nhentai.net"

    @staticmethod
    def _url(server: str, path: str) -> str:
        return f"{server.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _gallery_id(key: str) -> int:
        raw = resolve_key(key)
        match = _GALLERY_ID.search(raw)
        if match:
            return int(match.group(1))
        if raw.strip().isdigit():
            return int(raw.strip())
        raise ValueError(f"invalid nhentai gallery: {key}")

    async def _gallery(self, gallery_id: int) -> dict:
        cached = self._galleries.get(gallery_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        data = await self.http.json(
            f"{self.base_url}/api/v2/galleries/{gallery_id}",
            headers={"Accept": "application/json"},
        )
        self._galleries[gallery_id] = (time.monotonic() + 300, data)
        return data

    async def search(self, query: str, page: int = 1) -> SearchPage:
        data = await self.http.json(
            f"{self.base_url}/api/v2/search",
            params={"query": query, "page": page, "sort": "date"},
            headers={"Accept": "application/json"},
        )
        _image, thumb_server = await self._servers()
        items: list[SearchResult] = []
        for row in data.get("result") or []:
            gallery_id = row.get("id")
            if not gallery_id:
                continue
            items.append(
                SearchResult(
                    source_id=self.id,
                    key=encode_key(f"{self.base_url}/g/{gallery_id}/"),
                    title=row.get("english_title") or row.get("japanese_title") or f"Gallery {gallery_id}",
                    url=f"{self.base_url}/g/{gallery_id}/",
                    cover=self._url(thumb_server, row.get("thumbnail") or ""),
                    description=f"{row.get('num_pages', 0)} 页 · {row.get('num_favorites', 0)} 收藏",
                )
            )
        return SearchPage(
            items=items,
            page=page,
            has_next=page < int(data.get("num_pages") or 1),
        )

    async def get_manga(self, key: str) -> MangaDetail:
        gallery_id = self._gallery_id(key)
        data = await self._gallery(gallery_id)
        image_server, _thumb = await self._servers()
        title_info = data.get("title") or {}
        title = (
            title_info.get("pretty")
            or title_info.get("english")
            or title_info.get("japanese")
            or f"Gallery {gallery_id}"
        )
        cover_path = (data.get("cover") or {}).get("path") or ""
        tags = [tag.get("name", "") for tag in data.get("tags") or [] if tag.get("name")]
        description = " · ".join(tags[:12])
        if data.get("num_pages"):
            description = f"{description} · {data['num_pages']}P" if description else f"{data['num_pages']}P"

        gallery_url = f"{self.base_url}/g/{gallery_id}/"
        return MangaDetail(
            key=encode_key(gallery_url),
            title=title,
            url=gallery_url,
            cover=self._url(image_server, cover_path) if cover_path else "",
            description=description,
            tags=tags[:12],
            chapters=[
                ChapterRef(
                    key=encode_key(gallery_url),
                    title=title,
                    url=gallery_url,
                    number=1.0,
                )
            ],
        )

    async def get_pages(self, chapter_url: str) -> list[PageRef]:
        gallery_id = self._gallery_id(chapter_url)
        data = await self._gallery(gallery_id)
        image_server, _thumb = await self._servers()
        pages: list[PageRef] = []
        for page in data.get("pages") or []:
            path = page.get("path") or ""
            if not path:
                continue
            pages.append(
                PageRef(
                    url=self._url(image_server, path),
                    headers={"Referer": self.base_url + "/"},
                )
            )
        return pages
