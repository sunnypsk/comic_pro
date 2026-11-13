from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

_META = re.compile(r"^(?:meta|property|name):(.+)$")


def parse(html: str):
    from selectolax.parser import HTMLParser

    return HTMLParser(html or "")


def split_alternatives(spec: str) -> list[str]:
    """Split "a, b@href, c" on top-level commas, keeping parentheses/brackets intact."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in spec:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _select(node, css: str):
    if not css:
        return node
    try:
        return node.css_first(css)
    except Exception:  # noqa: BLE001 - malformed selector must not crash a source
        return None


def text_of(node) -> str:
    if node is None:
        return ""
    try:
        return (node.text(deep=True, strip=True) or "").strip()
    except TypeError:  # older/newer selectolax signatures
        return (node.text() or "").strip()


def html_of(node) -> str:
    if node is None:
        return ""
    try:
        return node.html or ""
    except Exception:  # noqa: BLE001
        return ""


def _extract_one(node, spec: str, base_url: str | None) -> str:
    if spec.startswith("regex:"):
        match = re.search(spec[6:], html_of(node), re.S)
        return unescape(match.group(1)).strip() if match else ""

    meta = _META.match(spec)
    if meta:
        prop = meta.group(1)
        selector = f'meta[property="{prop}"], meta[name="{prop}"]'
        el = getattr(node, "css_first", lambda _s: None)(selector)
        value = (el.attrs.get("content") or "") if el is not None else ""
        if base_url and value and not value.startswith(("http://", "https://", "data:")):
            value = urljoin(base_url, value)
        return value.strip()

    if "@" in spec:
        css, attr = spec.rsplit("@", 1)
        el = _select(node, css.strip())
        if el is None:
            return ""
        if not attr.strip() or attr.strip() == "text":
            return text_of(el)
        value = el.attrs.get(attr.strip()) or ""
        if base_url and value and not value.startswith(("http://", "https://", "data:")):
            value = urljoin(base_url, value)
        return value.strip()

    return text_of(_select(node, spec))


def extract(node, spec: str | None, base_url: str | None = None) -> str:
    """Resolve one selector spec.

    Supported forms:
      "css selector"            -> text of first match
      "css selector@attr"       -> attribute of first match (href/src/...)
      "css selector@text"       -> text of first match
      "a, b@href"               -> alternatives, first non-empty wins
      "regex:PATTERN"           -> first capture group in the node's HTML
      "meta:og:image"           -> <meta property=...> content
    """
    if not spec:
        return ""
    spec = spec.strip()
    if not spec:
        return ""
    if spec.startswith(("regex:", "meta:")):
        return _extract_one(node, spec, base_url)
    for alternative in split_alternatives(spec):
        value = _extract_one(node, alternative, base_url)
        if value:
            return value
    return ""


def extract_all(root, spec: str | None) -> list[str]:
    if not spec:
        return []
    try:
        nodes = root.css(spec)
    except Exception:  # noqa: BLE001
        return []
    return [text_of(node) for node in nodes if text_of(node)]


def first_image(node, attributes: tuple[str, ...] = ("data-src", "data-lazy-src", "src")) -> str:
    if node is None:
        return ""
    if getattr(node, "tag", "") == "img":
        for attr in attributes:
            value = node.attrs.get(attr)
            if value and not value.startswith("data:"):
                return value.strip()
    for img in node.css("img"):
        for attr in attributes:
            value = img.attrs.get(attr)
            if value and not value.startswith("data:"):
                return value.strip()
    return ""
