"""Tests for configuration and logging wiring.

Both tests here have a real failure mode. The first breaks the moment someone
downgrades ``SecretStr`` to a plain ``str``, which is exactly how tokens end up in
tracebacks and log files. The second breaks if the file sink is misconfigured,
which would leave an unattended run with no evidence of what happened.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from scan_hardware.config import Settings
from scan_hardware.utils.logger import setup_logging

_TOKEN = "123456:super-secret-value"


def test_secret_token_never_appears_in_repr() -> None:
    settings = Settings(api_key=_TOKEN)

    assert _TOKEN not in repr(settings)
    assert _TOKEN not in str(settings.api_key)
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == _TOKEN


def test_setup_logging_writes_debug_records_to_disk(tmp_path: Path) -> None:
    setup_logging(log_dir=tmp_path, level="INFO")
    logger.debug("marker record {}", 7)
    logger.remove()

    written = list(tmp_path.glob("*.log"))
    assert len(written) == 1
    assert "marker record 7" in written[0].read_text(encoding="utf-8")
