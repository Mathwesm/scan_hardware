"""HTTP routes for local hardware records and reference images."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse
from PIL import Image

from scan_hardware.config import Settings
from scan_hardware.models.item import Item, ItemInput
from scan_hardware.services.catalog import Catalog, IdentifierConflictError
from scan_hardware.services.ocr import InvalidImageError, validate_image

ItemId = Annotated[str, ApiPath(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


def _image_extension(content: bytes) -> str:
    """Choose a safe extension from validated image bytes."""
    with Image.open(BytesIO(content)) as image:
        image_format = image.format
    if image_format is None:
        raise InvalidImageError("Image format could not be detected")
    return {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[image_format]


def _store_image(content: bytes, image_dir: Path, catalog: Catalog, item_id: str) -> Item:
    """Write content-addressed image bytes and update the catalog pointer."""
    digest = hashlib.sha256(content).hexdigest()
    filename = f"{digest}.{_image_extension(content)}"
    destination = image_dir / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as output:
            output.write(content)
    except FileExistsError:
        pass  # Identical image bytes are already stored under their SHA-256 name.
    catalog.set_image_digest(item_id, filename)
    item = catalog.get_item(item_id)
    if item is None:
        raise RuntimeError("Stored item could not be read")
    return item


def register_catalog_routes(app: FastAPI, catalog: Catalog, config: Settings) -> None:
    """Attach catalog endpoints to the service application."""

    @app.put("/items/{item_id}", response_model=Item)
    def put_item(item_id: ItemId, item: ItemInput) -> Item:
        """Create or replace one hardware item idempotently."""
        try:
            return catalog.put_item(item_id, item)
        except IdentifierConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/items/{item_id}", response_model=Item)
    def get_item(item_id: ItemId) -> Item:
        """Fetch one registered hardware item."""
        item = catalog.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        return item

    @app.get("/items/{item_id}/sources")
    def get_item_sources(item_id: ItemId) -> list[dict[str, Any]]:
        """Return original imported rows, including every source column."""
        if catalog.get_item(item_id) is None:
            raise HTTPException(status_code=404, detail="Item not found")
        return catalog.get_source_records(item_id)

    register_image_routes(app, catalog, config)


def register_image_routes(app: FastAPI, catalog: Catalog, config: Settings) -> None:
    """Attach image upload and download endpoints to the service."""

    @app.put("/items/{item_id}/image", response_model=Item)
    async def put_image(item_id: ItemId, image: Annotated[UploadFile, File()]) -> Item:
        """Attach an image to a registered item."""
        if catalog.get_item(item_id) is None:
            raise HTTPException(status_code=404, detail="Item not found")
        content = await image.read(config.max_upload_bytes + 1)
        await image.close()
        try:
            validate_image(content, config.max_upload_bytes)
        except InvalidImageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _store_image(content, config.image_dir, catalog, item_id)

    @app.get("/items/{item_id}/image", response_class=FileResponse)
    def get_image(item_id: ItemId) -> FileResponse:
        """Serve the current local catalog image."""
        digest = catalog.get_image_digest(item_id)
        if digest is None:
            raise HTTPException(status_code=404, detail="Image not found")
        path = config.image_dir / digest
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Image file not found")
        return FileResponse(path)
