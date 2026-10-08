"""End-to-end API behavior with a deterministic OCR adapter."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from scan_hardware.api import create_app
from scan_hardware.config import Settings
from scan_hardware.services.catalog import Catalog
from scan_hardware.services.ocr import OcrScanner


class FakeScanner(OcrScanner):
    """Return a known OCR reading while exercising the full HTTP workflow."""

    def read_text(self, _content: bytes) -> list[str]:
        """Stand in for the local OCR model during API contract tests."""
        return ["B550-F GAMING"]


def _png() -> bytes:
    """Create a valid small image for upload validation."""
    image = Image.new("RGB", (128, 64), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_scan_returns_matching_item_and_local_image(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))
    item_data = {
        "category": "motherboard",
        "brand": "Demo",
        "model": "B550-F Gaming",
        "identifiers": ["B550-F GAMING"],
    }
    assert client.put("/items/board-1", json=item_data).status_code == 200
    picture = _png()
    image_response = client.put(
        "/items/board-1/image", files={"image": ("board.png", picture, "image/png")}
    )

    assert image_response.status_code == 200
    assert image_response.json()["local_image_url"] == "/items/board-1/image"
    scan_response = client.post("/scan", files={"image": ("scan.png", picture, "image/png")})

    assert scan_response.status_code == 200
    assert scan_response.json()["status"] == "matched"
    assert scan_response.json()["matches"][0]["item"]["id"] == "board-1"
    assert client.get("/items/board-1/image").content == picture


def test_scan_rejects_invalid_image(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))

    response = client.post("/scan", files={"image": ("bad.png", b"not an image", "image/png")})

    assert response.status_code == 422
    assert "corrupt or unsupported" in response.json()["detail"]


def test_lookup_without_catalog_returns_not_found(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))

    response = client.post("/lookup", json={"text": "RTX-4070"})

    assert response.status_code == 200
    assert response.json()["status"] == "not_found"


def test_item_sources_returns_all_original_fields(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))
    client.put(
        "/items/board-1",
        json={
            "category": "motherboard",
            "brand": "ASRock",
            "model": "B365M-HDV",
            "identifiers": ["B365M-HDV"],
        },
    )
    catalog = Catalog(config.resolved_catalog_path)
    catalog.put_source_record(
        "warcoder/pc-parts",
        "dataset/motherboard.json",
        1,
        {"name": "ASRock B365M-HDV", "socket": "LGA1151", "memory_slots": 2},
        "board-1",
    )

    response = client.get("/items/board-1/sources")

    assert response.status_code == 200
    assert response.json()[0]["data"]["memory_slots"] == 2
    assert response.json()[0]["data"]["socket"] == "LGA1151"
