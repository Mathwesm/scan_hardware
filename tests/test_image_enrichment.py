"""Exact product-image enrichment from a cached public export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scan_hardware.image_enrichment import ImageSourceError, build_manifest, catalog_images
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.services.catalog import Catalog


def _feed_row(
    category: str,
    name: str,
    brand: str,
    image_url: str,
    source_id: str,
    chipset: str | None = None,
) -> dict[str, object]:
    """Build a source row with the same fields as the public JSONL export."""
    return {
        "category": category,
        "name": name,
        "brand": brand,
        "image_url": image_url,
        "url": f"https://example.org/product/{source_id}",
        "source_id": source_id,
        "specs": {"Chipset": chipset} if chipset else {},
    }


def test_image_feed_requires_exact_gpu_chipset_and_rejects_ambiguous_urls(
    tmp_path: Path,
) -> None:
    """A similar name or two possible photos must never select the wrong SKU."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    products = [
        ("gpu-4070", Category.GPU, "Acme Model X", "GeForce RTX 4070"),
        ("gpu-4080", Category.GPU, "Acme Model X", "GeForce RTX 4080"),
        ("gpu-unknown", Category.GPU, "Acme Missing Chipset", None),
        ("cpu-clear", Category.CPU, "Gamma Q1234", None),
        ("cpu-ambiguous", Category.CPU, "Gamma Q5678", None),
        ("board-placeholder", Category.MOTHERBOARD, "Beta X570 Alpha", None),
    ]
    for row_number, (item_id, category, name, chipset) in enumerate(products, start=1):
        catalog.put_item(
            item_id,
            ItemInput(
                category=category,
                brand=name.split()[0],
                model=name,
                identifiers=[f"PART-{row_number:04d}"],
            ),
        )
        raw = {"name": name}
        if chipset:
            raw["chipset"] = chipset
        catalog.put_source_record("fixture", "parts.json", row_number, raw, item_id)
    source = tmp_path / "source.jsonl"
    rows = [
        _feed_row(
            "video-card",
            "Acme Model X",
            "Acme",
            "https://img.test/4070.jpg",
            "1",
            "GeForce RTX 4070",
        ),
        _feed_row(
            "video-card",
            "Acme Model X",
            "Acme",
            "https://img.test/4080.jpg",
            "2",
            "GeForce RTX 4080",
        ),
        _feed_row(
            "video-card", "Acme Missing Chipset", "Acme", "https://img.test/unknown.jpg", "7"
        ),
        _feed_row("cpu", "Gamma Q1234", "Gamma", "https://img.test/cpu.jpg", "3"),
        _feed_row("cpu", "Gamma Q5678", "Gamma", "https://img.test/a.jpg", "4"),
        _feed_row("cpu", "Gamma Q5678", "Gamma", "https://img.test/b.jpg", "5"),
        _feed_row("motherboard", "Beta X570 Alpha", "Beta", "https://img.test/no-image.png", "6"),
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    manifest, report = build_manifest(source, catalog.path, minimums={})

    selected = {image.item_id: str(image.image_url) for image in manifest.images}
    assert selected == {
        "gpu-4070": "https://img.test/4070.jpg",
        "gpu-4080": "https://img.test/4080.jpg",
        "cpu-clear": "https://img.test/cpu.jpg",
    }
    assert report["catalog"]["ambiguous_cpu"] == 1
    assert report["catalog"]["no_exact_match_motherboard"] == 1
    assert report["catalog"]["no_exact_match_gpu"] == 1
    assert report["feed_rejected"]["placeholder"] == 1
    assert report["feed_rejected"]["missing_chipset"] == 1


def test_image_feed_coverage_gate_rejects_incomplete_catalog(tmp_path: Path) -> None:
    """A truncated export cannot silently replace the packaged image set."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    source = tmp_path / "empty.jsonl"
    source.write_text("", encoding="utf-8")

    with pytest.raises(ImageSourceError, match="Image coverage gate failed"):
        build_manifest(source, catalog.path)


def test_cpu_with_boxed_and_single_tray_photo_uses_exact_tray_listing(tmp_path: Path) -> None:
    """A boxed image must not make an exact CPU tray photo ambiguous."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.put_item(
        "cpu-3600",
        ItemInput(
            category=Category.CPU,
            brand="AMD",
            model="AMD Ryzen 5 3600",
            identifiers=["RYZEN-3600"],
        ),
    )
    catalog.put_source_record("fixture", "parts.json", 1, {"name": "AMD Ryzen 5 3600"}, "cpu-3600")
    boxed = _feed_row("cpu", "AMD Ryzen 5 3600", "AMD", "https://img.test/box.jpg", "BOX")
    tray = _feed_row("cpu", "AMD Ryzen 5 3600", "AMD", "https://img.test/tray.jpg", "TRAY")
    tray["url"] = "https://shop.test/product/TRAY/amd-ryzen-5-3600-oemtray-processor"
    source = tmp_path / "source.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in [boxed, tray]), encoding="utf-8")

    manifest, report = build_manifest(source, catalog.path, minimums={})

    assert [(image.item_id, str(image.image_url)) for image in manifest.images] == [
        ("cpu-3600", "https://img.test/tray.jpg")
    ]
    assert report["catalog"]["added_cpu"] == 1


def test_cpu_with_two_tray_photos_remains_ambiguous(tmp_path: Path) -> None:
    """Two tray listings still need a model-specific manual image review."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.put_item(
        "cpu-3600",
        ItemInput(
            category=Category.CPU,
            brand="AMD",
            model="AMD Ryzen 5 3600",
            identifiers=["RYZEN-3600"],
        ),
    )
    catalog.put_source_record("fixture", "parts.json", 1, {"name": "AMD Ryzen 5 3600"}, "cpu-3600")
    rows = []
    for source_id in ("TRAY1", "TRAY2"):
        row = _feed_row(
            "cpu", "AMD Ryzen 5 3600", "AMD", f"https://img.test/{source_id}.jpg", source_id
        )
        row["url"] = f"https://shop.test/product/{source_id}/amd-ryzen-5-3600-oemtray"
        rows.append(row)
    source = tmp_path / "source.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    manifest, report = build_manifest(source, catalog.path, minimums={})

    assert manifest.images == []
    assert report["catalog"]["ambiguous_cpu"] == 1


@pytest.mark.parametrize(
    ("category", "source_category"),
    [
        (Category.RAM, "memory"),
        (Category.PSU, "power-supply"),
        (Category.CASE, "case"),
        (Category.COOLER, "cpu-cooler"),
        (Category.STORAGE, "internal-hard-drive"),
    ],
)
def test_exact_product_tag_recovers_images_for_other_categories(
    tmp_path: Path, category: Category, source_category: str
) -> None:
    """A matching listing ID selects its image even if display names differ."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.put_item(
        "part-1234",
        ItemInput(
            category=category,
            brand="Acme",
            model="Acme Long Display Name (AX-1234)",
            identifiers=["AX-1234"],
        ),
    )
    catalog.put_source_record(
        "fixture",
        "parts.json",
        1,
        {"name": "Acme Long Display Name", "url": "https://shop.test/product/EXACT1/acme"},
        "part-1234",
    )
    matching = _feed_row(
        source_category, "Acme Short Name", "Acme", "https://img.test/exact.jpg", "EXACT1"
    )
    wrong_brand = _feed_row(
        source_category, "Other Brand", "Other", "https://img.test/wrong.jpg", "EXACT1"
    )
    source = tmp_path / "source.jsonl"
    source.write_text(
        "\n".join(json.dumps(row) for row in [matching, wrong_brand]), encoding="utf-8"
    )

    manifest, _ = build_manifest(source, catalog.path, minimums={})

    assert [(image.item_id, str(image.image_url)) for image in manifest.images] == [
        ("part-1234", "https://img.test/exact.jpg")
    ]


def test_packaged_image_disappears_if_catalog_model_is_replaced(tmp_path: Path) -> None:
    """A reused item ID must not retain a photograph of a different model."""
    image = next(iter(catalog_images().values()))
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.put_item(
        image.item_id,
        ItemInput(
            category=image.category,
            brand=image.model.split()[0],
            model=image.model,
            identifiers=["ORIGINAL-MODEL"],
        ),
    )
    assert str(catalog.get_item(image.item_id).image_url) == str(image.image_url)

    catalog.put_item(
        image.item_id,
        ItemInput(
            category=image.category,
            brand="Different",
            model="Different hardware revision",
            identifiers=["REPLACED-MODEL"],
        ),
    )
    assert catalog.get_item(image.item_id).image_url is None
