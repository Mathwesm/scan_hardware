"""Regression tests for exact-source specification enrichment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scan_hardware.core.specifications import build_specifications
from scan_hardware.curation import BUILDCORES_REVISION, ReportedSpec, ReportedSpecManifest
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.reported_spec_import import _values, build_reported_specs, write_package_manifest
from scan_hardware.services.catalog import Catalog


def _write_board(source_root: Path, source_id: str, socket: str = "AM5") -> None:
    folder = source_root / "open-db" / "Motherboard"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "opendb_id": source_id,
        "metadata": {"manufacturer": "ASUS", "part_numbers": ["TEST-BOARD-123"]},
        "socket": socket,
        "form_factor": "Micro ATX",
        "memory": {"ram_type": "DDR5", "max": 128, "slots": 4},
    }
    (folder / f"{source_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_cpu(source_root: Path, source_id: str, cores: int = 6) -> None:
    folder = source_root / "open-db" / "CPU"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "opendb_id": source_id,
        "metadata": {
            "name": "AMD Ryzen 5 3600X",
            "manufacturer": "AMD",
            "part_numbers": ["100-100000022BOX"],
        },
        "socket": "AM4",
        "cores": {"total": cores, "threads": 12},
        "cache": {"l2": 3, "l3": 32},
        "specifications": {"memory": {"types": ["DDR4"]}},
    }
    (folder / f"{source_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _catalog(path: Path, with_socket: bool = False) -> Catalog:
    catalog = Catalog(path)
    catalog.put_item(
        "motherboard-test-board",
        ItemInput(
            category=Category.MOTHERBOARD,
            brand="Asus",
            model="Asus Test Board",
            identifiers=["TEST-BOARD-123"],
        ),
    )
    if with_socket:
        catalog.put_source_record(
            "test", "board.csv", 1, {"socket": "AM4"}, "motherboard-test-board"
        )
    return catalog


def test_exact_part_number_fills_missing_fields_without_overriding_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_board(source_root, "00000000-0000-4000-8000-000000000001")
    catalog = _catalog(tmp_path / "catalog.sqlite3", with_socket=True)

    manifest, report = build_reported_specs(source_root, catalog.path)

    values = {entry.field: entry.value for entry in manifest.specs}
    assert values == {
        "form_factor": "Micro ATX",
        "max_memory_gb": 128,
        "memory_slots": 4,
        "memory_type": "DDR5",
    }
    assert report["existing_catalog_spec"] == 1


def test_ambiguous_manufacturer_part_number_is_rejected(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_board(source_root, "00000000-0000-4000-8000-000000000001")
    _write_board(source_root, "00000000-0000-4000-8000-000000000002", socket="AM4")
    catalog = _catalog(tmp_path / "catalog.sqlite3")

    manifest, report = build_reported_specs(source_root, catalog.path)

    assert manifest.specs == []
    assert report["ambiguous"] == 1


@pytest.mark.parametrize("source_cores", [6, 8, 0])
def test_unique_cpu_name_requires_matching_core_count(tmp_path: Path, source_cores: int) -> None:
    """A name alone may enrich a CPU only when independent core counts agree."""
    source_root = tmp_path / "source"
    _write_cpu(source_root, "00000000-0000-4000-8000-000000000003", source_cores)
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.put_item(
        "cpu-ryzen-3600x",
        ItemInput(
            category=Category.CPU,
            brand="AMD",
            model="AMD Ryzen 5 3600X",
            identifiers=["AMD Ryzen 5 3600X"],
        ),
    )
    catalog.put_source_record("catalog", "cpu.csv", 1, {"core_count": 6}, "cpu-ryzen-3600x")

    manifest, report = build_reported_specs(source_root, catalog.path)

    if source_cores == 6:
        assert {entry.field for entry in manifest.specs} == {
            "socket",
            "threads",
            "memory_type",
            "l2_cache_mb",
            "l3_cache_mb",
        }
        assert report["matched_cpu_name_and_cores"] == 1
    else:
        assert manifest.specs == []
        assert report["cpu_name_core_mismatch"] == 1


def test_cpu_cache_keeps_fractional_megabytes_and_skips_zero() -> None:
    values = _values(
        Category.CPU,
        {
            "socket": "LGA1151",
            "cores": {"threads": 12},
            "clocks": {"performance": {"base": 4.0, "boost": 5.0}},
            "cache": {"l2": 1.5, "l3": 12},
            "specifications": {"tdp": 0, "memory": {"types": ["DDR4"]}},
        },
    )
    assert values["l2_cache_mb"] == 1.5
    assert "tdp_w" not in values


def test_reported_spec_rejects_wrong_unit() -> None:
    with pytest.raises(ValueError, match="field or unit is invalid"):
        ReportedSpec(
            item_id="cpu-test",
            category=Category.CPU,
            model="Test CPU",
            field="l2_cache_mb",
            value=1.5,
            unit="GHz",
            source_id="00000000-0000-4000-8000-000000000001",
        )


def test_packaged_manifest_round_trips_with_one_spec_per_line(tmp_path: Path) -> None:
    manifest = ReportedSpecManifest(
        revision=BUILDCORES_REVISION,
        specs=[
            ReportedSpec(
                item_id="cpu-test",
                category=Category.CPU,
                model="Test CPU",
                field="l2_cache_mb",
                value=1.5,
                unit="MB",
                source_id="00000000-0000-4000-8000-000000000001",
            )
        ],
    )
    path = tmp_path / "reported_specs.json"

    write_package_manifest(manifest, path)

    assert ReportedSpecManifest.model_validate_json(path.read_text(encoding="utf-8")) == manifest
    assert len(path.read_text(encoding="utf-8").splitlines()) == 6


def test_reported_spec_is_used_only_without_existing_catalog_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fact = ReportedSpec(
        item_id="motherboard-test-board",
        category=Category.MOTHERBOARD,
        model="Asus Test Board",
        field="memory_type",
        value="DDR5",
        source_id="00000000-0000-4000-8000-000000000001",
    )
    monkeypatch.setattr(
        "scan_hardware.core.specifications.reported_specs",
        lambda: {(fact.item_id, fact.field): fact},
    )
    missing = build_specifications(Category.MOTHERBOARD, [], fact.item_id)
    existing = build_specifications(
        Category.MOTHERBOARD,
        [{"dataset": "test", "data": {"socket": "AM4"}}],
        fact.item_id,
    )

    assert missing["memory_type"].value == "DDR5"
    assert missing["memory_type"].status == "reported"
    assert existing["socket"].value == "AM4"
