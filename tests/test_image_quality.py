"""Tests for rejecting tiny products in otherwise usable primary images."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from scan_hardware.core.image_quality import foreground_coverage


def _product_photo(box: tuple[int, int, int, int]) -> bytes:
    image = Image.new("RGB", (1000, 1000), "white")
    ImageDraw.Draw(image).rectangle(box, fill="black")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_small_subject_is_detected_by_frame_coverage() -> None:
    assert foreground_coverage(_product_photo((20, 20, 180, 180))) < 0.25


def test_centered_subject_occupies_enough_of_frame() -> None:
    assert foreground_coverage(_product_photo((150, 150, 850, 850))) > 0.25
