"""Deployment readiness and reproducible photo evaluation behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scan_hardware import bootstrap
from scan_hardware.bootstrap import prepare_catalog
from scan_hardware.config import Settings
from scan_hardware.models.item import Category, Item, ItemInput, Match, ScanResponse, ScanResult
from scan_hardware.photo_validation import PhotoCase, evaluate_case
from scan_hardware.services.catalog import Catalog


def test_bootstrap_reuses_a_nonempty_published_catalog(tmp_path: Path) -> None:
    catalog_path = tmp_path / "processed" / "first" / "catalog.sqlite3"
    catalog = Catalog(catalog_path)
    catalog.put_item(
        "cpu-1",
        ItemInput(category=Category.CPU, brand="Intel", model="E8400", identifiers=["E8400"]),
    )
    pointer = tmp_path / "latest.json"
    pointer.write_text(json.dumps({"catalog_path": str(catalog_path)}), encoding="utf-8")

    assert prepare_catalog(Settings(catalog_latest_pointer=pointer)) == catalog_path


def test_bootstrap_fails_when_an_archive_is_missing(tmp_path: Path) -> None:
    config = Settings(
        catalog_latest_pointer=tmp_path / "latest.json",
        import_rohit_path=tmp_path / "missing-rohit.zip",
        import_warcoder_path=tmp_path / "missing-warcoder.zip",
    )

    with pytest.raises(FileNotFoundError, match="Catalog archive is missing"):
        prepare_catalog(config)


def test_bootstrap_rebuilds_old_catalog_when_ram_archives_are_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_path = tmp_path / "processed" / "old" / "catalog.sqlite3"
    Catalog(old_path).put_item(
        "cpu-1",
        ItemInput(category=Category.CPU, brand="Intel", model="E8400", identifiers=["E8400"]),
    )
    pointer = tmp_path / "latest.json"
    pointer.write_text(json.dumps({"catalog_path": str(old_path)}), encoding="utf-8")
    new_path = tmp_path / "processed" / "new" / "catalog.sqlite3"

    def publish_ram(_rohit: Path, _warcoder: Path, _root: Path, output: Path) -> dict[str, int]:
        catalog = Catalog(new_path)
        catalog.put_item(
            "ram-1",
            ItemInput(
                category=Category.RAM,
                brand="Demo",
                model="Demo RAM Kit",
                identifiers=["RAM-KIT-16"],
            ),
        )
        output.write_text(json.dumps({"catalog_path": str(new_path)}), encoding="utf-8")
        return {"ram": 1}

    monkeypatch.setattr(bootstrap, "import_archives", publish_ram)
    config = Settings(
        catalog_latest_pointer=pointer,
        import_rohit_path=tmp_path / "rohit.zip",
        import_warcoder_path=tmp_path / "warcoder.zip",
    )

    assert prepare_catalog(config) == new_path
    assert Catalog(old_path).count_category(Category.RAM) == 0
    assert Catalog(new_path).count_category(Category.RAM) == 1


def test_photo_evaluation_does_not_promote_suggestion_to_exact() -> None:
    item = Item(
        id="motherboard-1",
        category=Category.MOTHERBOARD,
        brand="ASRock",
        model="A320M-DVS R4.0",
        identifiers=["A320M-DVS R4.0"],
    )
    result = ScanResult(
        status="suggestions",
        detected_text=["A320M-DVS"],
        matches=[
            Match(
                item=item,
                matched_identifier="A320M-DVS R4.0",
                observed_text="A320M-DVS",
                score=0.93,
                is_exact=False,
            )
        ],
    )
    case = PhotoCase(
        name="unreadable revision",
        image=Path("board.jpg"),
        category="motherboard",
        expected_status="matched",
        expected_item_id="motherboard-1",
    )

    assert not evaluate_case(case, ScanResponse.from_result(result), 1.2, "test-digest").passed
