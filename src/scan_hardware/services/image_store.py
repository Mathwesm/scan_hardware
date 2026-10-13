"""Persist validated product views in a local, content-addressed image volume."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image

from scan_hardware.core.image_quality import foreground_coverage
from scan_hardware.models.item import Item
from scan_hardware.services.catalog import Catalog
from scan_hardware.services.ocr import InvalidImageError, validate_image

ImageView = Literal["front", "side", "back", "detail", "other"]
MIN_PRIMARY_SIDE = 800
MIN_PRIMARY_COVERAGE = 0.25


def inspect_image(content: bytes, max_bytes: int) -> tuple[str, int, int]:
    """Validate encoded bytes and return extension, width, and height."""
    validate_image(content, max_bytes)
    with Image.open(BytesIO(content)) as image:
        image_format = image.format
        width, height = image.size
    if image_format is None:
        raise InvalidImageError("Image format could not be detected")
    return {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[image_format], width, height


def store_image(
    content: bytes,
    image_dir: Path,
    catalog: Catalog,
    item_id: str,
    view: ImageView,
    is_primary: bool,
    max_bytes: int,
    enforce_primary_quality: bool = True,
) -> Item:
    """Store one exact-model image and update its gallery atomically in SQLite."""
    if catalog.get_item(item_id) is None:
        raise KeyError(item_id)
    extension, width, height = inspect_image(content, max_bytes)
    if is_primary and view != "front" and enforce_primary_quality:
        raise InvalidImageError("Only a front view can be the primary image")
    if is_primary and min(width, height) < MIN_PRIMARY_SIDE and enforce_primary_quality:
        raise InvalidImageError("Primary image must be at least 800 px on each side")
    if is_primary and enforce_primary_quality:
        coverage = foreground_coverage(content)
        if coverage is not None and coverage < MIN_PRIMARY_COVERAGE:
            raise InvalidImageError("Product is too small in the primary image frame")
    digest = hashlib.sha256(content).hexdigest()
    filename = f"{digest}.{extension}"
    destination = image_dir / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as output:
            output.write(content)
    except FileExistsError:
        pass  # Identical bytes are already stored under their SHA-256 name.
    catalog.add_image(item_id, filename, view, width, height, is_primary)
    item = catalog.get_item(item_id)
    if item is None:
        raise RuntimeError("Stored item could not be read")
    return item
