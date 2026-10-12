"""Real offline OCR smoke test on a clear printed hardware label."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from pytest_mock import MockerFixture
from rapidocr.utils.output import RapidOCROutput

from scan_hardware.api import create_app
from scan_hardware.config import Settings
from scan_hardware.services.ocr import OcrScanner


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
    assert response.json()["matches"][0]["id"] == "board-1"


def test_dark_label_uses_inverted_fallback(mocker: MockerFixture) -> None:
    image = Image.new("RGB", (1000, 500), "black")
    output = BytesIO()
    image.save(output, format="PNG")

    def recognize(content: bytes) -> RapidOCROutput:
        with Image.open(BytesIO(content)) as received:
            is_inverted = received.convert("L").getpixel((500, received.height // 2)) > 128
        text = "GA-Z77X-UD5H" if is_inverted else "GIGABYTE"
        return RapidOCROutput(txts=(text,), scores=(0.99,))

    mocker.patch("scan_hardware.services.ocr.RapidOCR", return_value=recognize)

    assert OcrScanner().read_text(output.getvalue()) == ["GIGABYTE", "GA-Z77X-UD5H"]


def test_board_revision_near_model_is_read_from_focused_crop(mocker: MockerFixture) -> None:
    image = Image.new("RGB", (1000, 1000), "white")
    output = BytesIO()
    image.save(output, format="PNG")

    def recognize(content: bytes) -> RapidOCROutput:
        with Image.open(BytesIO(content)) as received:
            is_crop = received.size != (1000, 1000)
        if is_crop:
            return RapidOCROutput(txts=("4.02", "A320M-DVS", "REV."), scores=(0.99, 0.99, 0.99))
        return RapidOCROutput(
            boxes=[[[450, 300], [550, 300], [550, 700], [450, 700]]],
            txts=("A320M-DVS",),
            scores=(0.99,),
        )

    mocker.patch("scan_hardware.services.ocr.RapidOCR", return_value=recognize)

    assert OcrScanner().read_text(output.getvalue()) == [
        "A320M-DVS",
        "A320M-DVS REV 4.02",
    ]
