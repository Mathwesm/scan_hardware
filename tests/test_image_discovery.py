"""Exact-image discovery must not attach a visually similar board variant."""

from pathlib import Path

import httpx
import pytest

from scan_hardware.image_discovery import (
    DiscoveryRow,
    approved_images,
    discover_images,
    load_review_run,
    publish_images,
    save_run,
)
from scan_hardware.models.item import Category, ItemInput
from scan_hardware.services.catalog import Catalog


def _catalog(path: Path) -> Catalog:
    catalog = Catalog(path)
    for suffix in ("", " LK"):
        catalog.put_item(
            f"board{suffix.replace(' ', '-')}",
            ItemInput(
                category=Category.MOTHERBOARD,
                brand="Asus",
                model=f"Asus P8Z77-V{suffix}",
                identifiers=[f"P8Z77-V{suffix}"],
            ),
        )
    return catalog


def _result(title: str) -> dict[str, str | int]:
    return {
        "title": title,
        "url": "https://example.org/photo.jpg",
        "foreign_landing_url": "https://example.org/photo",
        "creator": "Example photographer",
        "license": "by-sa",
        "license_version": "4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "width": 900,
        "height": 850,
    }


def test_discovery_ignores_variant_when_searching_base_model(tmp_path: Path) -> None:
    """P8Z77-V LK must not become the P8Z77-V reference photograph."""
    catalog = _catalog(tmp_path / "catalog.sqlite3")

    def respond(request: httpx.Request) -> httpx.Response:
        query = str(request.url.params["q"])
        result = _result("ASUS P8Z77-V LK motherboard")
        if query.endswith("P8Z77-V LK motherboard"):
            return httpx.Response(200, json={"results": [result]})
        return httpx.Response(200, json={"results": [result]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        images, report = discover_images(catalog, client, limit=2, delay_seconds=0)

    assert [(image.item_id, str(image.image_url)) for image in images] == [
        ("board-LK", "https://example.org/photo.jpg")
    ]
    assert [(row.item_id, row.status) for row in report] == [
        ("board", "no_match"),
        ("board-LK", "accepted"),
    ]


def test_discovery_rejects_tiny_or_ambiguous_photos(tmp_path: Path) -> None:
    """Search snippets and multiple plausible listings must remain unassigned."""
    catalog = _catalog(tmp_path / "catalog.sqlite3")
    tiny = _result("ASUS P8Z77-V motherboard")
    tiny["width"] = 200

    def respond(request: httpx.Request) -> httpx.Response:
        query = str(request.url.params["q"])
        results = (
            [tiny]
            if " LK " not in query
            else [
                _result("ASUS P8Z77-V LK motherboard"),
                {**_result("ASUS P8Z77-V LK top view"), "url": "https://example.org/other.jpg"},
            ]
        )
        return httpx.Response(200, json={"results": results})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        images, report = discover_images(catalog, client, limit=2, delay_seconds=0)

    assert images == []
    assert [row.status for row in report] == ["no_match", "ambiguous"]


def test_discovery_quarantines_malformed_api_response(tmp_path: Path) -> None:
    """A changed search response must leave the board without an image."""
    catalog = _catalog(tmp_path / "catalog.sqlite3")
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"images": []}))
    ) as client:
        images, report = discover_images(catalog, client, limit=1, delay_seconds=0)

    assert images == []
    assert [(row.item_id, row.status) for row in report] == [("board", "search_error")]


def test_icecat_requires_exact_product_code_and_registered_account(tmp_path: Path) -> None:
    """An Icecat variant must not be attached to a base model board."""
    catalog = _catalog(tmp_path / "catalog.sqlite3")

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["Brand"] == "Asus"
        assert request.url.params["ProductCode"] == "P8Z77-V"
        return httpx.Response(
            200,
            json={
                "msg": "OK",
                "data": {
                    "GeneralInfo": {
                        "Brand": "ASUS",
                        "BrandPartCode": "P8Z77-V",
                        "IcecatId": 13530032,
                        "Category": {"Name": {"Value": "Motherboards"}},
                    },
                    "Image": {
                        "HighPic": "https://images.icecat.biz/board.jpg",
                        "HighPicWidth": "500",
                        "HighPicHeight": "500",
                    },
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="registered Channel Partner"):
            discover_images(
                catalog, client, limit=1, provider="icecat", icecat_shopname="openicecat-live"
            )
        images, report = discover_images(
            catalog,
            client,
            limit=1,
            provider="icecat",
            icecat_shopname="registered-shop",
            delay_seconds=0,
        )

    assert [(image.item_id, str(image.image_url)) for image in images] == [
        ("board", "https://images.icecat.biz/board.jpg")
    ]
    assert report[0].status == "accepted"
    assert "openicecat-live" in str(images[0].source_url)

    def variant(request: httpx.Request) -> httpx.Response:
        payload = respond(request).json()
        payload["data"]["GeneralInfo"]["BrandPartCode"] = "P8Z77-V LK"
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(variant)) as client:
        wrong, decision = discover_images(
            catalog,
            client,
            limit=1,
            provider="icecat",
            icecat_shopname="registered-shop",
            delay_seconds=0,
        )
    assert wrong == []
    assert decision[0].status == "no_match"


def test_publication_preserves_existing_images(tmp_path: Path) -> None:
    """Publishing twice may add a board once but must never replace a previous photo."""
    path = tmp_path / "images.json"
    path.write_text(
        '{"images":[{"item_id":"board","image_url":"https://example.org/original.jpg",'
        '"creator":"Owner","source_url":"https://example.org/original"}]}',
        encoding="utf-8",
    )
    from scan_hardware.curation import VerifiedImage

    additions = [
        VerifiedImage(
            item_id="board-LK",
            image_url="https://example.org/new.jpg",
            creator="Photographer",
            source_url="https://example.org/new",
        )
    ]

    assert publish_images(additions, path) == 1
    assert publish_images(additions, path) == 0
    assert "original.jpg" in path.read_text(encoding="utf-8")

    approvals = tmp_path / "approved.txt"
    approvals.write_text("board-LK\n", encoding="utf-8")
    assert approved_images(additions, approvals) == additions
    approvals.write_text("board-missing\n", encoding="utf-8")
    with pytest.raises(ValueError, match="absent from this run"):
        approved_images(additions, approvals)

    catalog = _catalog(tmp_path / "catalog.sqlite3")
    run = save_run(
        additions,
        [
            DiscoveryRow(
                item_id="board-LK", model="Asus P8Z77-V LK", status="accepted", candidates=[]
            )
        ],
        tmp_path / "runs",
    )
    assert load_review_run(run, catalog) == additions
    report = run / "report.json"
    report.write_text(
        report.read_text(encoding="utf-8").replace("P8Z77-V LK", "P8Z77-V"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="no longer matches"):
        load_review_run(run, catalog)
