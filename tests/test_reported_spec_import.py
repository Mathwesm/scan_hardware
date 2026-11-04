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
        "chipset": "AMD B650",
        "form_factor": "Micro ATX",
        "memory": {"ram_type": "DDR5", "max": 128, "slots": 4},
    }
    (folder / f"{source_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_cpu(
    source_root: Path,
    source_id: str,
    cores: int = 6,
    *,
    name: str = "AMD Ryzen 5 3600X",
    manufacturer: str = "AMD",
    socket: str = "AM4",
) -> None:
    folder = source_root / "open-db" / "CPU"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "opendb_id": source_id,
        "metadata": {
            "name": name,
            "manufacturer": manufacturer,
            "part_numbers": ["100-100000022BOX"],
        },
        "socket": socket,
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
        "chipset": "AMD B650",
        "form_factor": "Micro ATX",
        "max_memory_gb": 128,
        "memory_slots": 4,
        "memory_type": "DDR5",
    }
    assert report["existing_catalog_spec"] == 1


def test_board_chipset_disagrees_with_socket_vendor() -> None:
    """Do not publish an Intel chipset on a board reported with an AMD socket."""
    values = _values(Category.MOTHERBOARD, {"socket": "AM5", "chipset": "Intel B760"})

    assert values["socket"] == "AM5"
    assert "chipset" not in values


def test_board_ports_return_flat_counts_without_unreliable_pcie_generation() -> None:
    """Count connectors and slots without publishing a misleading PCIe generation."""
    values = _values(
        Category.MOTHERBOARD,
        {
            "socket": "LGA 1155",
            "storage_devices": {"sata_6_gb_s": 5, "sata_3_gb_s": 4},
            "pcie_slots": [
                {"gen": "4.0", "quantity": 3, "lanes": 16},
                {"gen": "4.0", "quantity": 3, "lanes": 1},
            ],
        },
    )

    assert {key: value for key, value in values.items() if "sata" in key or "pcie" in key} == {
        "sata_slots": 9,
        "pcie_slots": 6,
    }
    assert not any("generation" in key or "gen" in key for key in values)


@pytest.mark.parametrize(
    ("storage", "slots"),
    [
        ({"sata_6_gb_s": 0, "sata_3_gb_s": 0}, []),
        ({"sata_6_gb_s": -1, "sata_3_gb_s": 4}, [{"quantity": 0, "lanes": 16}]),
        ({"sata_6_gb_s": "six", "sata_3_gb_s": 0}, [{"quantity": 1, "lanes": 32}]),
        ({"sata_6_gb_s": True, "sata_3_gb_s": 4}, [{"quantity": "1", "lanes": 16}]),
    ],
)
def test_board_ports_reject_placeholders_and_invalid_counts(
    storage: dict[str, object], slots: list[dict[str, object]]
) -> None:
    values = _values(Category.MOTHERBOARD, {"storage_devices": storage, "pcie_slots": slots})

    assert not any("sata" in key or "pcie" in key for key in values)


def test_exact_board_imports_connector_counts_with_source_id(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_id = "00000000-0000-4000-8000-000000000008"
    _write_board(source_root, source_id)
    path = source_root / "open-db" / "Motherboard" / f"{source_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["storage_devices"] = {"sata_6_gb_s": 4, "sata_3_gb_s": 2}
    payload["pcie_slots"] = [
        {"quantity": 1, "lanes": 16},
        {"quantity": 2, "lanes": 1},
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    catalog = _catalog(tmp_path / "catalog.sqlite3")

    manifest, report = build_reported_specs(source_root, catalog.path)

    connectors = {
        entry.field: (entry.value, entry.source_id)
        for entry in manifest.specs
        if entry.field in {"sata_slots", "pcie_slots"}
    }
    assert connectors == {"sata_slots": (6, source_id), "pcie_slots": (3, source_id)}
    assert report["selected_motherboard_sata_slots"] == 1
    assert report["selected_motherboard_pcie_slots"] == 1


def test_board_ports_are_rejected_when_catalog_socket_disagrees(tmp_path: Path) -> None:
    """A reused part number with a conflicting socket must not gain connector counts."""
    source_root = tmp_path / "source"
    source_id = "00000000-0000-4000-8000-000000000009"
    _write_board(source_root, source_id, socket="AM5")
    path = source_root / "open-db" / "Motherboard" / f"{source_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["storage_devices"] = {"sata_6_gb_s": 4, "sata_3_gb_s": 0}
    payload["pcie_slots"] = [{"quantity": 1, "lanes": 16}]
    path.write_text(json.dumps(payload), encoding="utf-8")
    catalog = _catalog(tmp_path / "catalog.sqlite3", with_socket=True)

    manifest, report = build_reported_specs(source_root, catalog.path)

    assert not any(entry.field in {"sata_slots", "pcie_slots"} for entry in manifest.specs)
    assert report["board_socket_mismatch"] == 1


def test_ambiguous_manufacturer_part_number_is_rejected(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_board(source_root, "00000000-0000-4000-8000-000000000001")
    _write_board(source_root, "00000000-0000-4000-8000-000000000002", socket="AM4")
    catalog = _catalog(tmp_path / "catalog.sqlite3")

    manifest, report = build_reported_specs(source_root, catalog.path)

    assert manifest.specs == []
    assert report["ambiguous"] == 1


def test_brand_prefixed_legacy_identifier_matches_exact_part_number(tmp_path: Path) -> None:
    """Kaggle's brand prefix must not hide a unique OpenDB product code."""
    source_root = tmp_path / "source"
    _write_board(source_root, "00000000-0000-4000-8000-000000000007")
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    for suffix in ("", "-CSM"):
        item_id = f"motherboard-test{suffix.lower()}"
        catalog.put_item(
            item_id,
            ItemInput(
                category=Category.MOTHERBOARD,
                brand="Asus",
                model=f"Asus TEST-BOARD-123{suffix}",
                identifiers=[f"Asus TEST-BOARD-123{suffix}"],
            ),
        )

    manifest, _ = build_reported_specs(source_root, catalog.path)

    assert {(entry.item_id, entry.field, entry.value) for entry in manifest.specs} >= {
        ("motherboard-test", "chipset", "AMD B650"),
        ("motherboard-test", "socket", "AM5"),
    }
    assert not any(entry.item_id == "motherboard-test-csm" for entry in manifest.specs)


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


def test_cpu_oem_tray_name_matches_only_the_complete_model(tmp_path: Path) -> None:
    """Packaging suffix must not hide a CPU, or merge 3570 with 3570S."""
    source_root = tmp_path / "source"
    _write_cpu(
        source_root,
        "00000000-0000-4000-8000-000000000004",
        cores=4,
        name="Intel Core i5 3570S OEM/Tray",
        manufacturer="Intel",
        socket="LGA 1155",
    )
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    for model, suffix in (("Intel Core i5-3570S", "3570s"), ("Intel Core i5-3570", "3570")):
        item_id = f"cpu-{suffix}"
        catalog.put_item(
            item_id,
            ItemInput(category=Category.CPU, brand="Intel", model=model, identifiers=[model]),
        )
        catalog.put_source_record("catalog", "cpu.csv", len(suffix), {"core_count": 4}, item_id)

    manifest, report = build_reported_specs(source_root, catalog.path)

    sockets = [entry for entry in manifest.specs if entry.field == "socket"]
    assert [(entry.item_id, entry.value) for entry in sockets] == [("cpu-3570s", "LGA 1155")]
    assert report["matched_cpu_name_and_cores"] == 1


def test_exact_cpu_name_wins_over_packaging_variant(tmp_path: Path) -> None:
    """A second tray listing must not invalidate an existing exact CPU match."""
    source_root = tmp_path / "source"
    _write_cpu(
        source_root,
        "00000000-0000-4000-8000-000000000005",
        cores=4,
        name="Intel Core i5-3570S",
        manufacturer="Intel",
        socket="LGA 1155",
    )
    _write_cpu(
        source_root,
        "00000000-0000-4000-8000-000000000006",
        cores=4,
        name="Intel Core i5-3570S OEM/Tray",
        manufacturer="Intel",
        socket="LGA 1150",
    )
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.put_item(
        "cpu-3570s",
        ItemInput(
            category=Category.CPU,
            brand="Intel",
            model="Intel Core i5-3570S",
            identifiers=["Intel Core i5-3570S"],
        ),
    )
    catalog.put_source_record("catalog", "cpu.csv", 1, {"core_count": 4}, "cpu-3570s")

    manifest, report = build_reported_specs(source_root, catalog.path)

    assert [(row.field, row.value) for row in manifest.specs if row.field == "socket"] == [
        ("socket", "LGA 1155")
    ]
    assert report["matched_cpu_name_and_cores"] == 1


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
