"""Join BuildCores OpenDB colors to exact catalog manufacturer part numbers."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from scan_hardware.config import settings
from scan_hardware.core.matching import normalize_identifier
from scan_hardware.curation import (
    BUILDCORES_REVISION,
    ReportedColor,
    ReportedColorManifest,
)
from scan_hardware.models.item import Category
from scan_hardware.services.catalog import Catalog

SOURCE_REPO = "https://github.com/buildcores/buildcores-open-db"
PACKAGE_MANIFEST = Path(__file__).parent / "curation" / "reported_colors.json"
MIN_EXPECTED_MATCHES = 1_200
MIN_PART_NUMBER_LENGTH = 7
SOURCE_FOLDERS = {Category.GPU: "GPU", Category.MOTHERBOARD: "Motherboard"}
COLOR_NAMES = {
    "BLACK": "Black",
    "GREY": "Gray",
    "WHITE": "White",
    "RED": "Red",
    "BLUE": "Blue",
    "GOLD": "Gold",
    "ORANGE": "Orange",
    "GREEN": "Green",
    "BROWN": "Brown",
    "YELLOW": "Yellow",
    "PURPLE": "Purple",
    "PINK": "Pink",
}


class SourceIdentifier(BaseModel):
    """One BuildCores product identifier."""

    type: str
    value: str


class SourceIdentifiers(BaseModel):
    """Manufacturer and retail identifiers for one record."""

    identifiers: list[SourceIdentifier] = Field(default_factory=list)


class SourceMetadata(BaseModel):
    """Identity fields needed for safe catalog joining."""

    manufacturer: str
    part_numbers: list[str] = Field(default_factory=list)


class SourceProduct(BaseModel):
    """Subset of an OpenDB record needed to import its color."""

    opendb_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    metadata: SourceMetadata
    color: list[str] = Field(default_factory=list)
    identifiers: SourceIdentifiers = Field(default_factory=SourceIdentifiers)

    def part_numbers(self) -> set[str]:
        """Return normalized manufacturer part numbers, excluding generic names."""
        raw = self.metadata.part_numbers + [
            entry.value for entry in self.identifiers.identifiers if entry.type == "mpn"
        ]
        return {
            value
            for part in raw
            if len(value := normalize_identifier(part)) >= MIN_PART_NUMBER_LENGTH
        }

    def display_color(self) -> str | None:
        """Render one or more source colors while excluding lighting labels."""
        if not self.color or any(value not in COLOR_NAMES for value in self.color):
            return None
        return " / ".join(dict.fromkeys(COLOR_NAMES[value] for value in self.color))


def _source_products(
    source_root: Path,
) -> tuple[dict[str, SourceProduct], dict[tuple[Category, str], set[str]], Counter[str]]:
    """Read local OpenDB records and index only exact manufacturer part numbers."""
    products: dict[str, SourceProduct] = {}
    index: dict[tuple[Category, str], set[str]] = defaultdict(set)
    counts: Counter[str] = Counter()
    for category, folder in SOURCE_FOLDERS.items():
        paths = (source_root / "open-db" / folder).glob("*.json")
        for path in paths:
            try:
                product = SourceProduct.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError):
                counts["invalid_source_records"] += 1
                continue
            products[product.opendb_id] = product
            for part_number in product.part_numbers():
                index[(category, part_number)].add(product.opendb_id)
            counts[f"read_{category.value}"] += 1
    return products, index, counts


def build_reported_manifest(
    source_root: Path, catalog_path: Path
) -> tuple[ReportedColorManifest, dict[str, int]]:
    """Accept only unique same-brand part-number matches with missing color."""
    products, index, counts = _source_products(source_root)
    catalog = Catalog(catalog_path)
    selected: list[ReportedColor] = []
    for item in catalog.list_items():
        if item.category not in SOURCE_FOLDERS:
            continue
        candidates = {
            source_id
            for identifier in item.identifiers
            for source_id in index.get((item.category, normalize_identifier(identifier)), set())
            if normalize_identifier(products[source_id].metadata.manufacturer)
            == normalize_identifier(item.brand)
        }
        if len(candidates) != 1:
            counts["ambiguous" if candidates else "no_exact_part_number"] += 1
            continue
        product = products[next(iter(candidates))]
        color = product.display_color()
        if color is None:
            counts["unusable_source_color"] += 1
            continue
        details = catalog.get_item(item.id)
        if details is None:
            raise RuntimeError(f"Catalog item disappeared during import: {item.id}")
        existing = details.specifications.get("color")
        is_previous_import = (
            existing is not None
            and len(existing.evidence) == 1
            and existing.evidence[0].dataset == "BuildCores OpenDB"
        )
        if existing is not None and not is_previous_import:
            counts["existing_catalog_color"] += 1
            continue
        selected.append(
            ReportedColor(
                item_id=item.id,
                category=item.category,
                model=item.model,
                color=color,
                source_id=product.opendb_id,
            )
        )
        counts[f"selected_{item.category.value}"] += 1
    counts["selected"] = len(selected)
    return ReportedColorManifest(revision=BUILDCORES_REVISION, colors=selected), dict(counts)


def _verify_source_revision(source_root: Path) -> None:
    """Reject a mutable or unexpected OpenDB checkout."""
    executable = shutil.which("git")
    if executable is None:
        raise FileNotFoundError("Git is required to verify the OpenDB revision")
    # The executable and argument list are fixed; shell expansion is disabled.
    result = subprocess.run(  # noqa: S603
        [executable, "-C", str(source_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    if result.stdout.strip() != BUILDCORES_REVISION:
        raise ValueError("OpenDB checkout differs from the pinned revision")


@logger.catch(reraise=True)
def main() -> None:
    """Generate a versioned import report and optionally publish its manifest."""
    parser = argparse.ArgumentParser(description="Import exact-part-number OpenDB colors")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=settings.resolved_catalog_path)
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/processed/colors/buildcores")
    )
    parser.add_argument("--publish-package", action="store_true")
    args = parser.parse_args()
    _verify_source_revision(args.source_root)
    manifest, counts = build_reported_manifest(args.source_root, args.catalog)
    if counts["selected"] < MIN_EXPECTED_MATCHES:
        raise ValueError(f"OpenDB color import fell below {MIN_EXPECTED_MATCHES} exact matches")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (output / "report.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
    if args.publish_package:
        if PACKAGE_MANIFEST.is_file():
            shutil.copy2(PACKAGE_MANIFEST, output / "previous-package-manifest.json")
        shutil.copy2(manifest_path, PACKAGE_MANIFEST)
    logger.info("OpenDB color import path={} counts={}", manifest_path, counts)


if __name__ == "__main__":
    main()
