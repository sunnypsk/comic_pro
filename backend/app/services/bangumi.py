from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from collections import OrderedDict
from typing import Any

import httpx

log = logging.getLogger("comicpro.bangumi")
API_URL = "https://api.bgm.tv/v0"
# Some native titles repeat a romanized name in kana, e.g. "NAME -カナ-".
# Only remove a suffix made entirely of kana, never a volume number or subtitle.
_KANA_SUFFIX = re.compile(r"^([A-Za-z0-9][A-Za-z0-9 .!?'&:-]*?)\s*[-(（]\s*[\u3040-\u30ff\s-]+[)）-]*$")
_SEARCH_OPERATOR = re.compile(r"(?:^|\s)[a-z_]+:\S", re.I)


def normalized_title(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", value).casefold() if char.isalnum())


def _names(subject: dict[str, Any]) -> list[str]:
    values = [subject.get("name_cn"), subject.get("name")]
    for field in subject.get("infobox") or []:
        if not isinstance(field, dict):
            continue
        key, value = field.get("key", ""), field.get("value")
        if key in ("别名", "別名", "中文名", "英文名", "日文名", "原名"):
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, list):
                values.extend(item.get("v") for item in value if isinstance(item, dict))
        elif isinstance(key, str) and key.startswith(("版本:", "版本：")) and isinstance(value, list):
            values.extend(item.get("v") for item in value if isinstance(item, dict) and item.get("k") == "版本名")

    names: dict[str, str] = {}
    for value in values:
        if not isinstance(value, str) or not 1 < len(value.strip()) <= 200:
            continue
        value = value.strip()
        match = _KANA_SUFFIX.fullmatch(value)
        for name in ([match[1].strip(), value] if match else [value]):
            key = normalized_title(name)
            if len(key) > 1:
                names.setdefault(key, name)
    return list(names.values())


def source_queries(query: str, aliases: list[str], lang: str) -> list[str]:
    """Keep the original query first and at most two aliases suited to the source."""
    def preference(name: str) -> bool:
        kana = any("\u3040" <= char <= "\u30ff" for char in name)
        cjk = any("\u3400" <= char <= "\u9fff" for char in name)
        if lang.startswith("en"):
            return not name.isascii()
        if lang.startswith("zh"):
            return not (cjk and not kana)
        if lang.startswith("ja"):
            return not (kana or cjk)
        return False

    return [query, *sorted(aliases, key=preference)[:2]]


class BangumiTitles:
    """Optional, bounded title lookup; no local title dictionary or database writes."""

    def __init__(self, client: httpx.AsyncClient, *, timeout: float, ttl: int, version: str) -> None:
        self.client = client
        self.timeout = timeout
        self.ttl = ttl
        self.headers = {"User-Agent": f"sunnypsk/ComicPro/{version}", "Accept": "application/json"}
        self._cache: OrderedDict[str, tuple[float, list[str]]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._retry_at = 0.0

    def _cached(self, key: str) -> list[str] | None:
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            self._cache.move_to_end(key)
            return list(cached[1])
        self._cache.pop(key, None)
        return None

    def _remember(self, key: str, names: list[str], ttl: float) -> None:
        self._cache[key] = (time.monotonic() + ttl, names)
        self._cache.move_to_end(key)
        while len(self._cache) > 512:
            self._cache.popitem(last=False)

    async def resolve(self, query: str) -> list[str]:
        key = normalized_title(query)
        if len(key) < 2 or _SEARCH_OPERATOR.search(query):
            return []
        cached = self._cached(key)
        if cached is not None:
            return cached
        try:
            # Covers queueing, search and detail requests together.
            async with asyncio.timeout(self.timeout):
                async with self._lock:
                    cached = self._cached(key)
                    if cached is not None:
                        return cached
                    if time.monotonic() < self._retry_at:
                        return []
                    names = await self._lookup(query, key)
                    aliases = [name for name in names if normalized_title(name) != key][:6]
                    self._remember(key, aliases, self.ttl if aliases else 300)
                    return list(aliases)
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError) as exc:
            log.debug("title lookup unavailable: %s", exc)
            self._remember(key, [], 30)
            return []

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        response = await self.client.request(
            method, f"{API_URL}{path}", headers=self.headers, timeout=self.timeout, **kwargs
        )
        if response.status_code == 429:
            retry = response.headers.get("Retry-After", "60")
            self._retry_at = time.monotonic() + (max(1, float(retry)) if retry.isdigit() else 60)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("invalid Bangumi response")
        return body

    async def _lookup(self, query: str, key: str) -> list[str]:
        payload = await self._request(
            "POST", "/search/subjects", params={"limit": 10},
            json={"keyword": query, "sort": "heat", "filter": {"type": [1]}},
        )
        # Only series-level manga, excluding novels, individual volumes and anime.
        candidates = [
            item for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("type") == 1
            and item.get("platform") == "漫画" and item.get("series") is True
        ]
        matches = [item for item in candidates if key in {normalized_title(name) for name in _names(item)}]
        if len(matches) > 1:
            return []  # Ambiguous title: keep ordinary keyword search.
        # Search results omit infobox aliases; inspect a few likely series if needed.
        for item in matches or candidates[:3]:
            subject_id = item.get("id")
            if not isinstance(subject_id, int) or subject_id <= 0:
                continue
            names = _names(item)
            try:
                detail = await self._request("GET", f"/subjects/{subject_id}")
            except httpx.HTTPError:
                if matches:
                    return names  # name/name_cn already provide a verified mapping.
                raise
            if detail.get("type") != 1 or detail.get("platform") != "漫画" or detail.get("series") is not True:
                continue
            names = _names(detail)
            if key in {normalized_title(name) for name in names}:
                return names
        return []
