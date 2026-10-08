"""Persistence and conflict tests for the local SQLite catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from scan_hardware.models.item import Category, ItemInput
from scan_hardware.services.catalog import Catalog, IdentifierConflictError


def _item(identifier: str, model: str = "Demo board") -> ItemInput:
    return ItemInput(
        category=Category.MOTHERBOARD,
        brand="Demo",
        model=model,
        identifiers=[identifier],
    )


def test_put_item_is_idempotent_and_persists_across_connections(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")

    first = catalog.put_item("board-1", _item("B550-F"))
    second = catalog.put_item("board-1", _item("B550-F"))
    reopened = Catalog(tmp_path / "catalog.sqlite3")

    assert first == second
    assert reopened.get_item("board-1") == first
    assert len(reopened.list_items()) == 1


def test_identifier_conflict_rolls_back_new_item(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.put_item("board-1", _item("B550-F"))

    with pytest.raises(IdentifierConflictError, match="already belongs"):
        catalog.put_item("board-2", _item("B550 F"))

    assert catalog.get_item("board-2") is None
    assert catalog.get_item("board-1") is not None


def test_identifier_conflict_rolls_back_existing_item_update(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.put_item("board-1", _item("B550-F"))
    original = catalog.put_item("board-2", _item("X570-A"))

    with pytest.raises(IdentifierConflictError, match="already belongs"):
        catalog.put_item("board-2", _item("B550 F", model="Changed"))

    assert catalog.get_item("board-2") == original
