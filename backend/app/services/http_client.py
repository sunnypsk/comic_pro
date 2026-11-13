from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx

DEFAULT_TIMEOUT = 20.0


class SourceError(Exception):
    """A fetch from a comic source failed in a way worth showing to the user."""

    def __init__(self, message: str, code: str = "SOURCE_ERROR", status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class SourceHTTP:
    """Per-source HTTP helper: rate limiting, retries, cookie jar, headers."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout: float = 8.0,
        concurrency: int = 2,
        min_interval: float = 0.25,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.client = client
        self.timeout = timeout
        self.min_interval = max(0.0, min_interval)
        self.default_headers = default_headers or {}
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._pace_lock = asyncio.Lock()
        self._last_request = 0.0
        self._cookies = httpx.Cookies()

    async def _pace(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._pace_lock:
            now = time.monotonic()
            wait = self._last_request + self.min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        merged = {k: v for k, v in self.default_headers.items() if v}
        if extra:
            merged.update({k: v for k, v in extra.items() if v})
        return merged

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        retries: int = 3,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(retries):
            async with self._semaphore:
                await self._pace()
                try:
                    response = await self.client.get(
                        url,
                        headers=self.headers(headers),
                        params=params,
                        timeout=self.timeout,
                        cookies=self._cookies,
                    )
                except httpx.HTTPError as exc:  # network/timeout errors
                    if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                        raise SourceError(
                            "source TLS certificate could not be verified (proxy or region block)",
                            "SOURCE_TLS",
                        ) from exc
                    last_error = exc
                    await asyncio.sleep(0.6 * (2**attempt) + random.random() * 0.2)
                    continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                retry_after = response.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.8 * (2**attempt)
                await asyncio.sleep(min(delay, 15.0) + random.random() * 0.2)
                continue
            if response.status_code == 403:
                raise SourceError("source returned 403 (cookie or browser check)", "SOURCE_BLOCKED", 403)
            if response.status_code == 404:
                raise SourceError("page not found on source", "SOURCE_NOT_FOUND", 404)
            if response.status_code >= 400:
                raise SourceError(f"source returned HTTP {response.status_code}", "SOURCE_ERROR", response.status_code)
            self._cookies.update(response.cookies)
            return response
        raise SourceError(f"request failed: {last_error}", "SOURCE_UNREACHABLE")

    async def text(self, url: str, **kwargs: Any) -> str:
        response = await self.get(url, **kwargs)
        return response.text

    async def json(self, url: str, **kwargs: Any) -> Any:
        return (await self.get(url, **kwargs)).json()
