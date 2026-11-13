from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..services.http_client import SourceHTTP
from ..services.slugs import b64d, b64e

_NUMBER = re.compile(r"(?:chapter|ch\.?|episode|ep\.?|卷|话|話|第)?\s*(\d+(?:\.\d+)?)", re.I)


def encode_key(value: str) -> str:
    return b64e(value)


def decode_key(value: str) -> str:
    try:
        return b64d(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid key: {value}") from exc


def resolve_key(key: str) -> str:
    """Accept either an encoded key or a raw URL (handy for manual testing)."""
    if key.startswith(("http://", "https://", "demo://")):
        return key
    return decode_key(key)


def chapter_number(title: str) -> float | None:
    match = _NUMBER.search(title or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


@dataclass(slots=True)
class SearchResult:
    source_id: str
    key: str
    title: str
    url: str
    cover: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SearchPage:
    items: list[SearchResult]
    page: int = 1
    has_next: bool = False


@dataclass(slots=True)
class ChapterRef:
    key: str
    title: str
    url: str
    number: float | None = None
    published_at: str | None = None


@dataclass(slots=True)
class MangaDetail:
    key: str
    title: str
    url: str
    cover: str = ""
    description: str = ""
    author: str = ""
    status: str = ""
    tags: list[str] = field(default_factory=list)
    chapters: list[ChapterRef] = field(default_factory=list)


@dataclass(slots=True)
class PageRef:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    inline: bytes | None = None
    ext: str = "jpg"


class Source(ABC):
    id: str = ""
    name: str = ""
    lang: str = "en"
    nsfw: bool = False
    direction: str = "rtl"
    engine: str = "generic"
    base_url: str = ""
    enabled_by_default: bool = True

    def __init__(self, http: SourceHTTP) -> None:
        self.http = http

    @abstractmethod
    async def search(self, query: str, page: int = 1) -> SearchPage: ...

    @abstractmethod
    async def get_manga(self, key: str) -> MangaDetail: ...

    @abstractmethod
    async def get_pages(self, chapter_url: str) -> list[PageRef]: ...

    async def popular(self, page: int = 1) -> SearchPage:
        return SearchPage(items=[], page=page)

    async def get_chapters(self, key: str) -> list[ChapterRef]:
        return list((await self.get_manga(key)).chapters)

    def describe(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "lang": self.lang,
            "nsfw": self.nsfw,
            "engine": self.engine,
            "base_url": self.base_url,
            "direction": self.direction,
            "enabled": self.enabled_by_default,
        }
