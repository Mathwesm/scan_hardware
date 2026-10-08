"""HTTP routes for printed identifier recognition and lookup."""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from scan_hardware.config import Settings
from scan_hardware.core.matching import match_items
from scan_hardware.models.item import ScanResult
from scan_hardware.services.catalog import Catalog
from scan_hardware.services.ocr import InvalidImageError, OcrScanner, validate_image


class LookupRequest(BaseModel):
    """A decoded or manually entered hardware identifier."""

    text: str = Field(min_length=1, max_length=500)


def register_scan_routes(
    app: FastAPI, catalog: Catalog, scanner: OcrScanner, config: Settings
) -> None:
    """Attach text and image scan endpoints to the service application."""

    @app.post("/lookup", response_model=ScanResult)
    def lookup(request: LookupRequest) -> ScanResult:
        """Match decoded text against the local hardware catalog."""
        return match_items([request.text], catalog.list_items())

    @app.post("/scan", response_model=ScanResult)
    async def scan(image: Annotated[UploadFile, File()]) -> ScanResult:
        """Extract printed text from an image and search the catalog."""
        content = await image.read(config.max_upload_bytes + 1)
        await image.close()
        try:
            validate_image(content, config.max_upload_bytes)
        except InvalidImageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        lines = await run_in_threadpool(scanner.read_text, content)
        return match_items(lines, catalog.list_items())
