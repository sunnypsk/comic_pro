from __future__ import annotations

import io
import time

import httpx
from app.services import fetcher
from app.services.slugs import image_signature
from PIL import Image


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (24, 32), (90, 140, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_image_proxy_fetches_and_caches(client, app, monkeypatch) -> None:
    async def allow(_host: str) -> None:
        return None

    monkeypatch.setattr(fetcher, "ensure_public_host", allow)
    calls = {"count": 0}
    payload = _png()

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, content=payload, headers={"content-type": "image/png"})

    app.state.image_proxy.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    url = "https://images.example.org/page-1.png"
    signed = app.state.image_proxy.signed_url("demo", url)

    first = await client.get(signed)
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert first.content == payload
    assert calls["count"] == 1

    second = await client.get(signed)
    assert second.status_code == 200
    assert second.content == payload
    assert calls["count"] == 1  # served from the disk cache


async def test_image_proxy_rejects_expired_signature(client, app) -> None:
    url = "https://images.example.org/page-2.png"
    expires = int(time.time()) - 10
    signature = image_signature(app.state.secret, "demo", url, expires)
    response = await client.get(
        "/api/img", params={"u": url, "s": "demo", "e": expires, "sig": signature}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "BAD_SIGNATURE"


async def test_image_proxy_rejects_non_image(client, app, monkeypatch) -> None:
    async def allow(_host: str) -> None:
        return None

    monkeypatch.setattr(fetcher, "ensure_public_host", allow)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not an image</html>", headers={"content-type": "text/html"})

    app.state.image_proxy.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    signed = app.state.image_proxy.signed_url("demo", "https://images.example.org/fake.jpg")
    response = await client.get(signed)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "NOT_AN_IMAGE"
