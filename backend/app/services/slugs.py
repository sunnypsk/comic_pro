from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
from pathlib import Path

from fastapi import HTTPException

_ILLEGAL = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_SPACES = re.compile(r"\s+")
_DOTS = re.compile(r"^\.+|\.+$")


def b64e(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def b64d(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode("utf-8")


def slugify(text: str, max_len: int = 80, fallback: str = "item") -> str:
    cleaned = _ILLEGAL.sub(" ", text or "")
    cleaned = _SPACES.sub(" ", cleaned).strip()
    cleaned = _DOTS.sub("", cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" .")
    return cleaned or fallback


def short_hash(value: str, length: int = 8) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def ensure_within(base: Path, target: Path) -> Path:
    """Resolve `target` and guarantee it stays inside `base`."""
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if target_resolved != base_resolved and base_resolved not in target_resolved.parents:
        raise HTTPException(status_code=400, detail={"code": "PATH_ESCAPE", "message": "invalid path"})
    return target_resolved


def sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(secret: str, message: str, signature: str) -> bool:
    return hmac.compare_digest(sign(secret, message), signature or "")


def image_signature(secret: str, source_id: str, url: str, expires: int) -> str:
    return sign(secret, f"img|{source_id}|{url}|{expires}")


def new_expiry(seconds: int = 6 * 3600) -> int:
    return int(time.time()) + seconds


def password_hash(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1${}${}".format(
        base64.b64encode(salt).decode("ascii"), base64.b64encode(derived).decode("ascii")
    )


def password_verify(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(derived, expected)
    except (ValueError, TypeError):
        return False
