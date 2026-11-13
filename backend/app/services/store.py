from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Setting


async def get_json(session: AsyncSession, key: str, default: Any) -> Any:
    row = await session.get(Setting, key)
    if row is None or not row.value:
        return default
    try:
        return json.loads(row.value)
    except (TypeError, ValueError):
        return default


async def set_json(session: AsyncSession, key: str, value: Any) -> None:
    row = await session.get(Setting, key)
    payload = json.dumps(value, ensure_ascii=False)
    if row is None:
        session.add(Setting(key=key, value=payload))
    else:
        row.value = payload


async def all_settings(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(select(Setting))).scalars().all()
    result: dict[str, Any] = {}
    for row in rows:
        try:
            result[row.key] = json.loads(row.value)
        except (TypeError, ValueError):
            result[row.key] = row.value
    return result
