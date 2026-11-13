from __future__ import annotations

import hashlib
import hmac

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import Settings
from ..db import Database
from .slugs import password_hash, password_verify
from .store import get_json, set_json

COOKIE_NAME = "comicpro_session"
PASSWORD_KEY = "auth_password_hash"


class AuthService:
    """Optional single-password auth with signed, HttpOnly session cookies."""

    def __init__(self, settings: Settings, database: Database, secret: str) -> None:
        self.settings = settings
        self.db = database
        self.serializer = URLSafeTimedSerializer(secret, salt="comicpro-auth")

    async def stored_hash(self) -> str:
        async with self.db.session() as session:
            value = await get_json(session, PASSWORD_KEY, "")
        return value if isinstance(value, str) else ""

    async def enabled(self) -> bool:
        return bool(self.settings.auth_password) or bool(await self.stored_hash())

    async def _effective_secret(self) -> str:
        return self.settings.auth_password or await self.stored_hash()

    async def fingerprint(self) -> str:
        return hashlib.sha256((await self._effective_secret()).encode("utf-8")).hexdigest()[:16]

    async def issue_cookie(self) -> str:
        return self.serializer.dumps({"v": 1, "h": await self.fingerprint()})

    async def verify_cookie(self, value: str) -> bool:
        if not value:
            return False
        try:
            payload = self.serializer.loads(value, max_age=self.settings.session_days * 86400)
        except (BadSignature, SignatureExpired):
            return False
        if not isinstance(payload, dict):
            return False
        return hmac.compare_digest(str(payload.get("h", "")), await self.fingerprint())

    async def check_password(self, password: str) -> bool:
        if not await self.enabled():
            return True
        if self.settings.auth_password:
            return hmac.compare_digest(password, self.settings.auth_password)
        return password_verify(password, await self.stored_hash())

    async def set_password(self, password: str) -> None:
        async with self.db.session() as session:
            await set_json(session, PASSWORD_KEY, password_hash(password))
            await session.commit()

    async def authenticated(self, request: Request) -> bool:
        if not await self.enabled():
            return True
        token = request.headers.get("x-api-token", "")
        if token and self.settings.api_token and hmac.compare_digest(token, self.settings.api_token):
            return True
        return await self.verify_cookie(request.cookies.get(COOKIE_NAME, ""))

    def cookie_kwargs(self) -> dict:
        root = self.settings.root_path() or "/"
        return {
            "key": COOKIE_NAME,
            "httponly": True,
            "samesite": "lax",
            "path": root,
            "max_age": self.settings.session_days * 86400,
            "secure": False,
        }
