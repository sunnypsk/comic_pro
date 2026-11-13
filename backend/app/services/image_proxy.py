from __future__ import annotations

import asyncio

import httpx

from ..config import Settings
from .fetcher import get_image
from .page_cache import PageCache
from .slugs import image_signature, new_expiry, verify_signature


class ImageProxy:
    """Signed, cached image delivery for third-party pages (hotlink/cors workaround)."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        cache: PageCache,
        secret: str,
        base_path: str = "",
    ) -> None:
        self.settings = settings
        self.client = client
        self.cache = cache
        self.secret = secret
        self.base_path = base_path
        self._inflight: dict[str, asyncio.Future] = {}

    def signed_url(self, source_id: str, url: str) -> str:
        expires = new_expiry()
        signature = image_signature(self.secret, source_id, url, expires)
        from urllib.parse import quote

        return (
            f"{self.base_path}/api/img?u={quote(url, safe='')}"
            f"&s={quote(source_id, safe='')}&e={expires}&sig={signature}"
        )

    def verify(self, source_id: str, url: str, expires: int, signature: str) -> bool:
        import time

        if expires < int(time.time()):
            return False
        return verify_signature(self.secret, f"img|{source_id}|{url}|{expires}", signature)

    async def fetch(self, source_id: str, url: str, referer: str = "") -> tuple[bytes, str, str]:
        cached = self.cache.get(url)
        if cached is not None:
            ext = cached.suffix.lstrip(".") or "jpg"
            media = "image/jpeg" if ext == "jpg" else f"image/{ext}"
            return cached.read_bytes(), ext, media

        key = self.cache.digest(url)
        future = self._inflight.get(key)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._inflight[key] = future
            try:
                headers = {"Referer": referer} if referer else {}
                data, ext, media = await get_image(
                    self.client, url, headers=headers, max_bytes=self.settings.max_image_mb * 1024 * 1024
                )
                self.cache.put(url, data, ext)
                future.set_result((data, ext, media))
            except asyncio.CancelledError:
                future.cancel()
                raise
            except Exception as exc:  # noqa: BLE001 - propagate to all waiters
                future.set_exception(exc)
            finally:
                self._inflight.pop(key, None)
        return await future
