"""Validated API models for catalog items and scan results."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


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


class Specification(BaseModel):
    """A normalized hardware property with transparent source disagreement."""

    value: str | int | float | bool | None
    unit: str | None = None
    status: Literal["reported", "conflict"]
    evidence: list[SpecificationEvidence]


class Item(ItemInput):
    """Catalog item with a stable external identifier and image endpoint."""

    id: str
    has_local_image: bool = False
    local_image_url: str | None = None
    specifications: dict[str, Specification] = Field(default_factory=dict)


class Match(BaseModel):
    """A catalog candidate with its matching evidence."""

    item: Item
    matched_identifier: str
    observed_text: str
    score: float = Field(ge=0, le=1)
    is_exact: bool


class ScanResult(BaseModel):
    """OCR output and ordered catalog matches."""

    status: str
    detected_text: list[str]
    matches: list[Match]
