from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from app.services import cbz


async def _demo_manga(client: httpx.AsyncClient) -> dict:
    search = await client.get("/api/search", params={"q": "star"})
    payload = search.json()
    item = payload["sources"][0]["items"][0]
    detail = await client.get(f"/api/sources/demo/manga/{item['key']}")
    assert detail.status_code == 200
    return detail.json()


async def _wait_jobs(client: httpx.AsyncClient, limit_s: float = 60.0) -> list[dict]:
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        payload = (await client.get("/api/downloads")).json()
        jobs = payload["jobs"]
        if jobs and all(job["status"] in ("done", "partial", "error", "canceled") for job in jobs):
            return jobs
        await asyncio.sleep(0.15)
    raise AssertionError(f"jobs did not finish: {jobs}")


async def test_health_and_sources(client: httpx.AsyncClient) -> None:
    health = await client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"

    sources = (await client.get("/api/sources")).json()["sources"]
    ids = {source["id"] for source in sources}
    assert "demo" in ids
    demo = next(source for source in sources if source["id"] == "demo")
    assert demo["enabled"] is True


async def test_search_groups_by_source(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/search", params={"q": "star"})
    payload = response.json()
    assert payload["query"] == "star"
    assert len(payload["sources"]) == 1
    outcome = payload["sources"][0]
    assert outcome["status"] == "ok"
    assert outcome["items"][0]["title"] == "Starfall Chronicles"


async def test_detail_download_library_and_reader(client: httpx.AsyncClient, app) -> None:
    detail = await _demo_manga(client)
    assert detail["title"] == "Starfall Chronicles"
    assert len(detail["chapters"]) == 3

    chapter = detail["chapters"][0]
    response = await client.post("/api/downloads", json={"chapter_ids": [chapter["id"]]})
    assert response.status_code == 200
    jobs = await _wait_jobs(client)
    assert jobs[0]["status"] == "done"
    assert jobs[0]["pages_done"] == jobs[0]["pages_total"] == 6

    settings = app.state.settings
    downloads = list(settings.library_dir.rglob("*.cbz"))
    assert len(downloads) == 1
    assert cbz.page_count(downloads[0]) == 6

    library = (await client.get("/api/library")).json()
    assert library["total"] == 1
    series = library["series"][0]
    assert series["title"] == "Starfall Chronicles"
    assert series["chapter_count"] == 1

    detail_payload = (await client.get(f"/api/library/{series['id']}")).json()
    assert detail_payload["chapters"][0]["page_count"] == 6

    cover = await client.get(f"/api/library/{series['id']}/cover")
    assert cover.status_code == 200
    assert cover.headers["content-type"] == "image/jpeg"

    manifest = (await client.get("/api/read/library", params={"series": series["id"], "chapter": 0})).json()
    assert manifest["total"] == 6
    page = await client.get(manifest["pages"][2]["url"])
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("image/")

    online = (
        await client.get(
            "/api/read/online", params={"manga_id": detail["id"], "chapter_id": chapter["id"]}
        )
    ).json()
    assert online["total"] == 6
    assert online["pages"][0]["url"].startswith("/api/demo/page")
    assert online["next"]["id"] == detail["chapters"][1]["id"]

    saved = await client.post(
        "/api/progress",
        json={
            "kind": "online",
            "item_ref": online["item_ref"],
            "chapter_ref": str(chapter["id"]),
            "page": 3,
            "page_total": 6,
        },
    )
    assert saved.status_code == 200
    progress = (await client.get("/api/progress", params={"kind": "online", "item_ref": online["item_ref"]})).json()
    assert progress["page"] == 3

    home = (await client.get("/api/home")).json()
    assert any(item["title"] == "Starfall Chronicles" for item in home["continue"])


async def test_download_all_and_scan(client: httpx.AsyncClient) -> None:
    detail = await _demo_manga(client)
    response = await client.post("/api/downloads", json={"manga_id": detail["id"], "all": True})
    assert response.status_code == 200
    assert response.json()["count"] == 3
    jobs = await _wait_jobs(client)
    assert all(job["status"] == "done" for job in jobs)

    scan = await client.post("/api/library/scan")
    assert scan.status_code == 200
    assert scan.json()["items"] == 3


async def test_delete_library_requires_confirmation(client: httpx.AsyncClient) -> None:
    detail = await _demo_manga(client)
    await client.post("/api/downloads", json={"manga_id": detail["id"], "all": True})
    await _wait_jobs(client)
    series = (await client.get("/api/library")).json()["series"][0]

    refused = await client.delete(f"/api/library/{series['id']}")
    assert refused.status_code == 400

    deleted = await client.delete(f"/api/library/{series['id']}", params={"confirm": "true"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted_chapters"] == 3
    assert (await client.get("/api/library")).json()["total"] == 0


async def test_image_proxy_rejects_bad_signature(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/img",
        params={"u": "https://example.org/a.jpg", "s": "demo", "e": 9999999999, "sig": "deadbeef"},
    )
    assert response.status_code == 403


async def test_source_probe_requires_network(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/sources/probe", json={"url": "not a url"})
    assert response.status_code in (400, 502)


async def test_unknown_endpoint_returns_json_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("path", ["/", "/library"])
async def test_spa_fallback(client: httpx.AsyncClient, path: str) -> None:
    from app.main import frontend_dist

    response = await client.get(path)
    if (frontend_dist() / "index.html").exists():
        assert response.status_code == 200
        assert 'id="root"' in response.text
        assert "window.__COMICPRO__" in response.text
    else:
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "NO_FRONTEND"
