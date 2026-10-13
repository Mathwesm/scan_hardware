"""HTTP application factory for the standalone hardware scanner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from scan_hardware.api_catalog import register_catalog_routes
from scan_hardware.api_scanner import register_scan_routes
from scan_hardware.auth import MIN_API_KEY_LENGTH, validate_api_key
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
    active_catalog = catalog or (
        Catalog(database_url=active_config.database_url)
        if active_config.database_url is not None
        else Catalog(active_config.resolved_catalog_path)
    )
    if active_config.require_catalog and active_catalog.count_items() == 0:
        raise RuntimeError("Required catalog is empty")
    active_scanner = scanner or OcrScanner(active_config.ocr_min_confidence)
    app = FastAPI(title="Hardware Scanner", version="0.1.0")

    if active_config.require_api_key and (
        active_config.api_key is None
        or len(active_config.api_key.get_secret_value()) < MIN_API_KEY_LENGTH
    ):
        raise RuntimeError("API_KEY must contain at least 32 characters when auth is enabled")

    @app.middleware("http")
    async def authenticate(request: Request, call_next: Any) -> Any:
        """Protect catalog and scanning routes when deployment auth is enabled."""
        if (
            request.url.path not in {"/health", "/ready"}
            and active_config.require_api_key
            and not validate_api_key(request.headers.get("x-api-key"), active_config.api_key)
        ):
            return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report service process availability."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, int | str]:
        """Report whether the scanner has a searchable catalog."""
        count = active_catalog.count_items()
        if count == 0:
            raise HTTPException(status_code=503, detail="Catalog is empty")
        return {"status": "ready", "items": count}

    @app.get("/demo", include_in_schema=False)
    def demo() -> FileResponse:
        """Serve a small browser client for local camera and upload tests."""
        return FileResponse(Path(__file__).parent / "static" / "demo.html")

    register_catalog_routes(app, active_catalog, active_config)
    register_scan_routes(app, active_catalog, active_scanner, active_config)
    return app
