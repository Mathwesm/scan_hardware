"""PostgreSQL migration and runtime integration tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from scan_hardware.api import create_app
from scan_hardware.catalog_migrate import migrate_catalog
from scan_hardware.config import Settings
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.models.price import PriceOffer
from scan_hardware.services.catalog import Catalog


def _add_psu_source(source: Catalog) -> None:
    """Stage a new PSU category for the migration regression case."""
    source.put_item(
        "psu-test-1",
        ItemInput(
            category=Category.PSU,
            brand="Demo",
            model="Demo 750 W 80+ Gold Fully Modular Power Supply",
            identifiers=["DEMO-PSU-750"],
        ),
    )
    source.put_source_record(
        "test",
        "PSU.csv",
        1,
        {"name": "Demo 750 W 80+ Gold Fully Modular Power Supply", "power": "750"},
        "psu-test-1",
    )


def test_migration_preserves_records_and_supports_runtime_queries(tmp_path: Path) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PostgreSQL integration URL is not configured")
    source_path = tmp_path / "catalog.sqlite3"
    source = Catalog(source_path)
    source.put_item(
        "motherboard-test-1",
        ItemInput(
            category=Category.MOTHERBOARD,
            brand="Demo",
            model="Demo B550-F",
            identifiers=["B550-F"],
        ),
    )
    source.put_source_record("test", "boards.csv", 1, {"socket": "AM4"}, "motherboard-test-1")
    source.put_source_record("test", "boards.csv", 2, {"model": "bad"}, None, "unknown")
    source.add_image("motherboard-test-1", "a" * 64 + ".jpg", "front", 640, 480, True)
    source.record_price_offer(
        PriceOffer(
            item_id="motherboard-test-1",
            identifier="B550-F",
            retailer="Demo Shop",
            source_url="https://example.com/board",
            price_brl=Decimal("499.90"),
            observed_at=datetime.now(UTC),
        )
    )
    secret_url = SecretStr(database_url)

    first = migrate_catalog(source_path, secret_url)
    second = migrate_catalog(source_path, secret_url)
    destination = Catalog(database_url=secret_url)

    assert (
        first
        == second
        == {
            "items": 1,
            "identifiers": 1,
            "source_records": 2,
            "item_images": 1,
            "price_observations": 1,
        }
    )
    item = destination.get_item("motherboard-test-1")
    assert item is not None
    assert item.identifiers == ["B550-F"]
    assert item.estimated_price_brl == 499.9
    assert destination.list_images(item.id)[0]["view"] == "front"
    assert destination.get_source_records(item.id)[0]["data"]["socket"] == "AM4"
    client = TestClient(create_app(config=Settings(database_url=secret_url), catalog=destination))
    assert client.get("/ready").json()["items"] == 1
    assert client.get(f"/specs/{item.id}").json()["id"] == item.id
    assert client.post("/lookup", json={"text": "B550-F"}).json()["matches"][0]["id"] == item.id

    source.put_item(
        "ram-test-1",
        ItemInput(
            category=Category.RAM,
            brand="Demo",
            model="Demo 16 GB (2 x 8 GB) DDR4-3200 CL16 Memory",
            identifiers=["RAM-KIT-16"],
        ),
    )
    source.put_source_record(
        "test",
        "Memory.csv",
        1,
        {"name": "Demo 16 GB (2 x 8 GB) DDR4-3200 CL16 Memory", "size": "16", "type": "DDR4"},
        "ram-test-1",
    )
    upgraded = migrate_catalog(source_path, secret_url)
    ram = destination.get_item("ram-test-1")
    assert ram is not None
    assert ram.specifications["capacity_gb"].value == 16
    assert upgraded == {
        "items": 2,
        "identifiers": 2,
        "source_records": 3,
        "item_images": 1,
        "price_observations": 1,
    }
    original_board = destination.get_item(item.id)
    assert original_board is not None
    assert original_board.estimated_price_brl == 499.9
    assert destination.list_images(item.id)[0]["view"] == "front"
    assert client.post("/lookup", json={"text": "RAM-KIT-16"}).json()["matches"][0]["id"] == ram.id

    _add_psu_source(source)
    with_psu = migrate_catalog(source_path, secret_url)
    psu = destination.get_item("psu-test-1")
    assert psu is not None
    assert psu.specifications["wattage_w"].value == 750
    assert with_psu["items"] == 3
    assert (
        client.post("/lookup", json={"text": "DEMO-PSU-750"}).json()["matches"][0]["id"] == psu.id
    )

    destination.put_item(
        "cpu-test-1",
        ItemInput(category=Category.CPU, brand="Demo", model="Demo CPU", identifiers=["CPU-X"]),
    )
    assert destination.get_item("cpu-test-1") is not None
    assert migrate_catalog(source_path, secret_url) == with_psu
    source.put_source_record("test", "boards.csv", 3, {"model": "new"}, None, "unknown")
    with pytest.raises(RuntimeError, match="another SQLite version"):
        migrate_catalog(source_path, secret_url)
