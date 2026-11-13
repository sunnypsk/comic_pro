from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class Base(DeclarativeBase):
    pass


class Manga(Base):
    __tablename__ = "manga"
    __table_args__ = (UniqueConstraint("source_id", "source_key", name="uq_manga_source_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    source_key: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512))
    alt_titles: Mapped[str] = mapped_column(Text, default="")
    cover_url: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")
    author: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(64), default="")
    follow: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_download: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Chapter(Base):
    __tablename__ = "chapter"
    __table_args__ = (UniqueConstraint("manga_id", "source_key", name="uq_chapter_manga_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manga_id: Mapped[int] = mapped_column(ForeignKey("manga.id", ondelete="CASCADE"), index=True)
    source_key: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512))
    number: Mapped[float | None] = mapped_column(Float, nullable=True)
    url: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    downloaded: Mapped[bool] = mapped_column(Boolean, default=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0)


class DownloadJob(Base):
    __tablename__ = "download_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manga_id: Mapped[int] = mapped_column(ForeignKey("manga.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapter.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    pages_total: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    target_path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class LibraryItem(Base):
    """One CBZ chapter file on disk. Series are grouped by `series_dir`."""

    __tablename__ = "library_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rel_path: Mapped[str] = mapped_column(String(1024), unique=True)
    series_dir: Mapped[str] = mapped_column(String(1024), index=True)
    series_title: Mapped[str] = mapped_column(String(512))
    chapter_title: Mapped[str] = mapped_column(String(512))
    chapter_index: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    mtime: Mapped[float] = mapped_column(Float, default=0.0)
    added_at: Mapped[datetime] = mapped_column(default=utcnow)


class ReadingProgress(Base):
    __tablename__ = "reading_progress"
    __table_args__ = (UniqueConstraint("kind", "item_ref", name="uq_progress_kind_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # online | library
    item_ref: Mapped[str] = mapped_column(String(1024))
    chapter_ref: Mapped[str] = mapped_column(String(1024), default="")
    page: Mapped[int] = mapped_column(Integer, default=1)
    page_total: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, server_default=func.now()
    )
