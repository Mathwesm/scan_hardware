"""Behavior tests for exact model lookup and photo validation."""

from io import BytesIO
from pathlib import Path
from gzip import compress

import pytest
from PIL import Image

from hardware_scan.scanner import Hardware, Scanner, load_catalog, match_text


def test_exact_code_returns_specs_without_similar_model() -> None:
    catalog = [
        Hardware(
            id="z77",
            category="motherboard",
            brand="Gigabyte",
            model="GA-Z77X-UD5H",
            identifiers=["GA-Z77X-UD5H"],
            specs={"socket": "LGA1155"},
        ),
        Hardware(
            id="z170",
            category="motherboard",
            brand="Gigabyte",
            model="GA-Z170X-UD5 TH",
            identifiers=["GA-Z170X-UD5 TH"],
            specs={"socket": "LGA1151"},
        ),
    ]

    result = match_text(["GIGABYTE", "GA-Z77X-UD5H"], catalog)

    assert [(item.id, item.specs["socket"]) for item in result.matches] == [("z77", "LGA1155")]


def test_shorter_model_is_not_matched_inside_longer_code() -> None:
    catalog = [
        Hardware(
            id="old",
            category="motherboard",
            brand="ECS",
            model="A785GM-M",
            identifiers=["A785GM-M"],
        ),
        Hardware(
            id="new",
            category="motherboard",
            brand="ECS",
            model="A785GM-M3",
            identifiers=["A785GM-M3"],
        ),
    ]

    result = match_text(["A785GM-M3"], catalog)

    assert [item.id for item in result.matches] == ["new"]


def test_invalid_image_is_rejected() -> None:
    with pytest.raises(ValueError, match="corrupt or unsupported"):
        Scanner().scan(b"not an image", [])


def test_image_ocr_output_is_used_for_lookup() -> None:
    class FakeOutput:
        txts = ["A785GM-M3"]

    def fake_engine(image: bytes) -> FakeOutput:
        return FakeOutput()

    image = BytesIO()
    Image.new("RGB", (50, 50), color="white").save(image, format="PNG")
    catalog = [
        Hardware(
            id="ecs",
            category="motherboard",
            brand="ECS",
            model="A785GM-M3",
            identifiers=["A785GM-M3"],
        )
    ]

    result = Scanner(engine=fake_engine).scan(image.getvalue(), catalog)

    assert result.detected_text == ["A785GM-M3"]
    assert [item.id for item in result.matches] == ["ecs"]


def test_real_board_photo_finds_three_printed_models() -> None:
    root = Path(__file__).resolve().parents[1]
    image = (root / "tests" / "fixtures" / "placa.jpg").read_bytes()
    catalog = load_catalog(root / "catalog.example.json")

    result = Scanner().scan(image, catalog)

    assert {item.id for item in result.matches} == {
        "motherboard-ecs-a785gm-m3-v1",
        "motherboard-ecs-g41t-mr23-v1",
        "motherboard-ecs-a890gxm-a-v1",
    }


def test_load_compressed_catalog(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json.gz"
    catalog_path.write_bytes(
        compress(
            b'[{"id":"cpu-1","category":"cpu","brand":"AMD",'
            b'"model":"Ryzen 5 3600","identifiers":["Ryzen 5 3600"],'
            b'"specs":{"cores":6}}]',
            mtime=0,
        )
    )

    catalog = load_catalog(catalog_path)

    assert len(catalog) == 1
    assert catalog[0].specs["cores"] == 6
