"""End-to-end API behavior with a deterministic OCR adapter."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pydantic import SecretStr

from scan_hardware.api import create_app
from scan_hardware.config import Settings
from scan_hardware.services.catalog import Catalog
from scan_hardware.services.ocr import OcrScanner


class FakeScanner(OcrScanner):
    """Return a known OCR reading while exercising the full HTTP workflow."""

    def read_text(self, _content: bytes) -> list[str]:
        """Stand in for the local OCR model during API contract tests."""
        return ["B550-F GAMING"]


class CpuScanner(OcrScanner):
    """Return a printed CPU code for the HTTP scan contract test."""

    def read_text(self, _content: bytes) -> list[str]:
        """Read the model code from the deterministic fixture."""
        return ["i3-7350K"]


class RamScanner(OcrScanner):
    """Return a RAM part number for the HTTP scan contract test."""

    def read_text(self, _content: bytes) -> list[str]:
        """Read the part number from the deterministic fixture."""
        return ["CMZ16GX3M2A1600C10"]


def _png() -> bytes:
    """Create a valid small image for upload validation."""
    image = Image.new("RGB", (128, 64), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _colored_png() -> bytes:
    """Create a visible board-like colored area for the photo estimate contract."""
    image = Image.new("RGB", (300, 300), "white")
    ImageDraw.Draw(image).rectangle((30, 70, 220, 250), fill="green")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _large_png(color: str) -> bytes:
    """Create a full-resolution product view for gallery upload tests."""
    image = Image.new("RGB", (900, 900), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _poorly_framed_png() -> bytes:
    """Create a large file with the hardware occupying only one corner."""
    image = Image.new("RGB", (1000, 1000), "white")
    ImageDraw.Draw(image).rectangle((30, 30, 180, 180), fill="black")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_scan_marks_photo_color_as_estimate_when_catalog_has_none(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))
    client.put(
        "/items/board-1",
        json={
            "category": "motherboard",
            "brand": "Demo",
            "model": "B550-F Gaming",
            "identifiers": ["B550-F GAMING"],
        },
    )

    response = client.post("/scan", files={"image": ("board.png", _colored_png(), "image/png")})

    assert response.status_code == 200
    assert response.json()["matches"][0]["color"] == "Green"
    assert response.json()["matches"][0]["color_source"] == "photo_estimate"


def test_catalog_color_takes_precedence_over_photo_estimate(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))
    client.put(
        "/items/board-1",
        json={
            "category": "motherboard",
            "brand": "Demo",
            "model": "B550-F Gaming",
            "identifiers": ["B550-F GAMING"],
        },
    )
    Catalog(config.resolved_catalog_path).put_source_record(
        "sample", "board.csv", 1, {"color": "Black"}, "board-1"
    )

    response = client.post("/scan", files={"image": ("board.png", _colored_png(), "image/png")})

    assert response.status_code == 200
    assert response.json()["matches"][0]["color"] == "Black"
    assert response.json()["matches"][0]["color_source"] == "catalog"


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
    assert scan_response.json()["matches"][0]["id"] == "board-1"
    assert client.get("/items/board-1/image").content == picture


def test_ram_lookup_and_scan_return_flat_kit_specs(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=RamScanner()))
    item_id = "ram-corsair-16"
    response = client.put(
        f"/items/{item_id}",
        json={
            "category": "ram",
            "brand": "Corsair",
            "model": "Corsair Vengeance 16 GB (2 x 8 GB) DDR3-1600 CL9 Memory",
            "identifiers": ["CMZ16GX3M2A1600C10"],
            "image_url": "https://example.com/ram.jpg",
        },
    )
    assert response.status_code == 200
    Catalog(config.resolved_catalog_path).put_source_record(
        "rohitmit98/pc-parts-by-type",
        "Memory.csv",
        1,
        {
            "name": "Corsair Vengeance 16 GB (2 x 8 GB) DDR3-1600 CL9 Memory",
            "type": "DDR3",
            "size": "16",
        },
        item_id,
    )

    lookup = client.post("/lookup", json={"text": "CMZ16GX3M2A1600C10"})
    scan = client.post("/scan", files={"image": ("ram.png", _png(), "image/png")})

    assert lookup.status_code == 200
    assert scan.status_code == 200
    for result in (lookup.json(), scan.json()):
        assert result["status"] == "matched"
        assert len(result["matches"]) == 1
        assert result["matches"][0]["category"] == "ram"
        assert result["matches"][0]["capacity_gb"] == 16
        assert result["matches"][0]["module_count"] == 2
        assert result["matches"][0]["memory_speed_mt_s"] == 1600
        assert result["matches"][0]["image_url"] == "https://example.com/ram.jpg"
        assert "specs" not in result["matches"][0]


def test_gallery_keeps_front_primary_and_side_as_secondary(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))
    client.put(
        "/items/board-1",
        json={
            "category": "motherboard",
            "brand": "Demo",
            "model": "B550-F Gaming",
            "identifiers": ["B550-F GAMING"],
        },
    )
    front = _large_png("blue")
    side = _png()

    assert (
        client.put(
            "/items/board-1/images/front", files={"image": ("front.png", front, "image/png")}
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/items/board-1/images/side", files={"image": ("side.png", side, "image/png")}
        ).status_code
        == 200
    )
    images = client.get("/items/board-1/images").json()

    assert [(image["view"], image["is_primary"]) for image in images] == [
        ("front", True),
        ("side", False),
    ]
    assert client.get("/items/board-1/image").content == front
    assert client.get(images[1]["url"]).content == side
    assert client.get(images[1]["url"].replace("board-1", "board-2")).status_code == 404


def test_gallery_rejects_tiny_primary_and_nonfront_primary(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))
    client.put(
        "/items/board-1",
        json={
            "category": "motherboard",
            "brand": "Demo",
            "model": "B550-F Gaming",
            "identifiers": ["B550-F GAMING"],
        },
    )

    tiny = client.put(
        "/items/board-1/images/front", files={"image": ("tiny.png", _png(), "image/png")}
    )
    side = client.put(
        "/items/board-1/images/side?primary=true",
        files={"image": ("side.png", _large_png("red"), "image/png")},
    )
    corner = client.put(
        "/items/board-1/images/front",
        files={"image": ("corner.png", _poorly_framed_png(), "image/png")},
    )

    assert tiny.status_code == 422
    assert "800 px" in tiny.json()["detail"]
    assert side.status_code == 422
    assert "front view" in side.json()["detail"]
    assert corner.status_code == 422
    assert "too small" in corner.json()["detail"]


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
    assert response.json()["matches"] == []
    assert client.get("/ready").status_code == 503


def test_lookup_pages_ranked_partial_code_suggestions(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))
    for index, code in enumerate(("B550M", "B550-PLUS", "B550-F GAMING"), start=1):
        response = client.put(
            f"/items/board-{index}",
            json={
                "category": "motherboard",
                "brand": "Demo",
                "model": f"Demo {code}",
                "identifiers": [code],
            },
        )
        assert response.status_code == 200

    first = client.post("/lookup", json={"text": "bs500", "limit": 1})
    second = client.post("/lookup", json={"text": "bs500", "limit": 1, "offset": 1})

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "suggestions"
    assert first.json()["total_matches"] == 3
    assert first.json()["matches"][0]["model"] == "Demo B550M"
    assert first.json()["matches"][0]["match_score"] > second.json()["matches"][0]["match_score"]
    assert second.json()["matches"][0]["id"] != first.json()["matches"][0]["id"]
    assert client.post("/lookup", json={"text": "bs500", "limit": 101}).status_code == 422


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


def test_scan_exposes_cpu_specs_and_source_conflict(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=CpuScanner()))
    client.put(
        "/items/cpu-1",
        json={
            "category": "cpu",
            "brand": "Intel",
            "model": "Intel Core i3-7350K",
            "identifiers": ["i3-7350K"],
        },
    )
    catalog = Catalog(config.resolved_catalog_path)
    catalog.put_source_record(
        "rohitmit98/pc-parts-by-type",
        "CPU.csv",
        1,
        {"socket": "LGA 1151", "speed": "4.2", "coreCount": "2", "threadCount": "4", "power": "50"},
        "cpu-1",
    )
    catalog.put_source_record(
        "warcoder/pc-parts",
        "dataset/cpu.json",
        1,
        {"core_clock": 4.2, "core_count": 2, "tdp": 60},
        "cpu-1",
    )

    response = client.post("/scan", files={"image": ("cpu.png", _png(), "image/png")})

    assert response.status_code == 200
    assert response.json()["status"] == "matched"
    match = response.json()["matches"][0]
    assert match == {
        "category": "cpu",
        "brand": "Intel",
        "model": "Intel Core i3-7350K",
        "id": "cpu-1",
        "price_status": "unavailable",
        "socket": "LGA1151",
        "base_clock_ghz": 4.2,
        "cores": 2,
        "threads": 4,
    }
    assert client.get("/specs/cpu-1").json()["specs"]["tdp_w"]["status"] == "conflict"
    assert client.get("/items/cpu-1").status_code == 405

    schema = client.get("/openapi.json").json()["components"]["schemas"]["HardwareSummary"]
    assert {"id", "model", "socket", "cores", "threads"} <= schema["properties"].keys()
    assert "specs" not in schema["properties"]


@pytest.mark.parametrize(
    ("item_id", "item", "source", "expected_fields"),
    [
        (
            "board-1",
            {
                "category": "motherboard",
                "brand": "Gigabyte",
                "model": "Gigabyte GA-Z170X-UD5 TH",
                "identifiers": ["GA-Z170X-UD5 TH"],
            },
            {"socket": "LGA1151", "size": "ATX", "max_memory": 64, "memory_slots": 4},
            {"socket": "LGA1151", "form_factor": "ATX", "max_memory_gb": 64, "memory_slots": 4},
        ),
        (
            "gpu-1",
            {
                "category": "gpu",
                "brand": "Nvidia",
                "model": "Nvidia RTX 4080",
                "identifiers": ["RTX 4080"],
            },
            {"chipset": "GeForce RTX 4080", "VRAM": 16, "power": 320},
            {"chipset": "GeForce RTX 4080", "vram_gb": 16, "board_power_w": 320},
        ),
    ],
)
def test_lookup_returns_flat_hardware_fields(
    tmp_path: Path,
    item_id: str,
    item: dict[str, object],
    source: dict[str, object],
    expected_fields: dict[str, object],
) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))
    assert client.put(f"/items/{item_id}", json=item).status_code == 200
    Catalog(config.resolved_catalog_path).put_source_record(
        "warcoder/pc-parts", "dataset/item.json", 1, source, item_id
    )

    response = client.post("/lookup", json={"text": item["identifiers"][0]})

    assert response.status_code == 200
    assert response.json()["status"] == "matched"
    assert response.json()["matches"] == [
        {
            "category": item["category"],
            "brand": item["brand"],
            "model": item["model"],
            "id": item_id,
            "price_status": "unavailable",
            **expected_fields,
        }
    ]


def test_gigabyte_board_includes_exact_photo_and_memory_limits(tmp_path: Path) -> None:
    item_id = "motherboard-2716c8c323f0e5902e139112"
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))
    assert (
        client.put(
            f"/items/{item_id}",
            json={
                "category": "motherboard",
                "brand": "Gigabyte",
                "model": "Gigabyte GA-Z77X-UD5H",
                "identifiers": ["Gigabyte GA-Z77X-UD5H"],
            },
        ).status_code
        == 200
    )
    Catalog(config.resolved_catalog_path).put_source_record(
        "warcoder/pc-parts",
        "dataset/motherboard.json",
        1,
        {"max_memory": 32, "memory_slots": 4},
        item_id,
    )

    response = client.post("/lookup", json={"text": "GA-Z77X-UD5H"})

    assert response.status_code == 200
    board = response.json()["matches"][0]
    assert board["image_url"].startswith("https://static.gigabyte.com/")
    assert board["max_memory_gb"] == 32
    assert board["memory_type"] == "DDR3"
    assert board["memory_slot_type"] == "DIMM"
    assert board["memory_channels"] == 2
    assert board["max_memory_standard_mhz"] == 1600
    assert board["max_memory_oc_mhz"] == 2800
    details = client.get(f"/specs/{item_id}").json()
    assert details["image_attribution"] is None
    assert details["specs"]["max_memory_oc_mhz"]["status"] == "verified"


@pytest.mark.parametrize(
    ("item_id", "category", "model", "identifier", "expected"),
    [
        (
            "cpu-dd697180a182948f05745f01",
            "cpu",
            "AMD Ryzen 5 5600X",
            "Ryzen 5 5600X",
            {
                "memory_type": "DDR4",
                "memory_speed_mt_s": 3200,
                "l2_cache_mb": 3,
                "l3_cache_mb": 32,
                "tdp_w": 65,
            },
        ),
        (
            "gpu-bd1343be29aefce878e7e33c",
            "gpu",
            "MSI GTX 1050 Ti 4GT OC GeForce GTX 1050 Ti",
            "GTX 1050 Ti 4GT OC",
            {
                "memory_type": "GDDR5",
                "memory_speed_mhz": 7008,
                "memory_bus_bits": 128,
                "shader_units": 768,
            },
        ),
    ],
)
def test_lookup_exposes_verified_memory_details_for_cpu_and_gpu(
    tmp_path: Path,
    item_id: str,
    category: str,
    model: str,
    identifier: str,
    expected: dict[str, str | int],
) -> None:
    """A verified model-specific fact must reach the flat mobile response."""
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3", image_dir=tmp_path / "images")
    client = TestClient(create_app(config=config, scanner=FakeScanner()))
    assert (
        client.put(
            f"/items/{item_id}",
            json={
                "category": category,
                "brand": model.split()[0],
                "model": model,
                "identifiers": [identifier],
            },
        ).status_code
        == 200
    )

    response = client.post("/lookup", json={"text": identifier})

    assert response.status_code == 200
    assert response.json()["status"] == "matched"
    match = response.json()["matches"][0]
    assert all(match[field] == value for field, value in expected.items())
    details = client.get(f"/specs/{item_id}").json()["specs"]
    assert all(details[field]["status"] == "verified" for field in expected)


def test_demo_is_available_for_local_camera_testing(tmp_path: Path) -> None:
    config = Settings(catalog_path=tmp_path / "catalog.sqlite3")
    response = TestClient(create_app(config=config, scanner=FakeScanner())).get("/demo")

    assert response.status_code == 200
    assert 'capture="environment"' in response.text


def test_api_key_protects_scans_and_catalog_writes(tmp_path: Path) -> None:
    key = "test-secret-" + "x" * 32
    config = Settings(
        catalog_path=tmp_path / "catalog.sqlite3",
        require_api_key=True,
        api_key=SecretStr(key),
    )
    client = TestClient(create_app(config=config, scanner=FakeScanner()))

    assert client.get("/health").status_code == 200
    assert client.post("/lookup", json={"text": "E8400"}).status_code == 401
    assert client.put("/items/cpu-1", json={}).status_code == 401
    assert client.get("/demo").status_code == 401
    response = client.post("/lookup", json={"text": "E8400"}, headers={"x-api-key": key})
    assert response.status_code == 200


def test_auth_enabled_rejects_missing_or_short_key(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        create_app(config=Settings(catalog_path=tmp_path / "catalog.sqlite3", require_api_key=True))
