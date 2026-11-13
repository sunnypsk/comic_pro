from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}


def comic_info_xml(
    *,
    series: str,
    number: str = "",
    title: str = "",
    summary: str = "",
    writer: str = "",
    publisher: str = "",
    page_count: int = 0,
    web: str = "",
    language: str = "en",
    tags: list[str] | None = None,
    notes: str = "",
) -> str:
    fields = {
        "Title": title,
        "Series": series,
        "Number": number,
        "Summary": summary,
        "Writer": writer,
        "Publisher": publisher,
        "Genre": ", ".join(tags or []),
        "PageCount": str(page_count),
        "LanguageISO": language,
        "Web": web,
        "Manga": "YesAndRightToLeft",
        "Notes": notes,
    }
    body = "\n".join(
        f"  <{key}>{escape(str(value))}</{key}>" for key, value in fields.items() if value not in ("", None)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n'
        f"{body}\n</ComicInfo>\n"
    )


def write_cbz(
    target: Path,
    pages: list[Path],
    *,
    comic_info: str | None = None,
    metadata: dict | None = None,
    attachments: dict[str, bytes] | None = None,
) -> Path:
    """Write a CBZ atomically. Page order is the order of `pages`."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    if temp.exists():
        temp.unlink()
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for index, page in enumerate(pages, start=1):
            suffix = page.suffix.lower() if page.suffix.lower() in IMAGE_EXTS else ".jpg"
            archive.write(page, arcname=f"{index:04d}{suffix}")
        if comic_info:
            archive.writestr("ComicInfo.xml", comic_info)
        if metadata:
            archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        for name, payload in (attachments or {}).items():
            archive.writestr(name, payload)
    os.replace(temp, target)
    return target


def image_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = [
        info
        for info in archive.infolist()
        if not info.is_dir()
        and Path(info.filename).suffix.lower() in IMAGE_EXTS
        and not info.filename.startswith("__MACOSX")
    ]
    return sorted(entries, key=lambda info: info.filename)


def page_count(path: Path) -> int:
    try:
        with zipfile.ZipFile(path) as archive:
            return len(image_entries(archive))
    except (zipfile.BadZipFile, OSError):
        return 0


def read_metadata(path: Path) -> dict:
    result: dict = {}
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "ComicInfo.xml" in names:
                try:
                    root = ElementTree.fromstring(archive.read("ComicInfo.xml"))
                    for child in root:
                        if child.text:
                            result[child.tag] = child.text.strip()
                except ElementTree.ParseError:
                    pass
            if "metadata.json" in names:
                try:
                    result.update(json.loads(archive.read("metadata.json")))
                except ValueError:
                    pass
            if "PageCount" in result:
                try:
                    result["PageCount"] = int(result["PageCount"])
                except (TypeError, ValueError):
                    pass
            result.setdefault("PageCount", len(image_entries(archive)))
    except (zipfile.BadZipFile, OSError):
        return result
    return result


def extract_page(path: Path, index: int) -> tuple[bytes, str] | None:
    """Return (bytes, media type) for the 1-based page index."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = image_entries(archive)
            if not entries or index < 1 or index > len(entries):
                return None
            entry = entries[index - 1]
            suffix = Path(entry.filename).suffix.lower()
            media = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".gif": "image/gif",
                ".bmp": "image/bmp",
                ".avif": "image/avif",
            }.get(suffix, "application/octet-stream")
            return archive.read(entry), media
    except (zipfile.BadZipFile, OSError):
        return None


def first_image(path: Path) -> bytes | None:
    data = extract_page(path, 1)
    return data[0] if data else None


def cover_from_cbz(path: Path, target: Path, width: int = 320) -> bool:
    from PIL import Image

    raw = first_image(path)
    if not raw:
        return False
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("RGB")
            image.thumbnail((width, width * 3))
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix(".tmp.jpg")
            image.save(temp, format="JPEG", quality=82)
            os.replace(temp, target)
        return True
    except Exception:  # noqa: BLE001 - broken source image should not break scanning
        return False
