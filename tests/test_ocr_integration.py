"""Real offline OCR smoke test on a clear printed hardware label."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from scan_hardware.api import create_app
from scan_hardware.config import Settings


def test_printed_model_photo_matches_catalog_item(tmp_path: Path) -> None:
    image = Image.new("RGB", (1000, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 55), "B550-F GAMING", fill="black", font=ImageFont.load_default(size=90))
    output = BytesIO()
    image.save(output, format="PNG")
    content = output.getvalue()
    client = TestClient(
        create_app(
            config=Settings(
                catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images"
            )
        )
    )
    item = {
        "category": "motherboard",
        "brand": "Example",
        "model": "B550-F Gaming",
        "identifiers": ["B550-F GAMING"],
    }
    assert client.put("/items/board-1", json=item).status_code == 200

    response = client.post("/scan", files={"image": ("label.png", content, "image/png")})

    assert response.status_code == 200
    assert response.json()["status"] == "matched"
    assert response.json()["matches"][0]["item"]["id"] == "board-1"
