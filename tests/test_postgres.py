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

    destination.put_item(
        "cpu-test-1",
        ItemInput(category=Category.CPU, brand="Demo", model="Demo CPU", identifiers=["CPU-X"]),
    )
    assert destination.get_item("cpu-test-1") is not None
    assert migrate_catalog(source_path, secret_url) == first
    source.put_source_record("test", "boards.csv", 3, {"model": "new"}, None, "unknown")
    with pytest.raises(RuntimeError, match="another SQLite version"):
        migrate_catalog(source_path, secret_url)
