from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value can be overridden with COMICPRO_<NAME>."""

    model_config = SettingsConfigDict(
        env_prefix="COMICPRO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("/data")
    port: int = 8080
    # auth
    auth_password: str = ""
    api_token: str = ""
    secret_key: str = ""
    session_days: int = 30
    # hosting
    base_path: str = ""
    trust_proxy: bool = True
    log_level: str = "INFO"
    # network
    http_proxy: str = ""
    source_timeout: float = 8.0
    search_timeout: float = 12.0
    source_min_interval: float = 0.25
    # Optional cross-language title lookup (Bangumi public metadata API).
    bangumi_enabled: bool = True
    bangumi_timeout: float = Field(default=2.0, gt=0, le=10)
    bangumi_cache_ttl: int = Field(default=86400, ge=60)
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
    # downloads / cache
    download_concurrency: int = 2
    page_concurrency: int = 6
    cache_max_gb: float = 5.0
    max_image_mb: int = 30
    # background
    check_interval_min: int = 360
    demo_source: bool = True
    mangapill: bool = True
    weebcentral: bool = True
    dongman: bool = True
    nhentai: bool = True
    # meta
    version: str = "0.1.0"

    @property
    def db_dir(self) -> Path:
        return self.data_dir / "db"

    @property
    def db_path(self) -> Path:
        return self.db_dir / "comicpro.db"

    @property
    def library_dir(self) -> Path:
        return self.data_dir / "library"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def covers_dir(self) -> Path:
        return self.cache_dir / "covers"

    @property
    def page_cache_dir(self) -> Path:
        return self.cache_dir / "pages"

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "config" / "sources"

    @property
    def secret_file(self) -> Path:
        return self.data_dir / "config" / "secret.key"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.db_dir,
            self.library_dir,
            self.cache_dir,
            self.covers_dir,
            self.page_cache_dir,
            self.sources_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def root_path(self) -> str:
        cleaned = self.base_path.strip().strip("/")
        return f"/{cleaned}" if cleaned else ""

    def load_secret(self) -> str:
        """Env secret wins; otherwise persist a generated key under /data/config."""
        if self.secret_key:
            return self.secret_key
        try:
            if self.secret_file.exists():
                value = self.secret_file.read_text(encoding="utf-8").strip()
                if value:
                    return value
            self.secret_file.parent.mkdir(parents=True, exist_ok=True)
            value = secrets.token_urlsafe(48)
            self.secret_file.write_text(value, encoding="utf-8")
            try:
                os.chmod(self.secret_file, 0o600)
            except OSError:
                pass
            return value
        except OSError:
            # read-only /data: fall back to an ephemeral key
            return secrets.token_urlsafe(48)


@lru_cache
def get_settings() -> Settings:
    return Settings()
