from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response

from ..schemas import LoginIn, PasswordIn
from ..services.auth import COOKIE_NAME

router = APIRouter(prefix="/auth", tags=["auth"])

_ATTEMPTS: dict[str, list[float]] = {}
WINDOW = 60.0
LIMIT = 5


def _client_ip(request: Request) -> str:
    if request.app.state.settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    attempts = [stamp for stamp in _ATTEMPTS.get(ip, []) if now - stamp < WINDOW]
    _ATTEMPTS[ip] = attempts
    if len(attempts) >= LIMIT:
        return True
    attempts.append(now)
    return False


@router.get("/state")
async def state(request: Request) -> dict:
    auth = request.app.state.auth
    return {
        "required": await auth.enabled(),
        "authenticated": await auth.authenticated(request),
        "env_managed": bool(request.app.state.settings.auth_password),
    }


@router.post("/login")
async def login(payload: LoginIn, request: Request, response: Response) -> dict:
    auth = request.app.state.auth
    if not await auth.enabled():
        return {"ok": True, "required": False}
    if _rate_limited(_client_ip(request)):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "too many attempts"})
    if not await auth.check_password(payload.password):
        raise HTTPException(status_code=401, detail={"code": "BAD_PASSWORD", "message": "wrong password"})
    response.set_cookie(value=await auth.issue_cookie(), **auth.cookie_kwargs())
    return {"ok": True, "required": True}


@router.post("/logout")
async def logout(response: Response, request: Request) -> dict:
    kwargs = request.app.state.auth.cookie_kwargs()
    response.delete_cookie(COOKIE_NAME, path=kwargs["path"])
    return {"ok": True}


@router.post("/password")
async def change_password(payload: PasswordIn, request: Request, response: Response) -> dict:
    auth = request.app.state.auth
    if not await auth.authenticated(request):
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "login required"})
    if request.app.state.settings.auth_password:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ENV_LOCKED",
                "message": "AUTH_PASSWORD is set in the environment; change it there",
            },
        )
    if await auth.enabled() and not await auth.check_password(payload.current):
        raise HTTPException(status_code=400, detail={"code": "BAD_PASSWORD", "message": "current password is wrong"})
    await auth.set_password(payload.new)
    request.app.state.auth_required = True
    response.set_cookie(value=await auth.issue_cookie(), **auth.cookie_kwargs())
    return {"ok": True}
