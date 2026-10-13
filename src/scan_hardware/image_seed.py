"""Load reviewed local product views into the persistent Docker image volume."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from scan_hardware.config import settings
from scan_hardware.services.catalog import Catalog
from scan_hardware.services.image_store import ImageView, store_image
from scan_hardware.services.ocr import InvalidImageError


class SeedEntry(BaseModel):
    """One locally reviewed exact-model photograph."""

    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    path: Path
    view: ImageView
    is_primary: bool | None = None

    @field_validator("path")
    @classmethod
    def require_relative_path(cls, value: Path) -> Path:
        """Keep source files inside the mounted import directory."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("Image path must be relative to its manifest")
        return value


class SeedManifest(BaseModel):
    """Manifest envelope that quarantines invalid entries independently."""

    images: list[dict[str, Any]]


def seed_images(
    manifest_path: Path,
    catalog: Catalog,
    image_dir: Path,
    report_root: Path,
    max_bytes: int,
) -> dict[str, int]:
    """Import each local view idempotently and keep a versioned quality report."""
    manifest = SeedManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    source_root = manifest_path.parent.resolve()
    counts: Counter[str] = Counter()
    total = len(manifest.images)
    for position, raw in enumerate(manifest.images, start=1):
        try:
            entry = SeedEntry.model_validate(raw)
            source = (source_root / entry.path).resolve()
            if not source.is_relative_to(source_root):
                raise ValueError("Image path escapes the import directory")
            with source.open("rb") as handle:
                content = handle.read(max_bytes + 1)
            store_image(
                content,
                image_dir,
                catalog,
                entry.item_id,
                entry.view,
                entry.view == "front" if entry.is_primary is None else entry.is_primary,
                max_bytes,
            )
            counts["imported"] += 1
        except (OSError, ValidationError, ValueError, KeyError, InvalidImageError) as error:
            counts["rejected"] += 1
            logger.warning("Image seed rejected position={} reason={}", position, str(error))
        if position % max(1, total // 20) == 0 or position == total:
            filled = position * 20 // total
            logger.info(
                "Image seed progress=[{}{}] {}/{}",
                "#" * filled,
                "." * (20 - filled),
                position,
                total,
            )
    counts["total"] = total
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = report_root / run_id / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=False)
    report_path.write_text(json.dumps(dict(counts), indent=2), encoding="utf-8")
    if total and not counts["imported"]:
        raise RuntimeError(f"No manifest images could be imported: {report_path}")
    logger.info("Image seed complete report={} counts={}", report_path, dict(counts))
    return dict(counts)


@logger.catch(reraise=True)
def main() -> None:
    """Seed a selected catalog from a host-provided image manifest."""
    parser = argparse.ArgumentParser(description="Import local reviewed product images")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=settings.resolved_catalog_path)
    parser.add_argument("--image-dir", type=Path, default=settings.image_dir)
    parser.add_argument("--report-root", type=Path, default=Path("data/processed/image-import"))
    args = parser.parse_args()
    seed_images(
        args.manifest,
        Catalog(args.catalog),
        args.image_dir,
        args.report_root,
        settings.max_upload_bytes,
    )


if __name__ == "__main__":
    main()
