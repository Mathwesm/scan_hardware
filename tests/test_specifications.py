"""Source-backed hardware specification behavior."""

from __future__ import annotations

import pytest

from scan_hardware.core import specifications
from scan_hardware.core.specifications import build_specifications
from scan_hardware.curation import ReportedColor
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


def test_color_order_does_not_create_false_conflict() -> None:
    rows = [
        {"dataset": "source-a", "data": {"color": "Black / Silver"}},
        {"dataset": "source-b", "data": {"color": "Silver / Black"}},
    ]

    specs = build_specifications(Category.MOTHERBOARD, rows)

    assert specs["color"].status == "reported"
    assert specs["color"].value == "Black / Silver"
    assert {entry.value for entry in specs["color"].evidence} == {
        "Black / Silver",
        "Silver / Black",
    }


def test_exact_part_number_color_fills_only_missing_catalog_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The secondary source fills a gap but never replaces an imported fact."""
    entry = ReportedColor(
        item_id="gpu-exact",
        category=Category.GPU,
        model="Example GPU",
        color="Black / Gray",
        source_id="11111111-1111-1111-1111-111111111111",
    )
    monkeypatch.setattr(specifications, "reported_colors", lambda: {"gpu-exact": entry})

    missing = build_specifications(Category.GPU, [], "gpu-exact")
    existing = build_specifications(
        Category.GPU, [{"dataset": "primary", "data": {"color": "White"}}], "gpu-exact"
    )

    assert missing["color"].value == "Black / Gray"
    assert missing["color"].status == "reported"
    assert missing["color"].evidence[0].dataset == "BuildCores OpenDB"
    assert existing["color"].value == "White"


def test_ram_name_with_missing_layout_does_not_invent_module_count() -> None:
    specs = build_specifications(
        Category.RAM,
        [
            {
                "dataset": "rohitmit98/pc-parts-by-type",
                "data": {
                    "name": "Example Memory DDR4-3200",
                    "type": "DDR4",
                    "size": "16",
                },
            }
        ],
    )

    assert specs["capacity_gb"].value == 16
    assert specs["memory_speed_mt_s"].value == 3200
    assert "module_count" not in specs
    assert "module_capacity_gb" not in specs
    assert "cas_latency" not in specs


def test_psu_missing_name_details_does_not_invent_certification_or_modularity() -> None:
    specs = build_specifications(
        Category.PSU,
        [{"dataset": "test", "data": {"name": "Example PSU", "power": "750", "size": "ATX"}}],
    )

    assert specs["wattage_w"].value == 750
    assert specs["form_factor"].value == "ATX"
    assert "efficiency_rating" not in specs
    assert "modularity" not in specs


def test_storage_capacity_uses_product_name_instead_of_truncated_space_column() -> None:
    specs = build_specifications(
        Category.STORAGE,
        [
            {
                "dataset": "test",
                "data": {
                    "name": "Seagate Exos X22 20 TB Internal Hard Drive (ST20000NM005E)",
                    "type": "HDD",
                    "space": "2000",
                },
            }
        ],
    )

    assert specs["storage_capacity_gb"].value == 20_000
    assert specs["storage_type"].value == "HDD"
