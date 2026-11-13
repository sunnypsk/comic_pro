from __future__ import annotations

import io
from pathlib import Path

import pytest
from app.services import cbz
from app.services.fetcher import FetchError, ensure_public_host, sniff_extension
from app.services.page_cache import PageCache
from app.services.slugs import (
    b64d,
    b64e,
    ensure_within,
    password_hash,
    password_verify,
    sign,
    slugify,
    verify_signature,
)
from fastapi import HTTPException
from PIL import Image


def _png(tmp_path: Path, name: str, color: tuple[int, int, int]) -> Path:
    path = tmp_path / name
    Image.new("RGB", (32, 48), color).save(path, format="PNG")
    return path


def test_slugify_removes_illegal_characters() -> None:
    assert slugify('a/b\\c:d*e?"f"<g>h|i') == "a b c d e f g h i"
    assert slugify("   ...   ") == "item"
    assert slugify("x" * 200, max_len=10) == "x" * 10
    assert slugify("第 1 话：开始") == "第 1 话：开始"


def test_b64_roundtrip_unicode() -> None:
    value = "https://例子.org/manga/漫画/?a=1&b=2"
    assert b64d(b64e(value)) == value


def test_ensure_within_blocks_escape(tmp_path: Path) -> None:
    base = tmp_path / "library"
    base.mkdir()
    inside = base / "a" / "b.cbz"
    inside.parent.mkdir()
    inside.write_bytes(b"x")
    assert ensure_within(base, inside) == inside.resolve()
    with pytest.raises(HTTPException):
        ensure_within(base, base / ".." / "evil.cbz")


def test_password_hash_and_verify() -> None:
    stored = password_hash("s3cret")
    assert stored.startswith("scrypt$")
    assert password_verify("s3cret", stored)
    assert not password_verify("wrong", stored)
    assert not password_verify("s3cret", "garbage")


def test_hmac_signature() -> None:
    signature = sign("key", "payload")
    assert verify_signature("key", "payload", signature)
    assert not verify_signature("key", "payload2", signature)


def test_cbz_roundtrip_and_cover(tmp_path: Path) -> None:
    pages = [_png(tmp_path, f"{index}.png", (index * 40, 80, 120)) for index in range(3)]
    target = tmp_path / "out" / "chapter.cbz"
    comic_info = cbz.comic_info_xml(
        series="Blue Sky", number="1", title="Beginnings", page_count=3, web="https://example.org/x"
    )
    cbz.write_cbz(target, pages, comic_info=comic_info, metadata={"source_id": "demo"})
    assert target.exists()
    assert cbz.page_count(target) == 3
    data, media = cbz.extract_page(target, 2)
    assert media == "image/png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert cbz.extract_page(target, 9) is None
    cover = tmp_path / "covers" / "c.jpg"
    assert cbz.cover_from_cbz(target, cover)
    assert cover.exists() and cover.stat().st_size > 0
    metadata = cbz.read_metadata(target)
    assert metadata["Series"] == "Blue Sky"
    assert metadata["PageCount"] == 3


def test_comic_info_escapes_xml() -> None:
    xml = cbz.comic_info_xml(series="A & B <C>", page_count=1)
    assert "A &amp; B &lt;C&gt;" in xml


def test_page_cache_prune(tmp_path: Path) -> None:
    cache = PageCache(tmp_path / "pages", max_bytes=3000)
    for index in range(6):
        cache.put(f"https://example.org/{index}.jpg", b"x" * 1000, "jpg")
    assert cache.size() > 3000
    cache.prune()
    assert cache.size() <= 3000
    remaining = [index for index in range(6) if cache.find(f"https://example.org/{index}.jpg")]
    assert 2 <= len(remaining) <= 3


def test_sniff_extension() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buffer, format="JPEG")
    assert sniff_extension(buffer.getvalue()) == "jpg"
    assert sniff_extension(b"not an image") is None


async def test_ensure_public_host_blocks_loopback() -> None:
    with pytest.raises(FetchError):
        await ensure_public_host("localhost")


def test_placeholder_pages_are_deterministic() -> None:
    from app.services.placeholder import render_cover, render_page

    assert render_page("Starfall", "Chapter 1", 1, 6) == render_page("Starfall", "Chapter 1", 1, 6)
    assert render_cover("Starfall", "A. Writer") == render_cover("Starfall", "A. Writer")
