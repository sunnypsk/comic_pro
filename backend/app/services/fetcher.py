from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx


class FetchError(Exception):
    def __init__(self, message: str, code: str = "FETCH_FAILED") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def sniff_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    return None


async def ensure_public_host(host: str) -> None:
    """Reject hosts that resolve to private, loopback or link-local addresses."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchError(f"cannot resolve host: {host}", "DNS_ERROR") from exc
    for info in infos:
        raw = info[4][0]
        address = ipaddress.ip_address(raw.split("%")[0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise FetchError("blocked non-public address", "BLOCKED_HOST")


async def get_image(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_bytes: int = 30 * 1024 * 1024,
) -> tuple[bytes, str, str]:
    """Download one image, validating scheme, host and payload.

    Returns (bytes, extension, content_type).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchError("only http(s) image URLs are supported", "BAD_URL")

    await ensure_public_host(parsed.hostname)

    try:
        async with client.stream(
            "GET", url, headers=headers or {}, follow_redirects=True, timeout=30.0
        ) as response:
            if response.status_code >= 400:
                raise FetchError(f"image fetch failed: HTTP {response.status_code}", "IMAGE_HTTP")
            final_host = response.url.host
            if final_host and final_host != parsed.hostname:
                await ensure_public_host(final_host)
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            buffer = bytearray()
            async for chunk in response.aiter_bytes():
                buffer.extend(chunk)
                if len(buffer) > max_bytes:
                    raise FetchError("image exceeds size limit", "IMAGE_TOO_LARGE")
    except httpx.HTTPError as exc:
        raise FetchError(f"image fetch failed: {exc}", "IMAGE_NETWORK") from exc

    data = bytes(buffer)
    ext = sniff_extension(data)
    if ext is None:
        raise FetchError("response is not a supported image", "NOT_AN_IMAGE")
    if content_type and not content_type.startswith("image/") and content_type != "application/octet-stream":
        raise FetchError("response is not an image", "NOT_AN_IMAGE")
    return data, ext, content_type or f"image/{'jpeg' if ext == 'jpg' else ext}"
