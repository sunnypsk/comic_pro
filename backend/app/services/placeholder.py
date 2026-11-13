from __future__ import annotations

import io
import textwrap
import zlib

from PIL import Image, ImageDraw, ImageFont

_PALETTE = [
    ((24, 32, 54), (86, 132, 214)),
    ((44, 24, 38), (214, 106, 132)),
    ((18, 40, 38), (86, 196, 158)),
    ((46, 36, 18), (214, 168, 86)),
    ((30, 26, 54), (150, 118, 220)),
    ((40, 32, 30), (206, 122, 94)),
]


def _palette_for(title: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    return _PALETTE[zlib.crc32(title.encode("utf-8")) % len(_PALETTE)]


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_page(
    series_title: str,
    chapter_title: str,
    page: int = 1,
    total: int = 1,
    size: tuple[int, int] = (840, 1200),
) -> bytes:
    """Deterministic placeholder page, used by the offline demo source."""
    background, accent = _palette_for(series_title)
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    width, height = size

    draw.rectangle([0, 0, width, 14], fill=accent)
    draw.rectangle([0, height - 90, width, height], fill=accent)
    draw.text((40, height - 66), f"ComicPro demo · page {page}/{total}", font=_font(24), fill=background)

    title_font = _font(48)
    body_font = _font(26)
    chapter_font = _font(30)

    y = 70
    for line in _wrap(draw, series_title, title_font, width - 120)[:2]:
        draw.text((60, y), line, font=title_font, fill=(255, 255, 255))
        y += 58
    y += 10
    for line in _wrap(draw, chapter_title, chapter_font, width - 120)[:2]:
        draw.text((60, y), line, font=chapter_font, fill=accent)
        y += 40

    panel_top = y + 40
    draw.rounded_rectangle([60, panel_top, width - 60, height - 150], radius=18, outline=accent, width=3)
    body = (
        "This page is generated locally by ComicPro so the whole pipeline (search, "
        "reading, CBZ download and the library) can be exercised without any external site. "
        f"Chapter page {page} of {total}."
    )
    y = panel_top + 40
    for line in _wrap(draw, body, body_font, width - 160):
        draw.text((90, y), line, font=body_font, fill=(232, 236, 248))
        y += 36

    draw.text((60, height // 2), str(page), font=_font(220), fill=accent)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=84)
    return buffer.getvalue()


def render_cover(series_title: str, author: str = "") -> bytes:
    background, accent = _palette_for(series_title)
    image = Image.new("RGB", (480, 720), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 480, 10], fill=accent)
    y = 80
    for line in textwrap.wrap(series_title, width=14)[:4]:
        draw.text((36, y), line, font=_font(46), fill=(255, 255, 255))
        y += 56
    draw.text((36, 600), author or "ComicPro demo", font=_font(22), fill=accent)
    draw.text((36, 660), "DEMO", font=_font(28), fill=accent)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=86)
    return buffer.getvalue()
