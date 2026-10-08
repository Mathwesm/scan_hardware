"""Behavior tests for hardware identifier matching."""

from __future__ import annotations

import pytest

from scan_hardware.core.matching import match_items, normalize_identifier
from scan_hardware.models.item import Category, Item


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  B550-F GAMING ", "B550FGAMING"),
        ("RTX-4070 SUPER", "RTX4070SUPER"),
        ("Pláca Mãe", "PLACAMAE"),
    ],
)
def test_normalize_identifier_handles_printed_variants(raw: str, expected: str) -> None:
    assert normalize_identifier(raw) == expected


def test_exact_identifier_inside_longer_ocr_line() -> None:
    item = Item(
        id="board-1",
        category=Category.MOTHERBOARD,
        brand="Example",
        model="B550-F Gaming",
        identifiers=["B550-F GAMING"],
    )

    result = match_items(["MODEL: B550 F GAMING REV 1.0"], [item])

    assert result.status == "matched"
    assert result.matches[0].item.id == "board-1"
    assert result.matches[0].is_exact is True


def test_identifier_split_across_adjacent_ocr_lines() -> None:
    item = Item(
        id="board-1",
        category=Category.MOTHERBOARD,
        brand="Example",
        model="B550-F Gaming",
        identifiers=["B550-F GAMING"],
    )

    result = match_items(["B550-F", "GAMING"], [item])

    assert result.status == "matched"
    assert result.matches[0].matched_identifier == "B550-F GAMING"


def test_similar_identifier_is_only_a_suggestion() -> None:
    item = Item(
        id="gpu-1",
        category=Category.GPU,
        brand="Example",
        model="RTX 4080",
        identifiers=["RTX-4080"],
    )

    result = match_items(["RTX-4090"], [item])

    assert result.status == "suggestions"
    assert result.matches[0].is_exact is False


def test_identifier_prefix_is_not_exact_model_match() -> None:
    item = Item(
        id="gpu-1",
        category=Category.GPU,
        brand="Example",
        model="RTX 4080",
        identifiers=["RTX-4080"],
    )

    result = match_items(["RTX-4080TI"], [item])

    assert result.status != "matched"


def test_unrelated_text_does_not_identify_hardware() -> None:
    item = Item(
        id="cpu-1",
        category=Category.CPU,
        brand="Example",
        model="CPU 12345",
        identifiers=["CPU-12345"],
    )

    result = match_items(["MADE IN CHINA"], [item])

    assert result.status == "not_found"
    assert result.matches == []


def test_exact_match_does_not_include_fuzzy_suggestions() -> None:
    exact = Item(
        id="gpu-4080",
        category=Category.GPU,
        brand="Asus",
        model="GeForce RTX 4080",
        identifiers=["TUF GAMING GEFORCE RTX 4080"],
    )
    similar = Item(
        id="gpu-4070",
        category=Category.GPU,
        brand="Asus",
        model="GeForce RTX 4070",
        identifiers=["TUF GAMING GEFORCE RTX 4070"],
    )

    result = match_items(["TUF GAMING GEFORCE RTX 4080"], [similar, exact])

    assert result.status == "matched"
    assert [match.item.id for match in result.matches] == ["gpu-4080"]
