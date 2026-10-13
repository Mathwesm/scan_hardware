"""Estimate catalog colors from locally supplied hardware photographs."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from scan_hardware.config import settings
from scan_hardware.core.color import estimate_photo_color
from scan_hardware.curation import EstimatedColor, EstimatedColorManifest
from scan_hardware.models.item import Category
from scan_hardware.services.catalog import Catalog
from scan_hardware.services.ocr import InvalidImageError, validate_image

PACKAGE_MANIFEST = Path(__file__).parent / "curation" / "estimated_colors.json"
MAX_IMAGE_BYTES = 8_000_000


class LocalImage(BaseModel):
    """A local photo paired with an existing catalog item ID."""

    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    path: Path


class LocalImageManifest(BaseModel):
    """Batch input with paths relative to its own directory."""

    images: list[LocalImage] = Field(min_length=1)


def build_manifest(
    input_path: Path, catalog_path: Path
) -> tuple[EstimatedColorManifest, dict[str, int]]:
    """Classify local photos while rejecting stale IDs and unusable images.

    Args:
        input_path: UTF-8 JSON list of item IDs and relative image paths.
        catalog_path: Existing catalog database.

    Returns:
        Accepted estimates and per-reason counts.
    """
    source = LocalImageManifest.model_validate_json(input_path.read_text(encoding="utf-8"))
    catalog = Catalog(catalog_path)
    counts: Counter[str] = Counter()
    selected: dict[str, EstimatedColor] = {}
    conflicted_ids: set[str] = set()
    for entry in source.images:
        if entry.item_id in conflicted_ids:
            continue
        item = catalog.get_item(entry.item_id)
        if item is None or item.category is Category.CPU:
            counts["unknown_or_cpu"] += 1
            continue
        color = item.specifications.get("color")
        if color is not None and color.value is not None:
            counts["catalog_color_exists"] += 1
            continue
        path = input_path.parent / entry.path
        try:
            content = path.read_bytes()
            validate_image(content, MAX_IMAGE_BYTES)
        except (OSError, InvalidImageError):
            counts["unreadable_image"] += 1
            continue
        estimate = estimate_photo_color(content)
        if estimate is None:
            counts["uncertain_color"] += 1
            continue
        candidate = EstimatedColor(
            item_id=item.id,
            category=item.category,
            model=item.model,
            color=estimate,
        )
        previous = selected.get(item.id)
        if previous is not None and previous.color != candidate.color:
            selected.pop(item.id)
            conflicted_ids.add(item.id)
            counts["conflicting_photos"] += 1
            continue
        selected[item.id] = candidate
    counts["selected"] = len(selected)
    return EstimatedColorManifest(colors=list(selected.values())), dict(counts)


def merge_manifests(
    existing: EstimatedColorManifest, incoming: EstimatedColorManifest
) -> EstimatedColorManifest:
    """Retain previous estimates unless a new photo contradicts the same item."""
    merged = {entry.item_id: entry for entry in existing.colors}
    for candidate in incoming.colors:
        previous = merged.get(candidate.item_id)
        if previous is not None and (
            previous.model != candidate.model or previous.color != candidate.color
        ):
            merged.pop(candidate.item_id)
            continue
        merged[candidate.item_id] = candidate
    return EstimatedColorManifest(colors=list(merged.values()))


def save_manifest(
    manifest: EstimatedColorManifest, counts: dict[str, int], output_root: Path
) -> Path:
    """Write one immutable result and quality report for review."""
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    directory = output_root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    output = directory / "manifest.json"
    output.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (directory / "report.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
    return output


@logger.catch(reraise=True)
def main() -> None:
    """Process locally supplied photos and optionally publish their estimates."""
    parser = argparse.ArgumentParser(description="Estimate hardware colors from local photos")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--catalog", type=Path, default=settings.resolved_catalog_path)
    parser.add_argument("--output-root", type=Path, default=Path("data/processed/colors"))
    parser.add_argument("--publish-package", action="store_true")
    args = parser.parse_args()
    manifest, counts = build_manifest(args.manifest, args.catalog)
    if args.publish_package and PACKAGE_MANIFEST.is_file():
        existing = EstimatedColorManifest.model_validate_json(
            PACKAGE_MANIFEST.read_text(encoding="utf-8")
        )
        manifest = merge_manifests(existing, manifest)
    output = save_manifest(manifest, counts, args.output_root)
    if args.publish_package:
        if not manifest.colors:
            raise ValueError("No reliable color estimates were produced")
        if PACKAGE_MANIFEST.is_file():
            shutil.copy2(PACKAGE_MANIFEST, output.parent / "previous-package-manifest.json")
        shutil.copy2(output, PACKAGE_MANIFEST)
    logger.info(
        "Color batch report path={} counts={} published={}", output, counts, args.publish_package
    )


if __name__ == "__main__":
    main()
