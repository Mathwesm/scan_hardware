"""HTTP application factory for the standalone hardware scanner."""

from __future__ import annotations

from fastapi import FastAPI

from scan_hardware.api_catalog import register_catalog_routes
from scan_hardware.api_scanner import register_scan_routes
from scan_hardware.config import Settings, settings
from scan_hardware.services.catalog import Catalog
from scan_hardware.services.ocr import OcrScanner


def create_app(
    *,
    config: Settings | None = None,
    catalog: Catalog | None = None,
    scanner: OcrScanner | None = None,
) -> FastAPI:
    """Build the HTTP service with replaceable catalog and OCR dependencies.

    Args:
        config: Validated runtime settings.
        catalog: Optional local catalog.
        scanner: Optional OCR scanner.

    Returns:
        Ready-to-serve FastAPI application.
    """
    active_config = config or settings
    active_catalog = catalog or Catalog(active_config.resolved_catalog_path)
    active_scanner = scanner or OcrScanner(active_config.ocr_min_confidence)
    app = FastAPI(title="Hardware Scanner", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report service process availability."""
        return {"status": "ok"}

    register_catalog_routes(app, active_catalog, active_config)
    register_scan_routes(app, active_catalog, active_scanner, active_config)
    return app
