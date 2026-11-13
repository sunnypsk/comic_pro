from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
import yaml
from selectolax.parser import HTMLParser

from .yaml_source import ENGINE_DEFAULTS, deep_merge

MARKERS = {
    "wp-manga": "madara",
    "manga-page": "madara",
    "reading-content": "madara",
    "page-menu": "mangastream",
    "readerarea": "mangastream",
    "chapter-list": "mangastream",
    "wp-manga-chapter": "madara",
}


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "source"


async def probe_site(client: httpx.AsyncClient, url: str, user_agent: str) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError("invalid URL")

    response = await client.get(url, headers={"User-Agent": user_agent}, timeout=15.0, follow_redirects=True)
    if response.status_code >= 400:
        raise ValueError(f"site returned HTTP {response.status_code}")
    html = response.text
    lowered = html.lower()

    scores: dict[str, int] = {}
    found: list[str] = []
    for marker, engine in MARKERS.items():
        if marker in lowered:
            scores[engine] = scores.get(engine, 0) + 1
            found.append(marker)
    engine = max(scores, key=scores.get) if scores else "generic"
    confidence = min(0.9, 0.35 + 0.15 * scores.get(engine, 0)) if scores else 0.25

    tree = HTMLParser(html)
    title_node = tree.css_first("title")
    site_name = title_node.text(strip=True) if title_node else parsed.netloc
    origin = f"{parsed.scheme}://{parsed.netloc}"
    source_id = _slug(parsed.netloc.replace("www.", ""))

    draft = deep_merge(
        ENGINE_DEFAULTS[engine],
        {
            "id": source_id,
            "name": site_name[:80] or source_id,
            "base_url": origin,
            "engine": engine,
            "lang": "en",
            "nsfw": False,
            "enabled": False,
            "headers": {"User-Agent": user_agent},
        },
    )
    draft_yaml = yaml.safe_dump(draft, allow_unicode=True, sort_keys=False)
    return {
        "url": url,
        "final_url": str(response.url),
        "base_url": origin,
        "id": source_id,
        "site_name": site_name,
        "engine": engine,
        "confidence": round(confidence, 2),
        "markers": found,
        "yaml": draft_yaml,
    }
