"""Category browsing keeps mobile tab results flat and paginated."""

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from scan_hardware.api import create_app
from scan_hardware.config import Settings
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.services.catalog import Catalog


def test_category_catalog_pages_only_selected_hardware(tmp_path: Path) -> None:
    """Browsing one tab must not mix categories or return nested specification maps."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    entries = (
        ("board-1", Category.MOTHERBOARD, "Asus", "PRIME B550M-A"),
        ("board-2", Category.MOTHERBOARD, "Gigabyte", "B550M DS3H"),
        ("cpu-1", Category.CPU, "AMD", "Ryzen 5 5600X"),
        ("ram-1", Category.RAM, "Corsair", "Vengeance 16GB"),
        ("gpu-1", Category.GPU, "MSI", "RTX 4070"),
    )
    for item_id, category, brand, model in entries:
        catalog.put_item(
            item_id,
            ItemInput(category=category, brand=brand, model=model, identifiers=[item_id]),
        )
    catalog.put_source_record(
        "fixture",
        "board.csv",
        1,
        {
            "socket": "AM4",
            "sata_slots": 6,
            "pcie_slots": 2,
        },
        "board-1",
    )
    client = TestClient(create_app(config=Settings(image_dir=tmp_path / "images"), catalog=catalog))

    first = client.get("/catalog/motherboard?limit=1&offset=0")
    second = client.get("/catalog/motherboard?limit=1&offset=1")

    assert first.status_code == second.status_code == 200
    assert first.json()["category"] == "motherboard"
    assert first.json()["total"] == second.json()["total"] == 2
    assert [first.json()["items"][0]["id"], second.json()["items"][0]["id"]] == [
        "board-1",
        "board-2",
    ]
    assert first.json()["items"][0]["socket"] == "AM4"
    assert first.json()["items"][0]["sata_slots"] == 6
    assert first.json()["items"][0]["pcie_slots"] == 2
    assert client.get("/specs/board-1").json()["specs"]["sata_slots"]["value"] == 6
    lookup = client.post("/lookup", json={"text": "board-1"})
    assert lookup.status_code == 200
    assert lookup.json()["matches"][0]["pcie_slots"] == 2
    assert "specs" not in first.json()["items"][0]
    assert "match_score" not in first.json()["items"][0]
    assert client.get("/catalog/cpu").json()["items"][0]["id"] == "cpu-1"
    assert client.get("/catalog/ram").json()["items"][0]["id"] == "ram-1"
    assert client.get("/catalog/gpu").json()["items"][0]["id"] == "gpu-1"


def test_category_catalog_validates_category_and_pagination(tmp_path: Path) -> None:
    """Invalid tabs and unbounded pages must fail without reading the whole catalog."""
    client = TestClient(
        create_app(
            config=Settings(image_dir=tmp_path / "images"),
            catalog=Catalog(tmp_path / "catalog.sqlite3"),
        )
    )

    assert client.get("/catalog/cpu").json() == {
        "category": "cpu",
        "total": 0,
        "limit": 20,
        "offset": 0,
        "items": [],
    }
    assert client.get("/catalog/unknown").status_code == 422
    assert client.get("/catalog/cpu?limit=0").status_code == 422
    assert client.get("/catalog/cpu?limit=101").status_code == 422
    assert client.get("/catalog/cpu?offset=-1").status_code == 422


def test_category_catalog_respects_api_key(tmp_path: Path) -> None:
    """Mobile catalog browsing must use the same deployment authentication as scans."""
    key = "x" * 32
    client = TestClient(
        create_app(
            config=Settings(
                image_dir=tmp_path / "images",
                require_api_key=True,
                api_key=SecretStr(key),
            ),
            catalog=Catalog(tmp_path / "catalog.sqlite3"),
        )
    )

    assert client.get("/catalog/cpu").status_code == 401
    assert client.get("/catalog/cpu", headers={"X-API-Key": key}).status_code == 200
