"""Offline smoke test, piped to Python inside a disposable Docker container."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


def api(path: str, payload: dict | None = None):
    request = urllib.request.Request(
        "http://127.0.0.1:8080" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def wait_healthy() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            health = api("/api/health")
            if health["status"] == "ok" and health["db"] == "ok":
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    raise RuntimeError("container did not become healthy")


def check_library() -> None:
    assert api("/api/library")["total"] >= 1, "downloaded library must survive a restart"
    files = list(Path("/data/library").rglob("*.cbz"))
    assert files, "no CBZ written to the data volume"
    with zipfile.ZipFile(files[0]) as archive:
        assert archive.testzip() is None
        assert "ComicInfo.xml" in archive.namelist()


def main() -> None:
    wait_healthy()
    if "--persisted" in sys.argv:
        check_library()
        print("Restart persistence: PASS")
        return

    for name in (".git", ".env", ".aws", ".ssh", "data"):
        assert not (Path("/app") / name).exists(), f"unexpected build input: {name}"
    with urllib.request.urlopen("http://127.0.0.1:8080/", timeout=5) as response:
        html = response.read().decode()
        assert 'id="root"' in html and "window.__COMICPRO__" in html

    source_ids = {source["id"] for source in api("/api/sources")["sources"]}
    assert {"demo", "mangapill", "weebcentral", "dongman", "nhentai"} <= source_ids
    payload = api("/api/search?q=star&sources=demo")
    assert payload["aliases"] == []
    outcome = payload["sources"][0]
    assert outcome["status"] == "ok" and outcome["id"] == "demo"
    detail = api(f"/api/sources/demo/manga/{outcome['items'][0]['key']}")
    chapter = detail["chapters"][0]
    manifest = api(f"/api/read/online?manga_id={detail['id']}&chapter_id={chapter['id']}")
    assert manifest["total"] > 0 and manifest["pages"]
    result = api("/api/downloads", {"chapter_ids": [chapter["id"]]})
    assert result["count"] == 1
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        jobs = api("/api/downloads")["jobs"]
        if jobs and all(job["status"] == "done" for job in jobs):
            break
        assert all(job["status"] not in ("error", "partial", "canceled") for job in jobs), jobs
        time.sleep(0.25)
    else:
        raise RuntimeError("offline demo download did not complete")
    api("/api/library/scan", {})
    check_library()
    print("Frontend, sources, reader, download and library: PASS")


if __name__ == "__main__":
    main()
