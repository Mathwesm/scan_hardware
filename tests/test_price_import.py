"""Behavior checks for local BRL price observations."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scan_hardware.api import create_app
from scan_hardware.config import Settings
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.models.price import PriceOffer
from scan_hardware.price_import import import_prices
from scan_hardware.services.catalog import Catalog


def _catalog(path: Path) -> Catalog:
    catalog = Catalog(path)
    catalog.put_item(
        "cpu-1",
        ItemInput(
            category=Category.CPU,
            brand="AMD",
            model="Ryzen 5 5600X",
            identifiers=["100-100000065BOX"],
        ),
    )
    return catalog


def _offer(retailer: str, price: str, observed_at: datetime) -> PriceOffer:
    return PriceOffer(
        item_id="cpu-1",
        identifier="100-100000065BOX",
        retailer=retailer,
        source_url=f"https://example.com/{retailer}",
        price_brl=price,
        observed_at=observed_at,
    )


def test_price_mean_uses_latest_offer_per_retailer_and_expires(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path / "catalog.sqlite3")
    now = datetime.now(UTC)
    catalog.record_price_offer(_offer("Store A", "1000.00", now - timedelta(days=2)))
    catalog.record_price_offer(_offer("Store A", "1200.00", now - timedelta(days=1)))
    catalog.record_price_offer(_offer("Store B", "1400.00", now))

    assert catalog.price_summary("cpu-1", at=now) == (1300.0, 2, now)
    assert catalog.get_item("cpu-1").estimated_price_brl == 1300.0
    assert catalog.price_summary("cpu-1", at=now + timedelta(days=15)) is None


def test_wrong_identifier_and_naive_date_are_rejected(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path / "catalog.sqlite3")
    with pytest.raises(ValueError, match="identifier does not belong"):
        catalog.record_price_offer(
            PriceOffer(
                item_id="cpu-1",
                identifier="100-100000065WOF",
                retailer="Store A",
                source_url="https://example.com/item",
                price_brl="1000.00",
                observed_at=datetime.now(UTC),
            )
        )
    with pytest.raises(ValueError, match="must include a timezone"):
        _offer("Store A", "1000.00", datetime.fromisoformat("2026-10-13T10:00:00"))


def test_manifest_quarantines_bad_rows_and_is_idempotent(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path / "catalog.sqlite3")
    now = datetime.now(UTC)
    manifest = tmp_path / "manifest.json"
    valid = _offer("Store A", "999.90", now).model_dump(mode="json")
    manifest.write_text(
        json.dumps({"offers": [valid, {**valid, "identifier": "wrong-code"}]}),
        encoding="utf-8",
    )

    first = import_prices(manifest, catalog, tmp_path / "reports")
    second = import_prices(manifest, catalog, tmp_path / "reports")

    assert first == second == {"imported": 1, "rejected": 1, "total": 2}
    assert catalog.price_summary("cpu-1", at=now) == (999.9, 1, now)


def test_price_is_flat_in_lookup_and_specs_json(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    catalog = _catalog(path)
    observed = datetime.now(UTC)
    catalog.record_price_offer(_offer("Store A", "1000.00", observed))
    catalog.record_price_offer(_offer("Store B", "1500.00", observed))
    client = TestClient(create_app(config=Settings(catalog_path=path)))

    lookup = client.post("/lookup", json={"text": "100-100000065BOX"})
    specs = client.get("/specs/cpu-1")

    assert lookup.status_code == specs.status_code == 200
    assert lookup.json()["matches"][0]["estimated_price_brl"] == 1250.0
    assert lookup.json()["matches"][0]["price_offer_count"] == 2
    assert specs.json()["estimated_price_brl"] == 1250.0
