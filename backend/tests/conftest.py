from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        demo_source=True,
        log_level="WARNING",
        secret_key="test-secret-key",
        source_timeout=3.0,
        search_timeout=4.0,
        source_min_interval=0.0,
        check_interval_min=0,
        mangapill=False,
        weebcentral=False,
        dongman=False,
        nhentai=False,
    )


@pytest.fixture
async def app(settings: Settings):
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
