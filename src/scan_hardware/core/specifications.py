"""Normalize imported hardware specifications without hiding source conflicts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from scan_hardware.models.item import Category, Specification, SpecificationEvidence

ValueKind = Literal["text", "integer", "decimal", "boolean"]
SpecValue = str | int | float | bool


class SourceRecord(BaseModel):
    """Validate the stored source envelope while keeping original columns."""

    model_config = ConfigDict(extra="ignore")

    dataset: str
    data: dict[str, Any]


@dataclass(frozen=True)
class SpecDefinition:
    """Describe equivalent source columns and the output unit."""

    fields: tuple[str, ...]
    kind: ValueKind
    unit: str | None = None


SPEC_DEFINITIONS: dict[Category, dict[str, SpecDefinition]] = {
    Category.CPU: {
        "socket": SpecDefinition(("socket",), "text"),
        "base_clock_ghz": SpecDefinition(("speed", "core_clock"), "decimal", "GHz"),
        "boost_clock_ghz": SpecDefinition(("boost_clock",), "decimal", "GHz"),
        "cores": SpecDefinition(("coreCount", "core_count"), "integer"),
        "threads": SpecDefinition(("threadCount",), "integer"),
        "tdp_w": SpecDefinition(("power", "tdp"), "integer", "W"),
        "integrated_graphics": SpecDefinition(("graphics",), "text"),
        "smt": SpecDefinition(("smt",), "boolean"),
    },
    Category.GPU: {
        "chipset": SpecDefinition(("chipset",), "text"),
        "vram_gb": SpecDefinition(("VRAM", "memory"), "integer", "GB"),
        "core_clock_mhz": SpecDefinition(("core_clock",), "integer", "MHz"),
        "boost_clock_mhz": SpecDefinition(("boost_clock",), "integer", "MHz"),
        "board_power_w": SpecDefinition(("power",), "integer", "W"),
        "length_mm": SpecDefinition(("length",), "integer", "mm"),
        "resolution_class": SpecDefinition(("resolution",), "text"),
        "color": SpecDefinition(("color",), "text"),
    },
    Category.MOTHERBOARD: {
        "socket": SpecDefinition(("socket",), "text"),
        "form_factor": SpecDefinition(("size", "form_factor"), "text"),
        "max_memory_gb": SpecDefinition(("max_memory",), "integer", "GB"),
        "memory_slots": SpecDefinition(("memory_slots",), "integer"),
        "color": SpecDefinition(("color",), "text"),
    },
}


def _parse_number(raw: Any, kind: ValueKind) -> int | float | None:
    """Reject invalid or negative source numbers before reporting them."""
    if isinstance(raw, bool):
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if kind == "integer":
        return int(number) if number.is_integer() else None
    return number


def _parse_value(raw: Any, definition: SpecDefinition, key: str) -> SpecValue | None:
    """Convert a source cell into a stable comparable value."""
    if definition.kind == "text":
        if not isinstance(raw, str) or not raw.strip():
            return None
        value = raw.strip()
        return re.sub(r"\s+", "", value.upper()) if key == "socket" else value
    if definition.kind == "boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.casefold() in {"true", "false"}:
            return raw.casefold() == "true"
        return None
    return _parse_number(raw, definition.kind)


def build_specifications(
    category: Category, source_rows: list[dict[str, Any]]
) -> dict[str, Specification]:
    """Build one specification map from source rows with conflict evidence.

    Args:
        category: Hardware category whose field mappings apply.
        source_rows: Original rows returned by the local catalog.

    Returns:
        Normalized fields; conflicting values have a null value and all evidence.
    """
    sources = [SourceRecord.model_validate(row) for row in source_rows]
    specifications: dict[str, Specification] = {}
    for key, definition in SPEC_DEFINITIONS[category].items():
        evidence_map: dict[tuple[str, str, SpecValue], SpecificationEvidence] = {}
        for source in sources:
            for field in definition.fields:
                value = _parse_value(source.data.get(field), definition, key)
                if value is not None:
                    evidence_map[(source.dataset, field, value)] = SpecificationEvidence(
                        dataset=source.dataset, field=field, value=value
                    )
        if not evidence_map:
            continue
        evidence = [evidence_map[index] for index in sorted(evidence_map, key=str)]
        values = {entry.value for entry in evidence}
        is_conflict = len(values) > 1
        specifications[key] = Specification(
            value=None if is_conflict else evidence[0].value,
            unit=definition.unit,
            status="conflict" if is_conflict else "reported",
            evidence=evidence,
        )
    return specifications
