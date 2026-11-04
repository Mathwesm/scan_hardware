"""Socket relationships include only source-backed, unambiguous candidates."""

from pathlib import Path

from fastapi.testclient import TestClient

from scan_hardware.api import create_app
from scan_hardware.config import Settings
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.services.catalog import Catalog


def _add_item(
    catalog: Catalog, item_id: str, category: str, socket: str | None, brand: str = "Example"
) -> None:
    """Create a test record with an optional reported socket."""
    from scan_hardware.models.item import ItemInput

    catalog.put_item(
        item_id,
        ItemInput.model_validate(
            {
                "category": category,
                "brand": brand,
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


def test_socket_relationship_rejects_cpu_with_wrong_vendor(tmp_path: Path) -> None:
    """An erroneous Ryzen LGA1151 source row must not appear for an Intel board."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    _add_item(catalog, "board-intel", "motherboard", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-intel", "cpu", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-ryzen", "cpu", "LGA1151", brand="AMD")
    client = TestClient(create_app(config=Settings(image_dir=tmp_path / "images"), catalog=catalog))

    result = client.get("/specs/board-intel/socket-related").json()

    assert [candidate["id"] for candidate in result["matches"]] == ["cpu-intel"]


def test_intel_board_with_bad_amd_socket_has_no_cpu_relationship(tmp_path: Path) -> None:
    """A mislabelled Intel board must not suggest an AM4 Ryzen."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    _add_item(catalog, "board-intel", "motherboard", "AM4", brand="Intel")
    _add_item(catalog, "cpu-ryzen", "cpu", "AM4", brand="AMD")
    client = TestClient(create_app(config=Settings(image_dir=tmp_path / "images"), catalog=catalog))

    result = client.get("/specs/board-intel/socket-related").json()

    assert result["matches"] == []


def test_lga1151_filters_incompatible_intel_generations_in_both_directions(
    tmp_path: Path,
) -> None:
    """Intel 100/200 and 300 chipsets must not cross 6/7 and 8/9 Core generations."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    _add_item(catalog, "board-h110", "motherboard", "LGA1151", brand="Gigabyte")
    _add_item(catalog, "board-z370", "motherboard", "LGA1151", brand="MSI")
    catalog.put_source_record("fixture", "h110-chipset", 1, {"chipset": "Intel H110"}, "board-h110")
    catalog.put_source_record("fixture", "z370-chipset", 1, {"chipset": "Intel Z370"}, "board-z370")
    _add_item(catalog, "cpu-old", "cpu", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-new", "cpu", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-old-suffix", "cpu", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-new-suffix", "cpu", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-first-gen", "cpu", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-hedt", "cpu", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-gold", "cpu", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-xeon", "cpu", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-xeon-e3", "cpu", "LGA1151", brand="Intel")
    _add_item(catalog, "cpu-xeon-e3-low-power", "cpu", "LGA1151", brand="Intel")
    catalog.put_item(
        "cpu-old",
        ItemInput.model_validate(
            {
                "category": "cpu",
                "brand": "Intel",
                "model": "Intel Core i5-6500",
                "identifiers": ["cpu-old"],
            }
        ),
    )
    catalog.put_item(
        "cpu-new",
        ItemInput.model_validate(
            {
                "category": "cpu",
                "brand": "Intel",
                "model": "Intel Core i5-8400",
                "identifiers": ["cpu-new"],
            }
        ),
    )
    for item_id, model in (
        ("cpu-old-suffix", "Intel Core i3-7100T"),
        ("cpu-new-suffix", "Intel Core i3-8100T"),
        ("cpu-first-gen", "Intel Core i7-920"),
        ("cpu-hedt", "Intel Core i5-7640X"),
        ("cpu-gold", "Intel Pentium Gold G5400"),
        ("cpu-xeon", "Intel Xeon E-2144G"),
        ("cpu-xeon-e3", "Intel Xeon E3-1230 V5"),
        ("cpu-xeon-e3-low-power", "Intel Xeon E3-1235L V5"),
    ):
        catalog.put_item(
            item_id,
            ItemInput.model_validate(
                {"category": "cpu", "brand": "Intel", "model": model, "identifiers": [item_id]}
            ),
        )
    client = TestClient(create_app(config=Settings(image_dir=tmp_path / "images"), catalog=catalog))

    assert {x["id"] for x in client.get("/specs/board-h110/socket-related").json()["matches"]} == {
        "cpu-old",
        "cpu-old-suffix",
    }
    assert {x["id"] for x in client.get("/specs/board-z370/socket-related").json()["matches"]} == {
        "cpu-new",
        "cpu-new-suffix",
        "cpu-gold",
    }
    assert [x["id"] for x in client.get("/specs/cpu-new/socket-related").json()["matches"]] == [
        "board-z370"
    ]


def test_board_with_chipset_from_other_vendor_has_no_socket_matches(tmp_path: Path) -> None:
    """A bad motherboard source socket must not suggest another vendor's CPUs."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    _add_item(catalog, "board-bad", "motherboard", "AM4", brand="Gigabyte")
    catalog.put_source_record("fixture", "chipset", 1, {"chipset": "Intel Z370"}, "board-bad")
    _add_item(catalog, "cpu-am4", "cpu", "AM4", brand="AMD")
    client = TestClient(create_app(config=Settings(image_dir=tmp_path / "images"), catalog=catalog))

    assert client.get("/specs/board-bad/socket-related").json()["matches"] == []


def test_lga1155_board_includes_manufacturer_verified_cpu_sockets(tmp_path: Path) -> None:
    """Curated Intel sockets must add CPUs absent from the imported dataset."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    _add_item(catalog, "board-z77", "motherboard", "LGA1155", brand="Gigabyte")
    verified_cpus = {
        "cpu-04394d651b7cd021a6bdcc16": "Intel Core i5-3570",
        "cpu-067ae851a667ef987f185106": "Intel Core i7-2700K",
        "cpu-087d484b8fb43f5fa38a43da": "Intel Core i5-3550",
        "cpu-0d520347817eb7608d9b7c7c": "Intel Core i7-3770K",
        "cpu-11e8b2a45c6727325d7426d1": "Intel Core i5-3470",
        "cpu-2d675853c37bfbbdad477e17": "Intel Core i5-3570K",
        "cpu-bc6c5022d07530787f42dd31": "Intel Core i5-3470S",
    }
    for item_id, model in verified_cpus.items():
        catalog.put_item(
            item_id,
            ItemInput(category=Category.CPU, brand="Intel", model=model, identifiers=[item_id]),
        )
    client = TestClient(create_app(config=Settings(image_dir=tmp_path / "images"), catalog=catalog))

    result = client.get("/specs/board-z77/socket-related").json()

    assert result["total"] == len(verified_cpus)
    assert {candidate["id"] for candidate in result["matches"]} == verified_cpus.keys()


def test_verified_intel_socket_replaces_wrong_lga1151_source(tmp_path: Path) -> None:
    """Older and X-series CPUs must expose their actual sockets in specs and relations."""
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    _add_item(catalog, "board-h110", "motherboard", "LGA1151", brand="MSI")
    catalog.put_source_record("fixture", "chipset", 1, {"chipset": "Intel H110"}, "board-h110")
    corrected = {
        "cpu-046f566d1d9153812380414b": ("Intel Core i7-870", "LGA1156"),
        "cpu-2cfe5e253b2d7880dc482c31": ("Intel Core i7-920", "LGA1366"),
        "cpu-b811ae9ed5e2e588f680d8b4": ("Intel Core i9-9900X", "LGA2066"),
    }
    for item_id, (model, expected_socket) in corrected.items():
        _add_item(catalog, item_id, "cpu", "LGA1151", brand="Intel")
        catalog.put_item(
            item_id,
            ItemInput(category=Category.CPU, brand="Intel", model=model, identifiers=[item_id]),
        )
        stored = catalog.get_item(item_id)
        assert stored is not None
        assert stored.specifications["socket"].value == expected_socket
        assert stored.specifications["socket"].status == "verified"
    client = TestClient(create_app(config=Settings(image_dir=tmp_path / "images"), catalog=catalog))

    assert client.get("/specs/board-h110/socket-related").json()["matches"] == []
