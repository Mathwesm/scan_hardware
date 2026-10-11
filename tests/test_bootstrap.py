"""Deployment readiness and reproducible photo evaluation behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scan_hardware.bootstrap import prepare_catalog
from scan_hardware.config import Settings
from scan_hardware.models.item import Category, Item, ItemInput, Match, ScanResult
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

    assert not evaluate_case(case, result, 1.2, "test-digest").passed
