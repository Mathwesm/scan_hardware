"""Local image-volume seeding and quarantine behavior."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from scan_hardware.image_seed import seed_images
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.services.catalog import Catalog


def _catalog(path: Path) -> Catalog:
    catalog = Catalog(path)
    catalog.put_item(
        "board-1",
        ItemInput(
            category=Category.MOTHERBOARD,
            brand="Demo",
            model="Board 1",
            identifiers=["BOARD-1"],
        ),
    )
    return catalog


def _picture(path: Path, color: str, size: tuple[int, int]) -> None:
    image = Image.new("RGB", size, color)
    output = BytesIO()
    image.save(output, format="PNG")
    path.write_bytes(output.getvalue())


def test_seed_gallery_is_idempotent_and_keeps_front_primary(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path / "catalog.sqlite3")
    source = tmp_path / "source"
    source.mkdir()
    _picture(source / "front.png", "blue", (900, 900))
    _picture(source / "back.png", "red", (640, 640))
    manifest = source / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "images": [
                    {"item_id": "board-1", "path": "front.png", "view": "front"},
                    {"item_id": "board-1", "path": "back.png", "view": "back"},
                ]
            }
        ),
        encoding="utf-8",
    )

    first = seed_images(manifest, catalog, tmp_path / "images", tmp_path / "reports", 8_000_000)
    second = seed_images(manifest, catalog, tmp_path / "images", tmp_path / "reports", 8_000_000)

    assert first == second == {"imported": 2, "total": 2}
    assert [(entry["view"], entry["is_primary"]) for entry in catalog.list_images("board-1")] == [
        ("front", 1),
        ("back", 0),
    ]
    assert len(list((tmp_path / "images").iterdir())) == 2


def test_seed_rejects_unsafe_path_without_losing_valid_image(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path / "catalog.sqlite3")
    source = tmp_path / "source"
    source.mkdir()
    _picture(source / "front.png", "blue", (900, 900))
    manifest = source / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "images": [
                    {"item_id": "board-1", "path": "../outside.png", "view": "front"},
                    {"item_id": "board-1", "path": "front.png", "view": "front"},
                ]
            }
        ),
        encoding="utf-8",
    )

    report = seed_images(manifest, catalog, tmp_path / "images", tmp_path / "reports", 8_000_000)

    assert report == {"rejected": 1, "imported": 1, "total": 2}
    assert len(catalog.list_images("board-1")) == 1


def test_seed_fails_when_all_images_are_rejected(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path / "catalog.sqlite3")
    source = tmp_path / "source"
    source.mkdir()
    manifest = source / "manifest.json"
    manifest.write_text(
        json.dumps({"images": [{"item_id": "board-1", "path": "missing.png", "view": "front"}]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="No manifest images could be imported"):
        seed_images(manifest, catalog, tmp_path / "images", tmp_path / "reports", 8_000_000)
