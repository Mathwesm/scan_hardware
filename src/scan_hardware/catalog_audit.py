"""Produce a versioned specification and image-rights audit for a catalog."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from scan_hardware.config import settings
from scan_hardware.core.specifications import build_specifications
from scan_hardware.curation import verified_images
from scan_hardware.image_enrichment import image_for_item
from scan_hardware.models.item import Category


def audit_catalog(catalog_path: Path) -> dict[str, Any]:
    """Count field coverage, source conflicts, and verified corrections.

    Args:
        catalog_path: Existing imported SQLite catalog.

    Returns:
        Category totals and per-field status counts.

    Raises:
        FileNotFoundError: The selected database does not exist.
    """
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Catalog is missing: {catalog_path}")
    connection = sqlite3.connect(catalog_path)
    try:
        items = connection.execute("SELECT id, category, model, image_url FROM items").fetchall()
        source_rows = connection.execute(
            "SELECT item_id, dataset, payload_json FROM source_records WHERE item_id IS NOT NULL"
        ).fetchall()
    finally:
        connection.close()
    by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item_id, dataset, payload_json in source_rows:
        by_item[item_id].append({"dataset": dataset, "data": json.loads(payload_json)})
    items_by_category: Counter[str] = Counter()
    coverage: dict[str, Counter[str]] = defaultdict(Counter)
    conflicts: dict[str, Counter[str]] = defaultdict(Counter)
    verified: dict[str, Counter[str]] = defaultdict(Counter)
    image_counts: Counter[str] = Counter()
    curated_images = verified_images()
    for item_id, category_name, model, image_url in items:
        items_by_category[category_name] += 1
        curated = curated_images.get(item_id)
        image_counts[
            "reviewed"
            if curated is not None and curated.license_name is not None
            else "unreviewed_url"
            if image_url or curated is not None
            else "matched_feed"
            if image_for_item(item_id, Category(category_name), model) is not None
            else "missing"
        ] += 1
        for field, spec in build_specifications(
            Category(category_name), by_item[item_id], item_id
        ).items():
            coverage[category_name][field] += 1
            if spec.status == "conflict":
                conflicts[category_name][field] += 1
            if spec.status == "verified":
                verified[category_name][field] += 1
    return {
        "items": dict(items_by_category),
        "coverage": {key: dict(value) for key, value in coverage.items()},
        "conflicts": {key: dict(value) for key, value in conflicts.items()},
        "verified": {key: dict(value) for key, value in verified.items()},
        "images": dict(image_counts),
    }


@logger.catch(reraise=True)
def main() -> None:
    """Write an immutable audit report from the selected catalog."""
    parser = argparse.ArgumentParser(description="Audit imported hardware catalog quality")
    parser.add_argument("--catalog", type=Path, default=settings.resolved_catalog_path)
    parser.add_argument("--output-root", type=Path, default=Path("data/audit"))
    args = parser.parse_args()
    report = audit_catalog(args.catalog)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output_root / run_id / "report.json"
    output.parent.mkdir(parents=True, exist_ok=False)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    logger.info(
        "Catalog audit saved path={} items={} images={}", output, report["items"], report["images"]
    )


if __name__ == "__main__":
    main()
