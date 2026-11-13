from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path


class PageCache:
    """Disk cache for proxied page images with a size cap and mtime-based LRU."""

    def __init__(self, root: Path, max_bytes: int) -> None:
        self.root = root
        self.max_bytes = max(0, max_bytes)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def digest(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def path_for(self, url: str, ext: str = "jpg") -> Path:
        digest = self.digest(url)
        return self.root / digest[:2] / digest[2:4] / f"{digest}.{ext}"

    def find(self, url: str) -> Path | None:
        digest = self.digest(url)
        directory = self.root / digest[:2] / digest[2:4]
        if not directory.exists():
            return None
        for candidate in directory.glob(f"{digest}.*"):
            return candidate
        return None

    def get(self, url: str) -> Path | None:
        path = self.find(url)
        if path is None:
            return None
        try:
            os.utime(path, None)
        except OSError:
            pass
        return path

    def put(self, url: str, data: bytes, ext: str) -> Path:
        path = self.path_for(url, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(data)
        os.replace(temp, path)
        return path

    def size(self) -> int:
        total = 0
        for path in self.root.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
        return total

    def prune(self) -> int:
        if self.max_bytes <= 0:
            return 0
        files: list[tuple[float, int, Path]] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append((stat.st_mtime, stat.st_size, path))
        total = sum(item[1] for item in files)
        if total <= self.max_bytes:
            return 0
        removed = 0
        target = int(self.max_bytes * 0.9)
        for _mtime, size, path in sorted(files):
            if total <= target:
                break
            try:
                path.unlink()
                total -= size
                removed += 1
            except OSError:
                continue
        return removed

    async def prune_async(self) -> int:
        return await asyncio.to_thread(self.prune)

    async def cleanup_loop(self, interval: float = 600.0) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.prune_async()
            except Exception:  # noqa: BLE001 - background maintenance must not die
                continue
