from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy import select

from ..db import Database
from ..models import LibraryItem
from . import cbz as cbz_service

_LEADING_INDEX = re.compile(r"^\s*\d{2,5}\s*[-–_.]?\s*")


def scan_files(root: Path) -> list[dict]:
    records: list[dict] = []
    if not root.exists():
        return records
    for path in sorted(root.rglob("*.cbz")):
        rel = path.relative_to(root)
        if ".parts" in rel.parts or ".trash" in rel.parts:
            continue
        metadata = cbz_service.read_metadata(path)
        try:
            stat = path.stat()
        except OSError:
            continue
        stem = path.stem
        chapter_title = str(metadata.get("Title") or _LEADING_INDEX.sub("", stem)).strip() or stem
        series_title = str(metadata.get("Series") or path.parent.name).strip() or path.parent.name
        try:
            pages = int(str(metadata.get("PageCount") or 0))
        except ValueError:
            pages = 0
        records.append(
            {
                "rel_path": rel.as_posix(),
                "series_dir": rel.parent.as_posix(),
                "series_title": series_title,
                "chapter_title": chapter_title,
                "page_count": pages or cbz_service.page_count(path),
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
                "name": path.name,
            }
        )
    counters: dict[str, int] = {}
    for record in sorted(records, key=lambda item: (item["series_dir"], item["name"])):
        index = counters.get(record["series_dir"], 0)
        record["chapter_index"] = index
        counters[record["series_dir"]] = index + 1
    return records


async def sync_library(database: Database, root: Path) -> dict:
    records = scan_files(root)
    seen = {record["rel_path"] for record in records}
    inserted = updated = removed = 0
    async with database.session() as session:
        existing = (await session.execute(select(LibraryItem))).scalars().all()
        by_path = {item.rel_path: item for item in existing}
        for record in records:
            item = by_path.get(record["rel_path"])
            if item is None:
                session.add(
                    LibraryItem(
                        rel_path=record["rel_path"],
                        series_dir=record["series_dir"],
                        series_title=record["series_title"],
                        chapter_title=record["chapter_title"],
                        chapter_index=record["chapter_index"],
                        page_count=record["page_count"],
                        size_bytes=record["size_bytes"],
                        mtime=record["mtime"],
                    )
                )
                inserted += 1
            else:
                item.series_dir = record["series_dir"]
                item.series_title = record["series_title"]
                item.chapter_title = record["chapter_title"]
                item.chapter_index = record["chapter_index"]
                item.page_count = record["page_count"]
                item.size_bytes = record["size_bytes"]
                item.mtime = record["mtime"]
                updated += 1
        for item in existing:
            if item.rel_path not in seen:
                await session.delete(item)
                removed += 1
        await session.commit()
    return {"items": len(records), "inserted": inserted, "updated": updated, "removed": removed}


def series_cover_path(covers_dir: Path, series_dir: str) -> Path:
    digest = hashlib.sha1(series_dir.encode("utf-8")).hexdigest()[:16]
    return covers_dir / f"{digest}.jpg"


def ensure_series_cover(root: Path, covers_dir: Path, series_dir: str, rel_path: str) -> Path | None:
    target = series_cover_path(covers_dir, series_dir)
    source = root / rel_path
    if target.exists() and source.exists():
        try:
            if target.stat().st_mtime >= source.stat().st_mtime:
                return target
        except OSError:
            pass
    if not source.exists():
        return target if target.exists() else None
    return target if cbz_service.cover_from_cbz(source, target) else None
