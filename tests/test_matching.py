"""Behavior tests for hardware identifier matching."""

from __future__ import annotations

import pytest

from scan_hardware.core.matching import match_items, normalize_identifier, search_items
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


def test_printed_board_code_matches_catalog_identifier_with_brand_prefix() -> None:
    correct = Item(
        id="board-z77x",
        category=Category.MOTHERBOARD,
        brand="Gigabyte",
        model="Gigabyte GA-Z77X-UD5H",
        identifiers=["Gigabyte GA-Z77X-UD5H"],
    )
    similar = Item(
        id="board-z170x",
        category=Category.MOTHERBOARD,
        brand="Gigabyte",
        model="Gigabyte GA-Z170X-UD5 TH",
        identifiers=["Gigabyte GA-Z170X-UD5 TH"],
    )

    result = match_items(["GA-Z77X-UD5H"], [similar, correct])

    assert result.status == "matched"
    assert [match.item.id for match in result.matches] == ["board-z77x"]
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


def test_short_board_code_does_not_match_prefix_of_longer_printed_code() -> None:
    generic = Item(
        id="board-generic",
        category=Category.MOTHERBOARD,
        brand="ASRock",
        model="ASRock A320M",
        identifiers=["A320M"],
    )

    result = match_items(["ASRock A320M-DVS"], [generic])

    assert result.status != "matched"


def test_printed_board_code_ranks_catalog_revision_before_similar_models() -> None:
    correct = Item(
        id="board-dvs",
        category=Category.MOTHERBOARD,
        brand="ASRock",
        model="ASRock A320M-DVS R4.0",
        identifiers=["A320M-DVS R4.0"],
    )
    similar = Item(
        id="board-dgs",
        category=Category.MOTHERBOARD,
        brand="ASRock",
        model="ASRock A320M-DGS",
        identifiers=["A320M-DGS"],
    )

    result = match_items(["A320M-DVS"], [similar, correct])

    assert result.status == "suggestions"
    assert result.matches[0].item.id == "board-dvs"


@pytest.mark.parametrize(
    ("observed", "expected_status"),
    [
        (["A320M-DVS", "REV. 4.02"], "matched"),
        (["A320M-DVS", "REV. 4.03"], "matched"),
        (["A320M-DVS"], "suggestions"),
        (["A320M-DVS", "REV. 4.04"], "suggestions"),
        (["A320M-DGS", "REV. 4.02"], "suggestions"),
    ],
)
def test_verified_asrock_pcb_revision_confirms_only_the_same_model(
    observed: list[str], expected_status: str
) -> None:
    item = Item(
        id="motherboard-6086912b15902278a564b9fc",
        category=Category.MOTHERBOARD,
        brand="ASRock",
        model="ASRock A320M-DVS R4.0",
        identifiers=["A320M-DVS R4.0"],
    )

    result = match_items(observed, [item])

    assert result.status == expected_status
    if expected_status == "matched":
        assert result.matches[0].item.id == item.id


def test_gpu_label_does_not_suggest_cpu_from_unrelated_serial_number() -> None:
    gpu = Item(
        id="gpu-1050",
        category=Category.GPU,
        brand="MSI",
        model="MSI GTX 1050 2G OC",
        identifiers=["GTX 1050 2G OC"],
    )
    cpu = Item(
        id="cpu-e8400",
        category=Category.CPU,
        brand="Intel",
        model="Intel Core 2 Duo E8400",
        identifiers=["E8400"],
    )

    result = match_items(["GeForce", "GTX 1050", "E8408"], [gpu, cpu])

    assert all(match.item.category is Category.GPU for match in result.matches)


def test_longer_exact_board_code_outranks_generic_prefix() -> None:
    generic = Item(
        id="board-generic",
        category=Category.MOTHERBOARD,
        brand="ASRock",
        model="ASRock A320M",
        identifiers=["A320M"],
    )
    specific = Item(
        id="board-dvs",
        category=Category.MOTHERBOARD,
        brand="ASRock",
        model="ASRock A320M-DVS",
        identifiers=["A320M-DVS"],
    )

    result = match_items(["ASRock A320M DVS"], [generic, specific])

    assert result.status == "matched"
    assert result.matches[0].item.id == "board-dvs"


def test_upside_down_gpu_label_lines_can_form_exact_model_code() -> None:
    gpu = Item(
        id="gpu-1050ti",
        category=Category.GPU,
        brand="MSI",
        model="MSI GTX 1050 Ti 4GT OC",
        identifiers=["GTX 1050 Ti 4GT OC"],
    )

    result = match_items(["OC", "Ti 4GT", "GTX 1050", "GeForce"], [gpu])

    assert result.status == "matched"
    assert result.matches[0].item.id == "gpu-1050ti"


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


@pytest.mark.parametrize(
    ("observed", "expected_first"),
    [
        ("BS5OM-A", "prime-b550"),
        ("PRIME BSSOM-A", "prime-b550"),
        ("TUF GAMING BSSO", "tuf-b550"),
    ],
)
def test_b550_ocr_letter_digit_confusion_stays_a_suggestion(
    observed: str, expected_first: str
) -> None:
    items = [
        Item(
            id="prime-b550",
            category=Category.MOTHERBOARD,
            brand="Asus",
            model="Asus PRIME B550M-A",
            identifiers=["PRIME B550M-A"],
        ),
        Item(
            id="tuf-b550",
            category=Category.MOTHERBOARD,
            brand="Asus",
            model="Asus TUF GAMING B550-PLUS",
            identifiers=["TUF GAMING B550-PLUS"],
        ),
        Item(
            id="asrock-b550",
            category=Category.MOTHERBOARD,
            brand="ASRock",
            model="ASRock B550M/ac",
            identifiers=["B550M/ac"],
        ),
        Item(
            id="tuf-b650",
            category=Category.MOTHERBOARD,
            brand="Asus",
            model="Asus TUF GAMING B650-PLUS",
            identifiers=["TUF GAMING B650-PLUS"],
        ),
    ]

    result = match_items([observed], items)

    assert result.status == "suggestions"
    assert result.matches[0].item.id == expected_first
    assert all(match.is_exact is False for match in result.matches)
    assert "tuf-b650" not in [match.item.id for match in result.matches]
    if "PRIME" in observed:
        assert "asrock-b550" not in [match.item.id for match in result.matches]


def test_short_ambiguous_b550_fragment_does_not_confirm_a_board() -> None:
    item = Item(
        id="tuf-b550",
        category=Category.MOTHERBOARD,
        brand="Asus",
        model="Asus TUF GAMING B550-PLUS",
        identifiers=["TUF GAMING B550-PLUS"],
    )

    result = match_items(["BSSO"], [item])

    assert result.status == "not_found"


def test_partial_bs500_search_ranks_related_b550_boards_without_false_confirmation() -> None:
    items = [
        Item(
            id="board-long",
            category=Category.MOTHERBOARD,
            brand="Asus",
            model="Asus TUF GAMING B550-PLUS",
            identifiers=["TUF GAMING B550-PLUS"],
        ),
        Item(
            id="board-short",
            category=Category.MOTHERBOARD,
            brand="ASRock",
            model="ASRock B550M",
            identifiers=["B550M"],
        ),
        Item(
            id="board-other",
            category=Category.MOTHERBOARD,
            brand="Asus",
            model="Asus B650M",
            identifiers=["B650M"],
        ),
    ]

    result = search_items("bs500", items)

    assert result.status == "suggestions"
    assert [match.item.id for match in result.matches] == ["board-short", "board-long"]
    assert all(match.is_exact is False for match in result.matches)
    assert result.matches[0].score > result.matches[1].score

    scanned = match_items(["BS500"], items)
    assert scanned.status == "suggestions"
    assert scanned.matches[0].item.id == "board-short"
    assert all(match.is_exact is False for match in scanned.matches)


def test_full_code_search_keeps_exact_model_ahead_of_related_models() -> None:
    correct = Item(
        id="board-z77x",
        category=Category.MOTHERBOARD,
        brand="Gigabyte",
        model="Gigabyte GA-Z77X-UD5H",
        identifiers=["GA-Z77X-UD5H"],
    )
    similar = Item(
        id="board-z170x",
        category=Category.MOTHERBOARD,
        brand="Gigabyte",
        model="Gigabyte GA-Z170X-UD5 TH",
        identifiers=["GA-Z170X-UD5 TH"],
    )

    result = search_items("GA-Z77X-UD5H", [similar, correct])

    assert result.status == "matched"
    assert [match.item.id for match in result.matches] == ["board-z77x"]


def test_cpu_family_prefix_is_removed_for_exact_i7_model_code() -> None:
    cpu = Item(
        id="cpu-8700k",
        category=Category.CPU,
        brand="Intel",
        model="Intel Core i7-8700K",
        identifiers=["Intel Core i7-8700K"],
    )

    result = search_items("i7-8700K", [cpu])

    assert result.status == "matched"
    assert result.matches[0].item.id == "cpu-8700k"


def test_ryzen_5600x_exact_code_does_not_mix_with_radeon_5600_xt() -> None:
    cpu = Item(
        id="cpu-5600x",
        category=Category.CPU,
        brand="AMD",
        model="AMD Ryzen 5 5600X",
        identifiers=["AMD Ryzen 5 5600X"],
    )
    gpu = Item(
        id="gpu-5600xt",
        category=Category.GPU,
        brand="ASRock",
        model="ASRock Radeon RX 5600 XT",
        identifiers=["RX5600XT CLD 6GO"],
    )

    result = search_items("5600X", [gpu, cpu])

    assert result.status == "matched"
    assert [match.item.id for match in result.matches] == ["cpu-5600x"]


def test_plain_rtx_3060_ranks_above_3060_ti_for_partial_chipset_code() -> None:
    plain = Item(
        id="gpu-3060",
        category=Category.GPU,
        brand="MSI",
        model="MSI GeForce RTX 3060 12GB",
        identifiers=["MSI GeForce RTX 3060 GAMING 12G"],
    )
    ti = Item(
        id="gpu-3060ti",
        category=Category.GPU,
        brand="MSI",
        model="MSI GeForce RTX 3060 Ti 8GB",
        identifiers=["MSI GeForce RTX 3060 Ti GAMING X"],
    )
    unrelated = Item(
        id="gpu-3070",
        category=Category.GPU,
        brand="MSI",
        model="MSI GeForce RTX 3070 8GB",
        identifiers=["MSI GeForce RTX 3070 GAMING X"],
    )

    result = search_items("RTX3060", [unrelated, ti, plain])

    assert result.status == "suggestions"
    assert [match.item.id for match in result.matches] == ["gpu-3060", "gpu-3060ti"]
    assert result.matches[0].score > result.matches[1].score


def test_complete_gpu_model_outranks_shared_chipset_fragment() -> None:
    specific = Item(
        id="gpu-pny",
        category=Category.GPU,
        brand="PNY",
        model="PNY VCG16504SSFPPB GeForce GTX 1650 SUPER",
        identifiers=["VCG16504SSFPPB"],
    )
    generic = Item(
        id="gpu-msi",
        category=Category.GPU,
        brand="MSI",
        model="MSI GeForce GTX 1650 SUPER",
        identifiers=["MSI GeForce GTX 1650 SUPER"],
    )

    result = search_items(specific.model, [generic, specific])

    assert result.status == "matched"
    assert result.matches[0].item.id == specific.id


def test_r9_290_partial_code_ranks_plain_gpu_before_290x() -> None:
    plain = Item(
        id="gpu-290",
        category=Category.GPU,
        brand="XFX",
        model="XFX DD Radeon R9 290",
        identifiers=["XFX DD Radeon R9 290"],
    )
    faster = Item(
        id="gpu-290x",
        category=Category.GPU,
        brand="MSI",
        model="MSI R9 290X Radeon R9 290X",
        identifiers=["MSI R9 290X Radeon R9 290X"],
    )

    result = search_items("R9 290", [faster, plain])

    assert result.status == "suggestions"
    assert result.matches[0].item.id == plain.id
    assert [match.item.id for match in result.matches] == [plain.id, faster.id]
