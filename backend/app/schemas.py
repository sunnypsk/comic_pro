from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    password: str = ""


class PasswordIn(BaseModel):
    current: str = ""
    new: str = Field(min_length=4, max_length=200)


class SourcePatch(BaseModel):
    enabled: bool


class SourceConfigIn(BaseModel):
    yaml: str


class ProbeIn(BaseModel):
    url: str


class FollowIn(BaseModel):
    follow: bool | None = None
    auto_download: bool | None = None


class DownloadIn(BaseModel):
    chapter_ids: list[int] = Field(default_factory=list)
    manga_id: int | None = None
    all: bool = False


class ProgressIn(BaseModel):
    kind: Literal["online", "library"]
    item_ref: str
    chapter_ref: str = ""
    page: int = 1
    page_total: int = 0


class SettingsIn(BaseModel):
    cache_max_gb: float | None = Field(default=None, ge=0, le=1024)
    check_interval_min: int | None = Field(default=None, ge=0, le=10080)
