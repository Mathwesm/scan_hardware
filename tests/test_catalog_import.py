"""Regression tests for conservative Kaggle catalog merging and provenance."""

from __future__ import annotations

from pathlib import Path

import pytest

from scan_hardware.catalog_import import (
    InvalidCatalogError,
    SourceRow,
    _build_groups,
    _import_groups,
    _publish,
)
from scan_hardware.core.matching import match_items
from scan_hardware.models.item import Category
from scan_hardware.services.catalog import Catalog


def test_exact_model_join_attaches_image_and_retains_original_columns(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    warcoder = [
        (
            Category.MOTHERBOARD,
            SourceRow(
                "warcoder/pc-parts",
                "dataset/motherboard.json",
                1,
                {"name": "ASRock B365M-HDV", "socket": "LGA1151", "memory_slots": 2},
            ),
        )
    ]
    rohit = [
        (
            Category.MOTHERBOARD,
            SourceRow(
                "rohitmit98/pc-parts-by-type",
                "Motherboard.csv",
                1,
                {
                    "name": "ASRock B365M-HDV Micro ATX LGA1151 Motherboard (B365M-HDV)",
                    "image": "https://example.com/board.jpg",
                    "size": "ATX",
                },
            ),
        )
    ]

    groups = _build_groups(warcoder, rohit)
    first_counts = _import_groups(catalog, groups)
    second_counts = _import_groups(catalog, groups)
    items = catalog.list_items()

    assert first_counts == second_counts
    assert len(items) == 1
    assert str(items[0].image_url) == "https://example.com/board.jpg"
    assert match_items(["B365M-HDV"], items).status == "matched"
    source_rows = catalog.get_source_records(items[0].id)
    assert len(source_rows) == 2
    assert source_rows[0]["data"]["size"] == "ATX"
    assert source_rows[1]["data"]["memory_slots"] == 2


def test_different_board_revision_does_not_inherit_wrong_image(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    warcoder = [
        (
            Category.MOTHERBOARD,
            SourceRow(
                "warcoder/pc-parts",
                "dataset/motherboard.json",
                1,
                {"name": "ASRock B365M-HDV R2.0"},
            ),
        )
    ]
    rohit = [
        (
            Category.MOTHERBOARD,
            SourceRow(
                "rohitmit98/pc-parts-by-type",
                "Motherboard.csv",
                1,
                {
                    "name": "ASRock B365M-HDV Micro ATX Motherboard (B365M-HDV)",
                    "image": "https://example.com/original.jpg",
                },
            ),
        )
    ]

    _import_groups(catalog, _build_groups(warcoder, rohit))
    items = catalog.list_items()

    assert len(items) == 2
    revised = next(item for item in items if item.model == "ASRock B365M-HDV R2.0")
    assert revised.image_url is None


def test_duplicate_normalized_alias_does_not_reject_product(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    warcoder = [
        (
            Category.CPU,
            SourceRow("warcoder/pc-parts", "dataset/cpu.json", 1, {"name": "Intel Core i3-7350K"}),
        )
    ]
    rohit = [
        (
            Category.CPU,
            SourceRow(
                "rohitmit98/pc-parts-by-type",
                "CPU.csv",
                1,
                {
                    "name": "Intel Core i3-7350K 4.2 GHz Processor (Intel Core i3 7350K)",
                    "image": "https://example.com/cpu.jpg",
                },
            ),
        )
    ]

    counts = _import_groups(catalog, _build_groups(warcoder, rohit))

    assert counts["imported_rows"] == 2
    assert counts["items_with_image_url"] == 1
    assert len(catalog.list_items()) == 1


def test_placeholder_image_is_not_published_as_product_photo(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    rohit = [
        (
            Category.GPU,
            SourceRow(
                "rohitmit98/pc-parts-by-type",
                "GPU.csv",
                1,
                {
                    "name": "MSI GeForce GTX 1050 Video Card (GTX-1050-MSI)",
                    "image": "https://static/forever/img/no-image.png",
                },
            ),
        )
    ]

    counts = _import_groups(catalog, _build_groups([], rohit))

    assert counts.get("items_with_image_url", 0) == 0
    assert catalog.list_items()[0].image_url is None
    assert catalog.get_source_records(catalog.list_items()[0].id)[0]["data"]["image"] == (
        "https://static/forever/img/no-image.png"
    )


def test_failed_quality_gate_keeps_previous_published_catalog(tmp_path: Path) -> None:
    pointer = tmp_path / "latest.json"
    pointer.write_text('{"catalog_path": "previous.sqlite3"}', encoding="utf-8")

    with pytest.raises(InvalidCatalogError, match="Catalog quality gate failed"):
        _publish(tmp_path / "partial.sqlite3", pointer, {"cpu": 1, "rejected_rows": 0})

    assert pointer.read_text(encoding="utf-8") == '{"catalog_path": "previous.sqlite3"}'


def test_gpu_models_shared_across_chipsets_stay_distinct(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    warcoder = [
        (
            Category.GPU,
            SourceRow(
                "warcoder/pc-parts",
                "dataset/video-card.json",
                1,
                {"name": "Asus TUF GAMING", "chipset": "GeForce RTX 4070 Ti"},
            ),
        ),
        (
            Category.GPU,
            SourceRow(
                "warcoder/pc-parts",
                "dataset/video-card.json",
                2,
                {"name": "Asus TUF GAMING", "chipset": "GeForce RTX 4080"},
            ),
        ),
    ]

    _import_groups(catalog, _build_groups(warcoder, []))
    items = catalog.list_items()

    assert len(items) == 2
    assert {item.model for item in items} == {
        "Asus TUF GAMING GeForce RTX 4070 Ti",
        "Asus TUF GAMING GeForce RTX 4080",
    }
    result = match_items(["Asus TUF GAMING GeForce RTX 4080"], items)
    assert result.matches[0].item.model == "Asus TUF GAMING GeForce RTX 4080"


def test_gpu_image_joins_only_matching_chipset(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    warcoder = [
        (
            Category.GPU,
            SourceRow(
                "warcoder/pc-parts",
                "dataset/video-card.json",
                1,
                {"name": "Asus TUF GAMING", "chipset": "GeForce RTX 4070 Ti"},
            ),
        ),
        (
            Category.GPU,
            SourceRow(
                "warcoder/pc-parts",
                "dataset/video-card.json",
                2,
                {"name": "Asus TUF GAMING", "chipset": "GeForce RTX 4080"},
            ),
        ),
    ]
    rohit = [
        (
            Category.GPU,
            SourceRow(
                "rohitmit98/pc-parts-by-type",
                "GPU.csv",
                1,
                {
                    "name": "Asus TUF GAMING GeForce RTX 4080 Video Card (TUF GAMING)",
                    "image": "https://example.com/4080.jpg",
                },
            ),
        )
    ]

    _import_groups(catalog, _build_groups(warcoder, rohit))
    images = {
        item.model: str(item.image_url) if item.image_url else None for item in catalog.list_items()
    }

    assert images["Asus TUF GAMING GeForce RTX 4070 Ti"] is None
    assert images["Asus TUF GAMING GeForce RTX 4080"] == "https://example.com/4080.jpg"
