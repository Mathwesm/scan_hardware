"""Read small, manufacturer-verified specification corrections."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel, Field, HttpUrl, model_validator

from scan_hardware.models.item import Category, ImageAttribution, SpecificationEvidence


class VerifiedFact(BaseModel):
    """A reviewed manufacturer fact for one stable imported item ID."""

    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    category: Category
    field: str
    value: str | int | float | bool
    unit: str | None = None
    source_url: HttpUrl

    @model_validator(mode="after")
    def validate_field(self) -> VerifiedFact:
        """Reject facts for a field that the category does not support."""
        from scan_hardware.core.specifications import SPEC_DEFINITIONS

        definition = SPEC_DEFINITIONS[self.category].get(self.field)
        if definition is None or definition.unit != self.unit:
            raise ValueError("Verified fact field or unit does not match its category")
        if isinstance(self.value, bool):
            valid_type = definition.kind == "boolean"
        elif isinstance(self.value, str):
            valid_type = definition.kind == "text" and bool(self.value.strip())
        elif isinstance(self.value, int):
            valid_type = definition.kind in {"integer", "decimal"} and self.value >= 0
        else:
            valid_type = definition.kind == "decimal" and self.value >= 0
        if not valid_type:
            raise ValueError("Verified fact value has the wrong type")
        return self

    def as_evidence(self) -> SpecificationEvidence:
        """Expose the manufacturer's source next to raw catalog evidence."""
        return SpecificationEvidence(
            dataset="manufacturer",
            field=self.field,
            value=self.value,
            source_url=str(self.source_url),
        )


class VerifiedManifest(BaseModel):
    """Validated set of reviewed facts shipped with the service."""

    facts: list[VerifiedFact]


class VerifiedImage(BaseModel):
    """A reviewed Commons photograph linked to one exact hardware model."""

    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    image_url: HttpUrl
    creator: str = Field(min_length=1)
    source_url: HttpUrl
    license_name: str = "CC BY-SA 4.0"
    license_url: HttpUrl = HttpUrl("https://creativecommons.org/licenses/by-sa/4.0/")

    def attribution(self) -> ImageAttribution:
        """Expose credit fields in the item response."""
        return ImageAttribution(
            creator=self.creator,
            source_url=str(self.source_url),
            license_name=self.license_name,
            license_url=str(self.license_url),
        )


class ImageManifest(BaseModel):
    """Validated small list of curated product photographs."""

    images: list[VerifiedImage]


@lru_cache(maxsize=1)
def verified_facts() -> dict[tuple[str, str], VerifiedFact]:
    """Load immutable reviewed facts from the packaged UTF-8 manifest."""
    path = files("scan_hardware").joinpath("curation", "verified_specs.json")
    manifest = VerifiedManifest.model_validate_json(path.read_text(encoding="utf-8"))
    facts: dict[tuple[str, str], VerifiedFact] = {}
    for fact in manifest.facts:
        key = (fact.item_id, fact.field)
        if key in facts:
            raise ValueError(f"Duplicate verified fact: {key}")
        facts[key] = fact
    return facts


@lru_cache(maxsize=1)
def verified_images() -> dict[str, VerifiedImage]:
    """Load curated image references with creator and license details."""
    path = files("scan_hardware").joinpath("curation", "verified_images.json")
    manifest = ImageManifest.model_validate_json(path.read_text(encoding="utf-8"))
    images: dict[str, VerifiedImage] = {}
    for image in manifest.images:
        if image.item_id in images:
            raise ValueError(f"Duplicate verified image: {image.item_id}")
        images[image.item_id] = image
    return images
