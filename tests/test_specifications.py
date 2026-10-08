"""Source-backed hardware specification behavior."""

from __future__ import annotations

from scan_hardware.core.specifications import build_specifications
from scan_hardware.models.item import Category


def test_cpu_specifications_merge_matching_sources_and_expose_conflict() -> None:
    rows = [
        {
            "dataset": "rohitmit98/pc-parts-by-type",
            "data": {
                "socket": "LGA 1151",
                "speed": "4.2",
                "coreCount": "2",
                "threadCount": "4",
                "power": "50",
            },
        },
        {
            "dataset": "warcoder/pc-parts",
            "data": {
                "core_clock": 4.2,
                "core_count": 2,
                "graphics": "Intel HD Graphics 630",
                "smt": True,
                "tdp": 60,
            },
        },
    ]

    specs = build_specifications(Category.CPU, rows)

    assert specs["socket"].value == "LGA1151"
    assert specs["base_clock_ghz"].value == 4.2
    assert len(specs["base_clock_ghz"].evidence) == 2
    assert specs["cores"].value == 2
    assert specs["threads"].value == 4
    assert specs["smt"].value is True
    assert specs["tdp_w"].value is None
    assert specs["tdp_w"].status == "conflict"
    assert {entry.value for entry in specs["tdp_w"].evidence} == {50, 60}


def test_duplicate_rows_do_not_duplicate_evidence() -> None:
    row = {"dataset": "warcoder/pc-parts", "data": {"core_count": 2}}

    specs = build_specifications(Category.CPU, [row, row])

    assert specs["cores"].value == 2
    assert len(specs["cores"].evidence) == 1


def test_malformed_numbers_are_not_presented_as_hardware_facts() -> None:
    rows = [
        {
            "dataset": "warcoder/pc-parts",
            "data": {"core_count": "two", "tdp": -5, "core_clock": "nan"},
        }
    ]

    assert build_specifications(Category.CPU, rows) == {}


def test_gpu_and_motherboard_fields_keep_category_specific_meaning() -> None:
    gpu = build_specifications(
        Category.GPU,
        [{"dataset": "warcoder/pc-parts", "data": {"memory": 12, "core_clock": 1320}}],
    )
    board = build_specifications(
        Category.MOTHERBOARD,
        [{"dataset": "warcoder/pc-parts", "data": {"socket": "AM4", "memory_slots": 4}}],
    )

    assert gpu["vram_gb"].value == 12
    assert gpu["core_clock_mhz"].unit == "MHz"
    assert board["socket"].value == "AM4"
    assert board["memory_slots"].value == 4
