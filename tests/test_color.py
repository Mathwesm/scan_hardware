"""Behavioral checks for conservative color estimates from photographs."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from scan_hardware.core.color import estimate_photo_color
from scan_hardware.models.item import Category, Item, Match, ScanResponse, ScanResult


def _image_with_board(color: str, *, dark_edge: bool = False) -> bytes:
    """Make a small studio-style image without accessing external media."""
    image = Image.new("RGB", (300, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 70, 220, 250), fill=color)
    if dark_edge:
        draw.rectangle((240, 0, 299, 140), fill="black")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize("color", ["red", "green", "blue"])
def test_estimates_dominant_board_color_against_white_background(color: str) -> None:
    assert estimate_photo_color(_image_with_board(color)) == color.title()


def test_ignores_dark_backdrop_connected_to_image_edge() -> None:
    assert estimate_photo_color(_image_with_board("green", dark_edge=True)) == "Green"


def test_blank_image_has_no_hardware_color() -> None:
    image = Image.new("RGB", (300, 300), "white")
    output = BytesIO()
    image.save(output, format="PNG")

    assert estimate_photo_color(output.getvalue()) is None


def test_lookup_uses_packaged_reference_estimate_when_source_is_missing() -> None:
    item = Item(
        id="motherboard-ecs-a785gm-m3-v1",
        category=Category.MOTHERBOARD,
        brand="ECS",
        model="ECS A785GM-M3 (V1.0)",
        identifiers=["A785GM-M3"],
    )
    result = ScanResult(
        status="matched",
        detected_text=["A785GM-M3"],
        matches=[Match(item=item, matched_identifier="A785GM-M3", score=1.0, is_exact=True)],
    )

    response = ScanResponse.from_result(result)

    assert response.matches[0].color_source == "reference_estimate"
    assert response.matches[0].color is not None
    assert "Green" in response.matches[0].color


def test_reference_estimate_does_not_apply_to_different_model() -> None:
    item = Item(
        id="motherboard-ecs-a785gm-m3-v1",
        category=Category.MOTHERBOARD,
        brand="ECS",
        model="Different revision",
        identifiers=["A785GM-M3"],
    )
    result = ScanResult(
        status="matched",
        detected_text=["A785GM-M3"],
        matches=[Match(item=item, matched_identifier="A785GM-M3", score=1.0, is_exact=True)],
    )

    response = ScanResponse.from_result(result)

    assert response.matches[0].color is None
