from __future__ import annotations

import httpx
import pytest
from app.api import auth as auth_api
from app.config import Settings
from app.main import create_app


async def _app_with(tmp_path, **kwargs):
    settings = Settings(
        data_dir=tmp_path / "data",
        demo_source=True,
        secret_key="auth-test-secret",
        check_interval_min=0,
        source_min_interval=0.0,
        log_level="WARNING",
        **kwargs,
    )
    return create_app(settings)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_login_flow_and_rate_limit(tmp_path) -> None:
    auth_api._ATTEMPTS.clear()
    app = await _app_with(tmp_path, auth_password="hunter2")
    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            state = (await client.get("/api/auth/state")).json()
            assert state == {"required": True, "authenticated": False, "env_managed": True}

            assert (await client.get("/api/search", params={"q": "star"})).status_code == 401

            bad = await client.post("/api/auth/login", json={"password": "nope"})
            assert bad.status_code == 401

            good = await client.post("/api/auth/login", json={"password": "hunter2"})
            assert good.status_code == 200
            assert (await client.get("/api/search", params={"q": "star"})).status_code == 200

            await client.post("/api/auth/logout")
            assert (await client.get("/api/search", params={"q": "star"})).status_code == 401

    auth_api._ATTEMPTS.clear()
    app = await _app_with(tmp_path / "rate", auth_password="hunter2")
    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            for _ in range(5):
                await client.post("/api/auth/login", json={"password": "wrong"})
            limited = await client.post("/api/auth/login", json={"password": "hunter2"})
            assert limited.status_code == 429
    auth_api._ATTEMPTS.clear()


async def test_set_password_from_ui(tmp_path) -> None:
    auth_api._ATTEMPTS.clear()
    app = await _app_with(tmp_path)
    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            assert (await client.get("/api/auth/state")).json()["required"] is False
            assert (await client.get("/api/search", params={"q": "star"})).status_code == 200

            changed = await client.post("/api/auth/password", json={"current": "", "new": "letmein"})
            assert changed.status_code == 200
            assert (await client.get("/api/auth/state")).json()["required"] is True

            anonymous = _client(app)
            async with anonymous:
                assert (await anonymous.get("/api/search", params={"q": "star"})).status_code == 401
                login = await anonymous.post("/api/auth/login", json={"password": "letmein"})
                assert login.status_code == 200
                assert (await anonymous.get("/api/search", params={"q": "star"})).status_code == 200


async def test_api_token_header(tmp_path) -> None:
    app = await _app_with(tmp_path, auth_password="hunter2", api_token="token-123")
    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            anonymous = await client.get("/api/search", params={"q": "star"})
            assert anonymous.status_code == 401
            allowed = await client.get(
                "/api/search", params={"q": "star"}, headers={"X-Api-Token": "token-123"}
            )
            assert allowed.status_code == 200
            wrong = await client.get("/api/search", params={"q": "star"}, headers={"X-Api-Token": "nope"})
            assert wrong.status_code == 401


async def test_password_change_blocked_when_env_managed(tmp_path) -> None:
    auth_api._ATTEMPTS.clear()
    app = await _app_with(tmp_path, auth_password="hunter2")
    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            await client.post("/api/auth/login", json={"password": "hunter2"})
            response = await client.post("/api/auth/password", json={"current": "hunter2", "new": "other"})
            assert response.status_code == 400
            assert response.json()["detail"]["code"] == "ENV_LOCKED"


@pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Real-IP"])
async def test_trusted_proxy_header(tmp_path, header: str) -> None:
    app = await _app_with(tmp_path, auth_password="hunter2")
    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            response = await client.get("/api/auth/state", headers={header: "203.0.113.5"})
            assert response.status_code == 200
