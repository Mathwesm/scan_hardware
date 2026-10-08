"""Start the standalone HTTP scanner with ``python -m scan_hardware``."""

from __future__ import annotations

import uvicorn
from loguru import logger

from scan_hardware.config import settings
from scan_hardware.utils.logger import setup_logging


@logger.catch(reraise=True)
def main() -> None:
    """Configure logging and serve the HTTP API."""
    setup_logging(
        log_dir=settings.log_dir,
        level=settings.log_level,
        serialize=settings.log_serialize,
    )
    uvicorn.run(
        "scan_hardware.api:create_app", factory=True, host=settings.host, port=settings.port
    )


if __name__ == "__main__":
    main()
