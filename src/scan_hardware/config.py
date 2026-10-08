"""Application settings, validated at import time.

Reading configuration through pydantic means a missing or malformed variable fails
loudly at boot instead of surfacing as a confusing ``None`` deep inside a pipeline run.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    log_dir: Path = Path("logs")
    log_serialize: bool = False
    catalog_path: Path | None = None
    catalog_latest_pointer: Path = Path("data/latest.json")
    image_dir: Path = Path("data/images")
    max_upload_bytes: int = 8_000_000
    ocr_min_confidence: float = 0.4
    host: str = "127.0.0.1"
    port: int = 8000

    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    @property
    def resolved_catalog_path(self) -> Path:
        """Use an explicit path or the last validated imported catalog."""
        if self.catalog_path is not None:
            return self.catalog_path
        if self.catalog_latest_pointer.exists():
            metadata = json.loads(self.catalog_latest_pointer.read_text(encoding="utf-8"))
            path = Path(metadata["catalog_path"])
            if not path.is_file():
                raise FileNotFoundError(f"Published catalog is missing: {path}")
            return path
        return Path("data/catalog.sqlite3")

    @property
    def telegram_enabled(self) -> bool:
        """Whether both Telegram credentials are present."""
        return self.telegram_bot_token is not None and self.telegram_chat_id is not None


settings = Settings()
