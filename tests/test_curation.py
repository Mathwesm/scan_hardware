"""Manufacturer curation must retain the original disagreement as evidence."""

from __future__ import annotations

from pathlib import Path

from scan_hardware.catalog_audit import audit_catalog
from scan_hardware.catalog_import import _import_supplemental_items
from scan_hardware.core.matching import match_items
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.services.catalog import Catalog


def test_verified_gpu_memory_overrides_conflict_with_source_link(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    item_id = "gpu-bd1343be29aefce878e7e33c"
    catalog.put_item(
        item_id,
        ItemInput(
            category=Category.GPU,
            brand="MSI",
            model="GTX 1050 Ti 4GT OC",
            identifiers=["GTX 1050 Ti 4GT OC"],
        ),
    )
    catalog.put_source_record("dataset-one", "gpu.csv", 1, {"memory": 2}, item_id)
    catalog.put_source_record("dataset-two", "gpu.json", 1, {"VRAM": 4}, item_id)

    item = catalog.get_item(item_id)

    assert item is not None
    assert item.specifications["vram_gb"].status == "verified"
    assert item.specifications["vram_gb"].value == 4
    assert {e.value for e in item.specifications["vram_gb"].evidence} == {2, 4}
    assert any(
        e.source_url and "msi.com" in e.source_url for e in item.specifications["vram_gb"].evidence
    )
    assert item.image_attribution is not None
    assert item.image_attribution.creator == "ITEagle Europe - Sebastiaan Broekhoven"


def test_catalog_audit_counts_verified_and_unreviewed_images(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite3"
    catalog = Catalog(catalog_path)
    catalog.put_item(
        "cpu-d654c224708ab17877afd973",
        ItemInput(category=Category.CPU, brand="Intel", model="E8400", identifiers=["E8400"]),
    )
    catalog.put_item(
        "cpu-other",
        ItemInput(
            category=Category.CPU,
            brand="Demo",
            model="Other",
            identifiers=["OTHER"],
            image_url="https://example.com/other.jpg",
        ),
    )
    catalog.put_item(
        "motherboard-2716c8c323f0e5902e139112",
        ItemInput(
            category=Category.MOTHERBOARD,
            brand="Gigabyte",
            model="GA-Z77X-UD5H",
            identifiers=["GA-Z77X-UD5H"],
        ),
    )

    report = audit_catalog(catalog_path)

    assert report["items"] == {"cpu": 2, "motherboard": 1}
    assert report["verified"]["cpu"]["socket"] == 1
    assert report["images"] == {"reviewed": 1, "unreviewed_url": 2}


def test_supplemental_boards_match_printed_codes_without_nearby_model_confusion(
    tmp_path: Path,
) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    counts = _import_supplemental_items(catalog)
    assert counts == {"motherboard": 2, "imported_rows": 2}

    items = catalog.list_items()
    for code, expected_id, expected_socket in (
        ("A785GM-M3", "motherboard-ecs-a785gm-m3-v1", "AM2+/AM2"),
        ("G41T-MR23", "motherboard-ecs-g41t-mr23-v1", "LGA775"),
    ):
        result = match_items([code, "V:1.0"], items)
        assert result.status == "matched"
        assert [match.item.id for match in result.matches] == [expected_id]
        item = catalog.get_item(expected_id)
        assert item is not None
        assert item.image_url is None
        assert item.specifications["socket"].status == "verified"
        assert item.specifications["socket"].value == expected_socket
        assert catalog.get_source_records(expected_id)[0]["data"]["source_url"].startswith(
            "https://"
        )

    result = match_items(["A785GM-M"], items)
    assert result.status != "matched"
