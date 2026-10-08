"""Import the two Kaggle archives into a versioned standalone SQLite catalog."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zipfile import ZipFile

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scan_hardware.core.matching import MIN_IDENTIFIER_LENGTH, normalize_identifier
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.services.catalog import Catalog, IdentifierConflictError
from scan_hardware.utils.logger import setup_logging

ROHIT_FILES = {
    "CPU.csv": Category.CPU,
    "GPU.csv": Category.GPU,
    "Motherboard.csv": Category.MOTHERBOARD,
}
WARCODER_FILES = {
    "dataset/cpu.json": Category.CPU,
    "dataset/video-card.json": Category.GPU,
    "dataset/motherboard.json": Category.MOTHERBOARD,
}
PART_CODE = re.compile(r"\(([^()]*)\)\s*$")
CPU_CLOCK = re.compile(r"\s+\d+(?:\.\d+)?\s*GHz\b", re.IGNORECASE)
MAX_REJECTED_RATE = 0.05


class InvalidCatalogError(Exception):
    """A source archive or staged catalog did not pass validation."""


class RawProduct(BaseModel):
    """Validate the minimum fields while preserving every original column."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=4)


@dataclass(frozen=True)
class SourceRow:
    """One original dataset record and its stable position."""

    dataset: str
    file_name: str
    row_number: int
    payload: dict[str, Any]


@dataclass
class ProductGroup:
    """Source rows confidently referring to the same named product."""

    category: Category
    name: str
    image_url: str | None = None
    aliases: list[str] = field(default_factory=list)
    rows: list[SourceRow] = field(default_factory=list)


def _stable_key(value: str) -> str:
    """Normalize a complete product name for conservative source joins."""
    return normalize_identifier(value)


def _read_archive(
    path: Path, dataset: str, files: dict[str, Category]
) -> tuple[list[tuple[Category, SourceRow]], list[SourceRow]]:
    """Read relevant category files and quarantine rows missing a product name."""
    valid: list[tuple[Category, SourceRow]] = []
    rejected: list[SourceRow] = []
    with ZipFile(path) as archive:
        missing = set(files) - set(archive.namelist())
        if missing:
            raise InvalidCatalogError(f"Missing expected files in {path}: {sorted(missing)}")
        for file_name, category in files.items():
            with archive.open(file_name) as stream:
                if file_name.endswith(".csv"):
                    contents = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig"))
                    rows: list[Any] = list(contents)
                else:
                    parsed = json.load(stream)
                    if not isinstance(parsed, list):
                        raise InvalidCatalogError(f"Expected a JSON list in {file_name}")
                    rows = parsed
            for row_number, raw_payload in enumerate(rows, start=1):
                payload = (
                    raw_payload if isinstance(raw_payload, dict) else {"invalid_value": raw_payload}
                )
                source = SourceRow(dataset, file_name, row_number, payload)
                try:
                    product = RawProduct.model_validate(payload)
                except ValidationError:
                    rejected.append(source)
                    continue
                if not product.name.strip():
                    rejected.append(source)
                    continue
                valid.append((category, source))
    return valid, rejected


def _join_candidates(category: Category, name: str) -> list[str]:
    """Derive only exact comparable names; never use fuzzy image attribution."""
    code = PART_CODE.search(name)
    candidates: list[str] = []
    if code:
        candidates.append(_stable_key(f"{name.split()[0]} {code.group(1)}"))
    if category is Category.CPU:
        candidates.append(_stable_key(CPU_CLOCK.split(name, maxsplit=1)[0]))
    return candidates


def _usable_image_url(value: Any) -> str | None:
    """Discard known placeholder and non-public image references."""
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or "." not in parsed.hostname:
        return None
    if "no-image" in parsed.path.casefold():
        return None
    return value


def _build_groups(
    warcoder: list[tuple[Category, SourceRow]], rohit: list[tuple[Category, SourceRow]]
) -> dict[tuple[Category, str], ProductGroup]:
    """Group same-name rows and enrich only unambiguous exact cross-source hits."""
    groups: dict[tuple[Category, str], ProductGroup] = {}
    war_names: dict[tuple[Category, str], set[tuple[Category, str]]] = {}
    for category, source in warcoder:
        name = str(source.payload["name"]).strip()
        chipset = source.payload.get("chipset") if category is Category.GPU else None
        display_name = name
        if isinstance(chipset, str) and chipset.strip():
            if _stable_key(chipset) not in _stable_key(name):
                display_name = f"{name} {chipset.strip()}"
            key = (category, f"war:{_stable_key(name)}:{_stable_key(chipset)}")
        else:
            key = (category, f"war:{_stable_key(name)}")
        group = groups.setdefault(key, ProductGroup(category=category, name=display_name))
        group.rows.append(source)
        war_names.setdefault((category, _stable_key(name)), set()).add(key)
        if display_name not in group.aliases:
            group.aliases.append(display_name)

    for category, source in rohit:
        name = str(source.payload["name"]).strip()
        candidates = {
            key
            for candidate in _join_candidates(category, name)
            for key in war_names.get((category, candidate), set())
        }
        if category is Category.GPU and len(candidates) > 1:
            candidates = {
                key
                for key in candidates
                if any(
                    isinstance(row.payload.get("chipset"), str)
                    and _stable_key(str(row.payload["chipset"])) in _stable_key(name)
                    for row in groups[key].rows
                )
            }
        matches = candidates
        key = next(iter(matches)) if len(matches) == 1 else (category, f"rohit:{_stable_key(name)}")
        group = groups.setdefault(key, ProductGroup(category=category, name=name))
        group.rows.append(source)
        image = _usable_image_url(source.payload.get("image"))
        if image is not None and group.image_url is None:
            group.image_url = image
        code = PART_CODE.search(name)
        if code and code.group(1) not in group.aliases:
            group.aliases.append(code.group(1))
        if key[1].startswith("rohit:") and name not in group.aliases:
            group.aliases.append(name)
    return groups


def _item_id(category: Category, key: str) -> str:
    """Create a stable, API-safe ID from a complete category and group key."""
    digest = hashlib.sha256(f"{category.value}:{key}".encode()).hexdigest()[:24]
    return f"{category.value}-{digest}"


def _import_groups(
    catalog: Catalog, groups: dict[tuple[Category, str], ProductGroup]
) -> dict[str, int]:
    """Persist products, exact identifiers, and every original source row."""
    counts: Counter[str] = Counter()
    alias_owner: dict[str, str] = {}
    ordered = sorted(groups.items(), key=lambda pair: (-bool(pair[1].image_url), pair[0]))
    for (category, key), group in ordered:
        item_id = _item_id(category, key)
        aliases = []
        seen_aliases: set[str] = set()
        for alias in group.aliases:
            normalized = normalize_identifier(alias)
            if (
                len(normalized) < MIN_IDENTIFIER_LENGTH
                or normalized in alias_owner
                or normalized in seen_aliases
            ):
                continue
            aliases.append(alias)
            seen_aliases.add(normalized)
        try:
            item = ItemInput(
                category=category,
                brand=group.name.split()[0],
                model=group.name[:200],
                identifiers=aliases[:30],
                image_url=group.image_url,
            )
            catalog.put_item(item_id, item)
        except (ValidationError, IdentifierConflictError) as error:
            for row in group.rows:
                catalog.put_source_record(
                    row.dataset, row.file_name, row.row_number, row.payload, None, str(error)
                )
            counts["rejected_rows"] += len(group.rows)
            continue
        for alias in item.identifiers:
            alias_owner[normalize_identifier(alias)] = item_id
        for row in group.rows:
            catalog.put_source_record(
                row.dataset, row.file_name, row.row_number, row.payload, item_id
            )
        counts[category.value] += 1
        counts["imported_rows"] += len(group.rows)
        if item.image_url is not None:
            counts["items_with_image_url"] += 1
    return dict(counts)


def _publish(catalog_path: Path, pointer: Path, counts: dict[str, int]) -> None:
    """Publish only a catalog that passes minimum count and image checks."""
    minimums = {"cpu": 500, "gpu": 2000, "motherboard": 2000, "items_with_image_url": 4000}
    failures = [
        f"{key}={counts.get(key, 0)} < {minimum}"
        for key, minimum in minimums.items()
        if counts.get(key, 0) < minimum
    ]
    total = counts.get("imported_rows", 0) + counts.get("rejected_rows", 0)
    if total == 0 or counts.get("rejected_rows", 0) / total > MAX_REJECTED_RATE:
        failures.append("Rejected source-row rate exceeds 5%")
    if failures:
        raise InvalidCatalogError("Catalog quality gate failed: " + "; ".join(failures))
    pointer.parent.mkdir(parents=True, exist_ok=True)
    if pointer.exists():
        snapshot = pointer.with_name(f"latest.{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json.bak")
        snapshot.write_bytes(pointer.read_bytes())
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"catalog_path": str(catalog_path.resolve()), "counts": counts}, indent=2),
        encoding="utf-8",
    )
    temporary.replace(pointer)


def import_archives(
    rohit_path: Path, warcoder_path: Path, output_root: Path, pointer: Path
) -> dict[str, int]:
    """Create, validate, and publish a versioned local catalog.

    Args:
        rohit_path: Complete Kaggle PC Parts by Type archive.
        warcoder_path: Complete Kaggle PC Parts archive.
        output_root: Directory holding immutable catalog versions.
        pointer: JSON pointer to the most recent validated version.

    Returns:
        Imported item, image-reference, and source-row counts.

    Raises:
        InvalidCatalogError: An archive or staged catalog is incomplete.
    """
    warcoder, bad_warcoder = _read_archive(warcoder_path, "warcoder/pc-parts", WARCODER_FILES)
    rohit, bad_rohit = _read_archive(rohit_path, "rohitmit98/pc-parts-by-type", ROHIT_FILES)
    groups = _build_groups(warcoder, rohit)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    catalog_path = output_root / run_id / "catalog.sqlite3"
    catalog = Catalog(catalog_path)
    counts = _import_groups(catalog, groups)
    for row in (*bad_warcoder, *bad_rohit):
        catalog.put_source_record(
            row.dataset, row.file_name, row.row_number, row.payload, None, "Missing valid name"
        )
        counts["rejected_rows"] = counts.get("rejected_rows", 0) + 1
    _publish(catalog_path, pointer, counts)
    logger.info("Catalog import published path={} counts={}", catalog_path, counts)
    return counts


@logger.catch(reraise=True)
def main() -> None:
    """Import the archives using local, noninteractive CLI arguments."""
    parser = argparse.ArgumentParser(description="Import the two Kaggle PC-parts archives")
    parser.add_argument("--rohit", type=Path, required=True)
    parser.add_argument("--warcoder", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("data/processed"))
    parser.add_argument("--pointer", type=Path, default=Path("data/latest.json"))
    args = parser.parse_args()
    setup_logging(log_dir=Path("logs"), serialize=True)
    import_archives(args.rohit, args.warcoder, args.output_root, args.pointer)


if __name__ == "__main__":
    main()
