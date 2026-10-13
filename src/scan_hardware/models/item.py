"""Validated API models for catalog items and scan results."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, HttpUrl, field_validator


class Category(StrEnum):
    """Supported hardware categories."""

    MOTHERBOARD = "motherboard"
    GPU = "gpu"
    CPU = "cpu"


class ItemInput(BaseModel):
    """Data required to register one hardware item."""

    category: Category
    brand: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    identifiers: list[str] = Field(min_length=1, max_length=30)
    image_url: HttpUrl | None = None

    @field_validator("brand", "model")
    @classmethod
    def strip_text(cls, value: str) -> str:
        """Reject whitespace-only display values."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value must contain non-whitespace characters")
        return stripped

    @field_validator("identifiers")
    @classmethod
    def validate_identifiers(cls, values: list[str]) -> list[str]:
        """Require meaningful, distinct part identifiers."""
        from scan_hardware.core.matching import MIN_IDENTIFIER_LENGTH, normalize_identifier

        normalized = [normalize_identifier(value) for value in values]
        if any(len(value) < MIN_IDENTIFIER_LENGTH for value in normalized):
            raise ValueError("Each identifier must contain at least four letters or digits")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Identifiers must be unique after normalization")
        return [value.strip() for value in values]


class SpecificationEvidence(BaseModel):
    """A distinct value retained from one imported source field."""

    dataset: str
    field: str
    value: str | int | float | bool
    source_url: str | None = None


class Specification(BaseModel):
    """A normalized hardware property with transparent source disagreement."""

    value: str | int | float | bool | None
    unit: str | None = None
    status: Literal["reported", "conflict", "verified"]
    evidence: list[SpecificationEvidence] = Field(default_factory=list, exclude=True)


class ImageAttribution(BaseModel):
    """Credit and license for a manually reviewed reference photograph."""

    creator: str
    source_url: str
    license_name: str
    license_url: str


class GalleryImage(BaseModel):
    """One local product view or an unreviewed external reference."""

    url: str
    view: Literal["front", "side", "back", "detail", "other"]
    is_primary: bool
    source: Literal["local", "external"]
    width: int | None = None
    height: int | None = None


class Item(ItemInput):
    """Catalog item with a stable external identifier and image endpoint."""

    id: str
    has_local_image: bool = False
    local_image_url: str | None = None
    image_attribution: ImageAttribution | None = None
    specifications: dict[str, Specification] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("specs", "specifications"),
        serialization_alias="specs",
    )


class Match(BaseModel):
    """A catalog candidate with its matching evidence."""

    item: Item = Field(
        validation_alias=AliasChoices("hardware", "item"), serialization_alias="hardware"
    )
    matched_identifier: str
    observed_text: str | None = Field(default=None, exclude=True)
    score: float = Field(ge=0, le=1)
    is_exact: bool


class ScanResult(BaseModel):
    """OCR output and ordered catalog matches."""

    status: str
    detected_text: list[str]
    matches: list[Match]


class HardwareSummary(BaseModel):
    """Small, flat hardware record intended for mobile clients."""

    category: Category
    brand: str
    model: str
    image_url: str | None = None
    id: str
    socket: str | None = None
    form_factor: str | None = None
    max_memory_gb: int | None = None
    memory_slots: int | None = None
    memory_type: str | None = None
    memory_slot_type: str | None = None
    memory_channels: int | None = None
    max_memory_standard_mhz: int | None = None
    max_memory_oc_mhz: int | None = None
    memory_speed_mt_s: int | None = None
    l2_cache_mb: float | None = None
    l3_cache_mb: float | None = None
    color: str | None = None
    color_source: Literal["catalog", "photo_estimate", "reference_estimate"] | None = None
    base_clock_ghz: float | None = None
    boost_clock_ghz: float | None = None
    cores: int | None = None
    threads: int | None = None
    tdp_w: int | None = None
    integrated_graphics: str | None = None
    smt: bool | None = None
    chipset: str | None = None
    vram_gb: int | None = None
    memory_speed_mhz: int | None = None
    memory_bus_bits: int | None = None
    shader_units: int | None = None
    core_clock_mhz: int | None = None
    boost_clock_mhz: int | None = None
    board_power_w: int | None = None
    length_mm: int | None = None
    resolution_class: str | None = None

    @classmethod
    def from_match(cls, match: Match, photo_color: str | None = None) -> HardwareSummary:
        """Keep unambiguous catalog values and mark visual color estimates.

        Args:
            match: Matched catalog item with source-backed specifications.
            photo_color: Broad color inferred from the uploaded photo, if any.

        Returns:
            Flat hardware response for mobile clients.
        """
        item = match.item
        values: dict[str, object] = {
            "category": item.category,
            "brand": item.brand,
            "model": item.model,
            "image_url": item.local_image_url or (str(item.image_url) if item.image_url else None),
            "id": item.id,
        }
        for key, specification in item.specifications.items():
            if specification.status != "conflict" and specification.value is not None:
                values[key] = specification.value
        if "color" in values:
            values["color_source"] = "catalog"
        elif photo_color is not None and item.category in {Category.GPU, Category.MOTHERBOARD}:
            values["color"] = photo_color
            values["color_source"] = "photo_estimate"
        elif item.category in {Category.GPU, Category.MOTHERBOARD}:
            from scan_hardware.curation import estimated_colors

            estimate = estimated_colors().get(item.id)
            if (
                estimate is not None
                and estimate.category is item.category
                and estimate.model == item.model
            ):
                values["color"] = estimate.color
                values["color_source"] = "reference_estimate"
        return cls.model_validate(values)


class ScanResponse(BaseModel):
    """Scanner status and a list of flat candidate records."""

    status: Literal["matched", "suggestions", "not_found"]
    matches: list[HardwareSummary]

    @classmethod
    def from_result(cls, result: ScanResult, photo_color: str | None = None) -> ScanResponse:
        """Present matches and optional photo color without nested specifications.

        Args:
            result: Scanner result with candidate items.
            photo_color: Broad visual estimate for candidates lacking catalog color.

        Returns:
            Flat scan response.
        """
        return cls(
            status=result.status,
            matches=[HardwareSummary.from_match(match, photo_color) for match in result.matches],
        )
