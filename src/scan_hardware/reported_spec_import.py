"""Import unambiguous OpenDB specifications without replacing existing catalog facts."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from scan_hardware.config import settings
from scan_hardware.core.matching import normalize_identifier
from scan_hardware.core.specifications import SPEC_DEFINITIONS
from scan_hardware.curation import BUILDCORES_REVISION, ReportedSpec, ReportedSpecManifest
from scan_hardware.models.item import Category, Item
from scan_hardware.reported_color_import import (
    SourceProduct,
    _source_products,
    _verify_source_revision,
)
from scan_hardware.services.catalog import Catalog

SOURCE_FOLDERS = {
    Category.CPU: "CPU",
    Category.GPU: "GPU",
    Category.MOTHERBOARD: "Motherboard",
}
PACKAGE_MANIFEST = Path(__file__).parent / "curation" / "reported_specs.json"
MIN_EXPECTED_SPECS = 5_000


def write_package_manifest(manifest: ReportedSpecManifest, path: Path) -> None:
    """Keep one specification per line so source changes remain reviewable."""
    with path.open("w", encoding="utf-8", newline="\n") as output:
        output.write('{\n  "revision": ')
        output.write(json.dumps(manifest.revision))
        output.write(',\n  "specs": [\n')
        for position, entry in enumerate(manifest.specs):
            output.write("    ")
            output.write(entry.model_dump_json())
            output.write(",\n" if position + 1 < len(manifest.specs) else "\n")
        output.write("  ]\n}\n")


class CpuCores(BaseModel):
    """Thread count from one OpenDB CPU."""

    total: int | None = Field(default=None, ge=0)
    threads: int | None = Field(default=None, ge=0)


class CpuClock(BaseModel):
    """Performance-core frequency from one OpenDB CPU."""

    base: float | None = Field(default=None, ge=0)
    boost: float | None = Field(default=None, ge=0)


class CpuClocks(BaseModel):
    """CPU clock groups."""

    performance: CpuClock = Field(default_factory=CpuClock)


class CpuCache(BaseModel):
    """CPU cache capacities in megabytes."""

    l2: float | None = Field(default=None, ge=0)
    l3: float | None = Field(default=None, ge=0)


class CpuMemory(BaseModel):
    """Supported CPU RAM generations."""

    types: list[str] = Field(default_factory=list)


class CpuSpecifications(BaseModel):
    """CPU power and memory details."""

    tdp: int | None = Field(default=None, ge=0)
    memory: CpuMemory = Field(default_factory=CpuMemory)


class CpuProduct(BaseModel):
    """Validated OpenDB CPU fields used by the service."""

    socket: str | None = None
    cores: CpuCores = Field(default_factory=CpuCores)
    clocks: CpuClocks = Field(default_factory=CpuClocks)
    cache: CpuCache = Field(default_factory=CpuCache)
    specifications: CpuSpecifications = Field(default_factory=CpuSpecifications)


class GpuProduct(BaseModel):
    """Validated OpenDB GPU fields with explicit units."""

    memory_type: str | None = None
    memory_bus: int | None = Field(default=None, ge=0)
    core_base_clock: int | None = Field(default=None, ge=0)
    core_boost_clock: int | None = Field(default=None, ge=0)
    tdp: int | None = Field(default=None, ge=0)


class BoardMemory(BaseModel):
    """Supported RAM properties from one OpenDB motherboard."""

    ram_type: str | None = None
    max: int | None = Field(default=None, ge=0)
    slots: int | None = Field(default=None, ge=0)


class BoardProduct(BaseModel):
    """Validated OpenDB motherboard fields used by the service."""

    socket: str | None = None
    form_factor: str | None = None
    memory: BoardMemory = Field(default_factory=BoardMemory)


def _positive(value: int | float | None) -> int | float | None:
    """Exclude source placeholders represented by zero."""
    return value if value is not None and value > 0 else None


def _nonempty(value: str | None) -> str | None:
    """Exclude blank and placeholder text."""
    if value is None or not value.strip() or value.strip().casefold() in {"none", "unknown"}:
        return None
    return value.strip()


def _values(category: Category, payload: dict[str, Any]) -> dict[str, str | int | float]:
    """Extract only fields whose meaning and unit are explicit in OpenDB."""
    values: dict[str, str | int | float | None]
    if category is Category.CPU:
        cpu = CpuProduct.model_validate(payload)
        memory_types = sorted({value.strip() for value in cpu.specifications.memory.types if value})
        values = {
            "socket": _nonempty(cpu.socket),
            "threads": _positive(cpu.cores.threads),
            "base_clock_ghz": _positive(cpu.clocks.performance.base),
            "boost_clock_ghz": _positive(cpu.clocks.performance.boost),
            "tdp_w": _positive(cpu.specifications.tdp),
            "l2_cache_mb": _positive(cpu.cache.l2),
            "l3_cache_mb": _positive(cpu.cache.l3),
            "memory_type": " / ".join(memory_types) if memory_types else None,
        }
    elif category is Category.GPU:
        gpu = GpuProduct.model_validate(payload)
        values = {
            "memory_type": _nonempty(gpu.memory_type),
            "memory_bus_bits": _positive(gpu.memory_bus),
            "core_clock_mhz": _positive(gpu.core_base_clock),
            "boost_clock_mhz": _positive(gpu.core_boost_clock),
            "board_power_w": _positive(gpu.tdp),
        }
    else:
        board = BoardProduct.model_validate(payload)
        values = {
            "socket": _nonempty(board.socket),
            "form_factor": _nonempty(board.form_factor),
            "max_memory_gb": _positive(board.memory.max),
            "memory_slots": _positive(board.memory.slots),
            "memory_type": _nonempty(board.memory.ram_type),
        }
    return {key: value for key, value in values.items() if value is not None}


def _cpu_name_index(
    source_root: Path, products: dict[str, SourceProduct]
) -> dict[tuple[str, str], set[str]]:
    """Index unique CPU model names separately from manufacturer part numbers."""
    source_ids = {path.stem for path in (source_root / "open-db" / "CPU").glob("*.json")}
    names: dict[tuple[str, str], set[str]] = defaultdict(set)
    for source_id in source_ids & products.keys():
        metadata = products[source_id].metadata
        key = (normalize_identifier(metadata.manufacturer), normalize_identifier(metadata.name))
        if key[1]:
            names[key].add(source_id)
    return names


def _source_candidates(
    item: Item,
    index: dict[tuple[Category, str], set[str]],
    products: dict[str, SourceProduct],
    cpu_names: dict[tuple[str, str], set[str]],
    catalog_cpu_names: Counter[tuple[str, str]],
) -> tuple[set[str], bool]:
    """Prefer exact part numbers; allow an independently checked unique CPU name."""
    candidates = {
        source_id
        for identifier in item.identifiers
        for source_id in index.get((item.category, normalize_identifier(identifier)), set())
        if normalize_identifier(products[source_id].metadata.manufacturer)
        == normalize_identifier(item.brand)
    }
    if candidates or item.category is not Category.CPU:
        return candidates, False
    name_key = (normalize_identifier(item.brand), normalize_identifier(item.model))
    if catalog_cpu_names[name_key] != 1:
        return set(), False
    matches = cpu_names.get(name_key, set())
    return matches, bool(matches)


def _cpu_cores_agree(payload: dict[str, Any], detail: Item) -> bool:
    """Reject a same-name record when independent core counts disagree."""
    source_cores = CpuProduct.model_validate(payload).cores.total
    catalog_cores = detail.specifications.get("cores")
    return (
        source_cores is not None
        and source_cores > 0
        and catalog_cores is not None
        and catalog_cores.value == source_cores
    )


def build_reported_specs(
    source_root: Path, catalog_path: Path
) -> tuple[ReportedSpecManifest, dict[str, int]]:
    """Select source-backed values only for missing catalog specifications."""
    products, index, counts = _source_products(source_root, SOURCE_FOLDERS)
    catalog = Catalog(catalog_path)
    items = catalog.list_items()
    catalog_cpu_names = Counter(
        (normalize_identifier(item.brand), normalize_identifier(item.model))
        for item in items
        if item.category is Category.CPU
    )
    cpu_names = _cpu_name_index(source_root, products)
    selected: list[ReportedSpec] = []
    for position, item in enumerate(items, start=1):
        if position % 500 == 0 or position == len(items):
            filled = position * 20 // len(items)
            logger.info(
                "OpenDB spec import progress=[{}{}] {}/{}",
                "#" * filled,
                "." * (20 - filled),
                position,
                len(items),
            )
        candidates, matched_by_name = _source_candidates(
            item, index, products, cpu_names, catalog_cpu_names
        )
        if len(candidates) != 1:
            counts["ambiguous" if candidates else "no_exact_part_number"] += 1
            continue
        source_id = next(iter(candidates))
        source_path = source_root / "open-db" / SOURCE_FOLDERS[item.category] / f"{source_id}.json"
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            values = _values(item.category, payload)
        except (OSError, json.JSONDecodeError, ValidationError):
            counts["invalid_source_specs"] += 1
            continue
        detail = catalog.get_item(item.id)
        if detail is None:
            raise RuntimeError(f"Catalog item disappeared during import: {item.id}")
        if matched_by_name:
            if not _cpu_cores_agree(payload, detail):
                counts["cpu_name_core_mismatch"] += 1
                continue
            counts["matched_cpu_name_and_cores"] += 1
        for field, value in values.items():
            existing = detail.specifications.get(field)
            is_previous_import = (
                existing is not None
                and len(existing.evidence) == 1
                and existing.evidence[0].dataset == "BuildCores OpenDB"
            )
            if existing is not None and not is_previous_import:
                counts["existing_catalog_spec"] += 1
                continue
            selected.append(
                ReportedSpec(
                    item_id=item.id,
                    category=item.category,
                    model=item.model,
                    field=field,
                    value=value,
                    unit=SPEC_DEFINITIONS[item.category][field].unit,
                    source_id=source_id,
                )
            )
            counts[f"selected_{item.category.value}_{field}"] += 1
    counts["selected"] = len(selected)
    return ReportedSpecManifest(revision=BUILDCORES_REVISION, specs=selected), dict(counts)


@logger.catch(reraise=True)
def main() -> None:
    """Write a versioned source report and optionally publish validated fields."""
    parser = argparse.ArgumentParser(description="Import exact-part-number OpenDB specs")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=settings.resolved_catalog_path)
    parser.add_argument("--output-root", type=Path, default=Path("data/processed/specs/buildcores"))
    parser.add_argument("--publish-package", action="store_true")
    args = parser.parse_args()
    _verify_source_revision(args.source_root)
    manifest, counts = build_reported_specs(args.source_root, args.catalog)
    if counts["selected"] < MIN_EXPECTED_SPECS:
        raise ValueError(f"OpenDB spec import fell below {MIN_EXPECTED_SPECS} exact values")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (output / "report.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
    if args.publish_package:
        if PACKAGE_MANIFEST.is_file():
            shutil.copy2(PACKAGE_MANIFEST, output / "previous-package-manifest.json")
        write_package_manifest(manifest, PACKAGE_MANIFEST)
    logger.info("OpenDB spec import path={} counts={}", manifest_path, counts)


if __name__ == "__main__":
    main()
