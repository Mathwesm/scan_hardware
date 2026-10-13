"""Read small, manufacturer-verified specification corrections."""

from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel, Field, HttpUrl, model_validator

from scan_hardware.models.item import Category, ImageAttribution, ItemInput, SpecificationEvidence

# Public BuildCores Git commit, not a credential.
BUILDCORES_REVISION = "0d3c3eaf220173aa4246916e3d7a226079e87a65"  # pragma: allowlist secret


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
    """An exact-model image with explicit licensing state."""

    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    image_url: HttpUrl
    creator: str = Field(min_length=1)
    source_url: HttpUrl
    license_name: str | None = "CC BY-SA 4.0"
    license_url: HttpUrl | None = HttpUrl("https://creativecommons.org/licenses/by-sa/4.0/")

    @model_validator(mode="after")
    def validate_license(self) -> VerifiedImage:
        """Require a license name and URL together when rights are known."""
        if (self.license_name is None) != (self.license_url is None):
            raise ValueError("Image license name and URL must both be present or absent")
        return self

    def attribution(self) -> ImageAttribution | None:
        """Expose credit only when reuse rights have been identified."""
        if self.license_name is None or self.license_url is None:
            return None
        return ImageAttribution(
            creator=self.creator,
            source_url=str(self.source_url),
            license_name=self.license_name,
            license_url=str(self.license_url),
        )


class ImageManifest(BaseModel):
    """Validated small list of curated product photographs."""

    images: list[VerifiedImage]


class EstimatedColor(BaseModel):
    """Approximate color extracted from an exact item's local reference photo."""

    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    category: Category
    model: str = Field(min_length=1)
    color: str = Field(min_length=1)


class EstimatedColorManifest(BaseModel):
    """Validated local-photo estimates that do not override source facts."""

    colors: list[EstimatedColor]


class ReportedColor(BaseModel):
    """Source-reported color joined by one exact manufacturer part number."""

    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    category: Category
    model: str = Field(min_length=1)
    color: str = Field(min_length=1)
    source_id: str = Field(pattern=r"^[a-f0-9-]{36}$")

    def as_evidence(self) -> SpecificationEvidence:
        """Link the reported color to its pinned OpenDB record."""
        folder = "GPU" if self.category is Category.GPU else "Motherboard"
        source_url = (
            "https://github.com/buildcores/buildcores-open-db/blob/"
            f"{BUILDCORES_REVISION}/open-db/{folder}/{self.source_id}.json"
        )
        return SpecificationEvidence(
            dataset="BuildCores OpenDB", field="color", value=self.color, source_url=source_url
        )


class ReportedColorManifest(BaseModel):
    """Versioned noncommercial color data from BuildCores OpenDB."""

    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    colors: list[ReportedColor]


class ReportedSpec(BaseModel):
    """Source-reported specification joined by exact manufacturer part number."""

    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    category: Category
    model: str = Field(min_length=1)
    field: str
    value: str | int | float | bool
    unit: str | None = None
    source_id: str = Field(pattern=r"^[a-f0-9-]{36}$")

    @model_validator(mode="after")
    def validate_specification(self) -> ReportedSpec:
        """Require a supported field, value type, and unit."""
        from scan_hardware.core.specifications import SPEC_DEFINITIONS

        definition = SPEC_DEFINITIONS[self.category].get(self.field)
        if definition is None or definition.unit != self.unit:
            raise ValueError("Reported specification field or unit is invalid")
        if isinstance(self.value, bool):
            valid = definition.kind == "boolean"
        elif isinstance(self.value, str):
            valid = definition.kind == "text" and bool(self.value.strip())
        elif isinstance(self.value, int):
            valid = definition.kind in {"integer", "decimal"} and self.value >= 0
        else:
            valid = definition.kind == "decimal" and self.value >= 0
        if not valid:
            raise ValueError("Reported specification value has the wrong type")
        return self

    def as_evidence(self) -> SpecificationEvidence:
        """Link the value to the pinned OpenDB source record."""
        folder = {
            Category.CPU: "CPU",
            Category.GPU: "GPU",
            Category.MOTHERBOARD: "Motherboard",
        }[self.category]
        source_url = (
            "https://github.com/buildcores/buildcores-open-db/blob/"
            f"{BUILDCORES_REVISION}/open-db/{folder}/{self.source_id}.json"
        )
        return SpecificationEvidence(
            dataset="BuildCores OpenDB",
            field=self.field,
            value=self.value,
            source_url=source_url,
        )


class ReportedSpecManifest(BaseModel):
    """Versioned noncommercial specification data from BuildCores OpenDB."""

    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    specs: list[ReportedSpec]


class VerifiedBoardRevision(BaseModel):
    """Manufacturer-confirmed PCB revisions within one catalog model family."""

    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    catalog_model: str = Field(min_length=4)
    model_code: str = Field(min_length=4)
    pcb_revisions: tuple[str, ...] = Field(min_length=1)
    source_url: HttpUrl

    @model_validator(mode="after")
    def validate_revisions(self) -> VerifiedBoardRevision:
        """Require distinct, fully specified printed revision numbers."""
        if len(set(self.pcb_revisions)) != len(self.pcb_revisions) or any(
            re.fullmatch(r"\d+\.\d{2}", revision) is None for revision in self.pcb_revisions
        ):
            raise ValueError("PCB revisions must be distinct major.minor codes")
        return self


class BoardRevisionManifest(BaseModel):
    """Reviewed PCB revision families shipped with the package."""

    boards: list[VerifiedBoardRevision]


class SupplementalItem(BaseModel):
    """A source-backed product missing from both imported Kaggle archives."""

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    item: ItemInput
    source_url: HttpUrl


class SupplementalManifest(BaseModel):
    """Validated products to add after the Kaggle import."""

    items: list[SupplementalItem]


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
    """Load exact-model image references and their licensing state."""
    path = files("scan_hardware").joinpath("curation", "verified_images.json")
    manifest = ImageManifest.model_validate_json(path.read_text(encoding="utf-8"))
    images: dict[str, VerifiedImage] = {}
    for image in manifest.images:
        if image.item_id in images:
            raise ValueError(f"Duplicate verified image: {image.item_id}")
        images[image.item_id] = image
    return images


@lru_cache(maxsize=1)
def estimated_colors() -> dict[str, EstimatedColor]:
    """Load optional color estimates generated from local reference images."""
    path = files("scan_hardware").joinpath("curation", "estimated_colors.json")
    if not path.is_file():
        return {}
    manifest = EstimatedColorManifest.model_validate_json(path.read_text(encoding="utf-8"))
    colors: dict[str, EstimatedColor] = {}
    for entry in manifest.colors:
        if entry.item_id in colors:
            raise ValueError(f"Duplicate estimated color: {entry.item_id}")
        colors[entry.item_id] = entry
    return colors


@lru_cache(maxsize=1)
def reported_colors() -> dict[str, ReportedColor]:
    """Load exact-part-number colors from the separately licensed manifest."""
    path = files("scan_hardware").joinpath("curation", "reported_colors.json")
    if not path.is_file():
        return {}
    manifest = ReportedColorManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if manifest.revision != BUILDCORES_REVISION:
        raise ValueError("Reported color manifest uses an unexpected source revision")
    colors: dict[str, ReportedColor] = {}
    for entry in manifest.colors:
        if entry.item_id in colors:
            raise ValueError(f"Duplicate reported color: {entry.item_id}")
        colors[entry.item_id] = entry
    return colors


@lru_cache(maxsize=1)
def reported_specs() -> dict[tuple[str, str], ReportedSpec]:
    """Load exact-part-number specifications from the pinned OpenDB revision."""
    path = files("scan_hardware").joinpath("curation", "reported_specs.json")
    if not path.is_file():
        return {}
    manifest = ReportedSpecManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if manifest.revision != BUILDCORES_REVISION:
        raise ValueError("Reported specification manifest uses an unexpected source revision")
    specs: dict[tuple[str, str], ReportedSpec] = {}
    for entry in manifest.specs:
        key = (entry.item_id, entry.field)
        if key in specs:
            raise ValueError(f"Duplicate reported specification: {key}")
        specs[key] = entry
    return specs


@lru_cache(maxsize=1)
def verified_board_revisions() -> dict[str, VerifiedBoardRevision]:
    """Load manufacturer-backed PCB revisions for exact model confirmation."""
    path = files("scan_hardware").joinpath("curation", "verified_revisions.json")
    manifest = BoardRevisionManifest.model_validate_json(path.read_text(encoding="utf-8"))
    boards: dict[str, VerifiedBoardRevision] = {}
    for board in manifest.boards:
        if board.item_id in boards:
            raise ValueError(f"Duplicate board revision: {board.item_id}")
        boards[board.item_id] = board
    return boards


@lru_cache(maxsize=1)
def supplemental_items() -> tuple[SupplementalItem, ...]:
    """Load reviewed missing products from the packaged UTF-8 manifest."""
    path = files("scan_hardware").joinpath("curation", "supplemental_items.json")
    manifest = SupplementalManifest.model_validate_json(path.read_text(encoding="utf-8"))
    ids = [item.id for item in manifest.items]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate supplemental item ID")
    return tuple(manifest.items)
