"""Exact manufacturer identifiers determine source color joins."""

from __future__ import annotations

import json
from pathlib import Path

from scan_hardware.models.item import Category, ItemInput
from scan_hardware.reported_color_import import build_reported_manifest
from scan_hardware.services.catalog import Catalog


def _source(
    root: Path, category: str, source_id: str, brand: str, part_number: str, color: list[str]
) -> None:
    """Write one minimal OpenDB record to a temporary checkout."""
    folder = root / "open-db" / category
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{source_id}.json").write_text(
        json.dumps(
            {
                "opendb_id": source_id,
                "metadata": {"manufacturer": brand, "part_numbers": [part_number]},
                "color": color,
            }
        ),
        encoding="utf-8",
    )


def test_import_accepts_unique_mpn_and_rejects_ambiguous_or_wrong_brand(tmp_path: Path) -> None:
    """A reused MPN must never assign one variant's color to another."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    for item_id, brand, identifier in (
        ("gpu-exact", "Asus", "TUF-RTX3060-8G"),
        ("gpu-ambiguous", "MSI", "RTX3060-GAMING-12G"),
        ("gpu-wrong-brand", "Gigabyte", "RX7600-SWFT-8G"),
    ):
        catalog.put_item(
            item_id,
            ItemInput(
                category=Category.GPU,
                brand=brand,
                model=f"{brand} {identifier}",
                identifiers=[identifier],
            ),
        )
    _source(
        tmp_path,
        "GPU",
        "11111111-1111-1111-1111-111111111111",
        "Asus",
        "TUF-RTX3060-8G",
        ["BLACK", "GREY"],
    )
    _source(
        tmp_path,
        "GPU",
        "22222222-2222-2222-2222-222222222222",
        "MSI",
        "RTX3060-GAMING-12G",
        ["RED"],
    )
    _source(
        tmp_path,
        "GPU",
        "33333333-3333-3333-3333-333333333333",
        "MSI",
        "RTX3060-GAMING-12G",
        ["BLUE"],
    )
    _source(
        tmp_path,
        "GPU",
        "44444444-4444-4444-4444-444444444444",
        "XFX",
        "RX7600-SWFT-8G",
        ["BLACK"],
    )

    manifest, counts = build_reported_manifest(tmp_path, catalog.path)

    assert [(entry.item_id, entry.color) for entry in manifest.colors] == [
        ("gpu-exact", "Black / Gray")
    ]
    assert counts["selected"] == 1
    assert counts["ambiguous"] == 1
    assert counts["no_exact_part_number"] == 1


def test_import_does_not_override_existing_catalog_color(tmp_path: Path) -> None:
    """Source-backed catalog values retain priority over a second dataset."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.put_item(
        "gpu-existing",
        ItemInput(
            category=Category.GPU,
            brand="Asus",
            model="Asus TUF 3060",
            identifiers=["TUF-RTX3060-8G"],
        ),
    )
    catalog.put_source_record("first-source", "gpu.json", 1, {"color": "White"}, "gpu-existing")
    _source(
        tmp_path,
        "GPU",
        "11111111-1111-1111-1111-111111111111",
        "Asus",
        "TUF-RTX3060-8G",
        ["BLACK"],
    )

    manifest, counts = build_reported_manifest(tmp_path, catalog.path)

    assert manifest.colors == []
    assert counts["existing_catalog_color"] == 1
