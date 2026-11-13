from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Database
from .sources.registry import SourceRegistry


def database(request: Request) -> Database:
    return request.app.state.db


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def registry(request: Request) -> SourceRegistry:
    return request.app.state.registry


RegistryDep = Annotated[SourceRegistry, Depends(registry)]


async def require_auth(request: Request) -> None:
    auth = request.app.state.auth
    if not await auth.authenticated(request):
        raise HTTPException(
            status_code=401, detail={"code": "UNAUTHORIZED", "message": "authentication required"}
        )
