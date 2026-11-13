from __future__ import annotations

import pytest
from app.config import Settings
from app.main import create_app
from app.models import Chapter, DownloadJob, Manga


async def test_download_recovery_requeues_running_jobs(app) -> None:
    downloader = app.state.downloader
    await downloader.stop()

    async with app.state.db.session() as session:
        manga = Manga(source_id="demo", source_key="demo://starfall", title="Starfall Chronicles")
        session.add(manga)
        await session.flush()
        chapter = Chapter(
            manga_id=manga.id,
            source_key="demo://starfall/0",
            title="Chapter 1",
            url="demo://starfall/0",
        )
        session.add(chapter)
        await session.flush()
        job = DownloadJob(manga_id=manga.id, chapter_id=chapter.id, status="running", pages_done=2)
        session.add(job)
        await session.commit()
        job_id = job.id

    assert await downloader.recover() == 1
    async with app.state.db.session() as session:
        stored = await session.get(DownloadJob, job_id)
        assert stored is not None
        assert stored.status == "queued"
        assert stored.pages_done == 2


async def test_source_config_crud(client, settings) -> None:
    yaml_text = (
        "id: test-site\n"
        "name: Test Site\n"
        "engine: generic\n"
        "base_url: https://example.org\n"
        "enabled: true\n"
        "search:\n"
        "  url: /?s={q}\n"
        "  item: article\n"
        "  link: a@href\n"
    )
    saved = await client.put("/api/sources/test-site/config", json={"yaml": yaml_text})
    assert saved.status_code == 200, saved.text

    listed = (await client.get("/api/sources")).json()["sources"]
    source = next((item for item in listed if item["id"] == "test-site"), None)
    assert source is not None
    assert source["enabled"] is True
    assert (settings.sources_dir / "test-site.yaml").exists()

    config = (await client.get("/api/sources/test-site/config")).json()
    assert "base_url: https://example.org" in config["yaml"]

    patched = await client.patch("/api/sources/test-site", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False

    reloaded = await client.post("/api/sources/reload")
    assert reloaded.status_code == 200
    assert "test-site.yaml" not in reloaded.json()["errors"]

    deleted = await client.delete("/api/sources/test-site/config")
    assert deleted.status_code == 200
    listed = (await client.get("/api/sources")).json()["sources"]
    assert all(item["id"] != "test-site" for item in listed)


async def test_invalid_source_yaml_rejected(client) -> None:
    response = await client.put(
        "/api/sources/broken/config",
        json={"yaml": "id: broken\nname: Broken\nengine: madara\n"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "BAD_CONFIG"


async def test_base_path_injected_into_spa(tmp_path) -> None:
    from app.main import frontend_dist

    if not (frontend_dist() / "index.html").exists():
        pytest.skip("frontend bundle not built")

    settings = Settings(
        data_dir=tmp_path / "data",
        demo_source=True,
        secret_key="base-path-secret",
        base_path="/comic",
        check_interval_min=0,
        log_level="WARNING",
    )
    app = create_app(settings)
    import httpx

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/library")
    assert response.status_code == 200
    assert '<base href="/comic/" />' in response.text
    assert '"basePath": "/comic"' in response.text
