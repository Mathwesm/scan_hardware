"""Socket relationships include only source-backed, unambiguous candidates."""

from pathlib import Path

from fastapi.testclient import TestClient

from scan_hardware.api import create_app
from scan_hardware.config import Settings
from scan_hardware.services.catalog import Catalog


def _add_item(catalog: Catalog, item_id: str, category: str, socket: str | None) -> None:
    """Create a test record with an optional reported socket."""
    from scan_hardware.models.item import ItemInput

    catalog.put_item(
        item_id,
        ItemInput.model_validate(
            {
                "category": category,
                "brand": "Example",
                "model": item_id,
                "identifiers": [item_id],
            }
        ),
    )
    if socket is not None:
        catalog.put_source_record("fixture", f"{item_id}.csv", 1, {"socket": socket}, item_id)


def test_socket_relationships_are_bidirectional_paginated_and_exact(tmp_path: Path) -> None:
    """Prevent fuzzy sockets, missing values, and pagination drift."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    _add_item(catalog, "board-am4", "motherboard", "AM4")
    _add_item(catalog, "board-am5", "motherboard", "AM5")
    _add_item(catalog, "cpu-am4-a", "cpu", "AM4")
    _add_item(catalog, "cpu-am4-b", "cpu", "AM4")
    _add_item(catalog, "cpu-am5", "cpu", "AM5")
    _add_item(catalog, "cpu-unknown", "cpu", None)
    client = TestClient(create_app(config=Settings(image_dir=tmp_path / "images"), catalog=catalog))

    first = client.get("/specs/board-am4/socket-related?limit=1")
    second = client.get("/specs/board-am4/socket-related?limit=1&offset=1")
    reverse = client.get("/specs/cpu-am4-a/socket-related")

    assert first.status_code == second.status_code == reverse.status_code == 200
    assert first.json()["relation"] == "same_socket"
    assert first.json()["total"] == second.json()["total"] == 2
    assert [first.json()["matches"][0]["id"], second.json()["matches"][0]["id"]] == [
        "cpu-am4-a",
        "cpu-am4-b",
    ]
    assert [candidate["id"] for candidate in reverse.json()["matches"]] == ["board-am4"]


def test_socket_relationships_exclude_conflicts_and_missing_socket(tmp_path: Path) -> None:
    """A conflicted or absent source value must not imply compatibility."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    _add_item(catalog, "board-am4", "motherboard", "AM4")
    _add_item(catalog, "board-unknown", "motherboard", None)
    _add_item(catalog, "cpu-conflict", "cpu", "AM4")
    catalog.put_source_record("other", "other.csv", 1, {"socket": "AM5"}, "cpu-conflict")
    client = TestClient(create_app(config=Settings(image_dir=tmp_path / "images"), catalog=catalog))

    assert client.get("/specs/board-am4/socket-related").json()["matches"] == []
    assert client.get("/specs/board-unknown/socket-related").json() == {
        "socket": None,
        "relation": "same_socket",
        "total": 0,
        "matches": [],
        "note": "Same socket does not confirm chipset, BIOS, or generation support.",
    }
    assert client.get("/specs/missing/socket-related").status_code == 404
    assert client.get("/specs/board-am4/socket-related?limit=101").status_code == 422


def test_socket_relationships_ignore_source_spacing(tmp_path: Path) -> None:
    """A curated 'LGA 1155' CPU must match a dataset 'LGA1155' board."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    _add_item(catalog, "board-lga1155", "motherboard", "LGA1155")
    _add_item(catalog, "cpu-lga1155", "cpu", "LGA 1155")
    client = TestClient(create_app(config=Settings(image_dir=tmp_path / "images"), catalog=catalog))

    result = client.get("/specs/board-lga1155/socket-related").json()

    assert result["socket"] == "LGA1155"
    assert [entry["id"] for entry in result["matches"]] == ["cpu-lga1155"]
