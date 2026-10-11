"""Manufacturer curation must retain the original disagreement as evidence."""

from __future__ import annotations

from pathlib import Path

from scan_hardware.catalog_audit import audit_catalog
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

    report = audit_catalog(catalog_path)

    assert report["items"] == {"cpu": 2}
    assert report["verified"]["cpu"]["socket"] == 1
    assert report["images"] == {"reviewed": 1, "unreviewed_url": 1}
