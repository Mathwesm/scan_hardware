"""Local-image color enrichment preserves identity and rejects uncertainty."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from scan_hardware.color_batch import build_manifest, merge_manifests
from scan_hardware.curation import EstimatedColor, EstimatedColorManifest
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.services.catalog import Catalog


def _colored_image(path: Path, color: str) -> None:
    """Save a visible component on a white backdrop under tmp_path."""
    image = Image.new("RGB", (300, 300), "white")
    ImageDraw.Draw(image).rectangle((30, 70, 220, 250), fill=color)
    output = BytesIO()
    image.save(output, format="PNG")
    path.write_bytes(output.getvalue())


def _catalog(path: Path) -> Catalog:
    """Create one board without a source color."""
    catalog = Catalog(path)
    catalog.put_item(
        "board-1",
        ItemInput(
            category=Category.MOTHERBOARD,
            brand="Example",
            model="Example B550",
            identifiers=["B550-EXAMPLE"],
        ),
    )
    return catalog


def test_batch_uses_local_image_and_quarantines_missing_file(tmp_path: Path) -> None:
    _catalog(tmp_path / "catalog.sqlite3")
    _colored_image(tmp_path / "board.png", "green")
    source = tmp_path / "images.json"
    source.write_text(
        json.dumps(
            {
                "images": [
                    {"item_id": "board-1", "path": "board.png"},
                    {"item_id": "missing-board", "path": "board.png"},
                    {"item_id": "board-1", "path": "absent.png"},
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest, counts = build_manifest(source, tmp_path / "catalog.sqlite3")

    assert len(manifest.colors) == 1
    assert manifest.colors[0].color == "Green"
    assert counts == {"unknown_or_cpu": 1, "unreadable_image": 1, "selected": 1}


def test_batch_rejects_disagreeing_photos_of_same_board(tmp_path: Path) -> None:
    _catalog(tmp_path / "catalog.sqlite3")
    _colored_image(tmp_path / "green.png", "green")
    _colored_image(tmp_path / "red.png", "red")
    source = tmp_path / "images.json"
    source.write_text(
        json.dumps(
            {
                "images": [
                    {"item_id": "board-1", "path": "green.png"},
                    {"item_id": "board-1", "path": "red.png"},
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest, counts = build_manifest(source, tmp_path / "catalog.sqlite3")

    assert manifest.colors == []
    assert counts["conflicting_photos"] == 1


def test_merge_keeps_other_items_and_quarantines_changed_color() -> None:
    existing = EstimatedColorManifest(
        colors=[
            EstimatedColor(
                item_id="board-1",
                category=Category.MOTHERBOARD,
                model="Example B550",
                color="Green",
            ),
            EstimatedColor(
                item_id="board-2",
                category=Category.MOTHERBOARD,
                model="Example X570",
                color="Black",
            ),
        ]
    )
    incoming = EstimatedColorManifest(
        colors=[
            EstimatedColor(
                item_id="board-1",
                category=Category.MOTHERBOARD,
                model="Example B550",
                color="Red",
            )
        ]
    )

    merged = merge_manifests(existing, incoming)

    assert [entry.item_id for entry in merged.colors] == ["board-2"]
