"""Normalize imported hardware specifications without hiding source conflicts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from scan_hardware.curation import reported_colors, reported_specs, verified_facts
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
    Category.CASE: {"form_factor": SpecDefinition(("size",), "text")},
    Category.COOLER: {"cooling_type": SpecDefinition(("type",), "text")},
    Category.STORAGE: {
        "storage_type": SpecDefinition(("type",), "text"),
        "storage_capacity_gb": SpecDefinition(("name",), "integer", "GB"),
    },
    Category.PSU: {
        "wattage_w": SpecDefinition(("power",), "integer", "W"),
        "form_factor": SpecDefinition(("size",), "text"),
        "efficiency_rating": SpecDefinition(("name",), "text"),
        "modularity": SpecDefinition(("name",), "text"),
    },
    Category.RAM: {
        "capacity_gb": SpecDefinition(("size",), "integer", "GB"),
        "module_count": SpecDefinition(("name",), "integer"),
        "module_capacity_gb": SpecDefinition(("name",), "integer", "GB"),
        "memory_type": SpecDefinition(("type",), "text"),
        "memory_speed_mt_s": SpecDefinition(("name",), "integer", "MT/s"),
        "cas_latency": SpecDefinition(("name",), "integer"),
    },
    Category.CPU: {
        "socket": SpecDefinition(("socket",), "text"),
        "base_clock_ghz": SpecDefinition(("speed", "core_clock"), "decimal", "GHz"),
        "boost_clock_ghz": SpecDefinition(("boost_clock",), "decimal", "GHz"),
        "cores": SpecDefinition(("coreCount", "core_count"), "integer"),
        "threads": SpecDefinition(("threadCount",), "integer"),
        "tdp_w": SpecDefinition(("power", "tdp"), "integer", "W"),
        "integrated_graphics": SpecDefinition(("graphics",), "text"),
        "smt": SpecDefinition(("smt",), "boolean"),
        "memory_type": SpecDefinition((), "text"),
        "memory_speed_mt_s": SpecDefinition((), "integer", "MT/s"),
        "l2_cache_mb": SpecDefinition((), "decimal", "MB"),
        "l3_cache_mb": SpecDefinition((), "decimal", "MB"),
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
        "memory_type": SpecDefinition((), "text"),
        "memory_speed_mhz": SpecDefinition((), "integer", "MHz"),
        "memory_bus_bits": SpecDefinition((), "integer", "bit"),
        "shader_units": SpecDefinition((), "integer"),
    },
    Category.MOTHERBOARD: {
        "socket": SpecDefinition(("socket",), "text"),
        "form_factor": SpecDefinition(("size", "form_factor"), "text"),
        "max_memory_gb": SpecDefinition(("max_memory",), "integer", "GB"),
        "memory_slots": SpecDefinition(("memory_slots",), "integer"),
        "memory_type": SpecDefinition((), "text"),
        "max_memory_standard_mhz": SpecDefinition((), "integer", "MHz"),
        "max_memory_oc_mhz": SpecDefinition((), "integer", "MHz"),
        "memory_slot_type": SpecDefinition((), "text"),
        "memory_channels": SpecDefinition((), "integer"),
        "color": SpecDefinition(("color",), "text"),
    },
}

_RAM_MODULES = re.compile(r"\b(\d+)\s*[xX]\s*(\d+)\s*GB\b", re.IGNORECASE)
_RAM_SPEED = re.compile(r"\bDDR[345]\s*[- ]\s*(\d{3,5})\b", re.IGNORECASE)
_RAM_CAS = re.compile(r"\bCL\s*(\d{1,3})\b", re.IGNORECASE)
_PSU_EFFICIENCY = re.compile(
    r"\b80\s*\+\s*(Titanium|Platinum|Gold|Silver|Bronze|White)\b", re.IGNORECASE
)
_PSU_MODULARITY = re.compile(r"\b(Fully Modular|Semi[- ]Modular|Non[- ]Modular)\b", re.IGNORECASE)
_STORAGE_CAPACITY = re.compile(r"\b(\d+(?:\.\d+)?)\s*(TB|GB)\b", re.IGNORECASE)


def _parse_psu_name_value(raw: Any, key: str) -> str | None:
    """Extract explicitly printed PSU efficiency and cabling type."""
    if not isinstance(raw, str):
        return None
    pattern = _PSU_EFFICIENCY if key == "efficiency_rating" else _PSU_MODULARITY
    match = pattern.search(raw)
    if match is None:
        return None
    if key == "efficiency_rating":
        return f"80+ {match.group(1).title()}"
    return match.group(1).replace("-", " ").title()


def _parse_storage_capacity(raw: Any) -> int | None:
    """Read stated GB or TB capacity; the source's `space` column is truncated."""
    if not isinstance(raw, str):
        return None
    match = _STORAGE_CAPACITY.search(raw)
    if match is None:
        return None
    amount = float(match.group(1)) * (1000 if match.group(2).upper() == "TB" else 1)
    return int(amount) if amount.is_integer() else None


def _parse_ram_name_value(raw: Any, key: str) -> int | None:
    """Extract kit layout, transfer rate, and CAS latency from a RAM product name."""
    if not isinstance(raw, str):
        return None
    if key in {"module_count", "module_capacity_gb"}:
        match = _RAM_MODULES.search(raw)
        if match is None:
            return None
        return int(match.group(1 if key == "module_count" else 2))
    pattern = _RAM_SPEED if key == "memory_speed_mt_s" else _RAM_CAS
    match = pattern.search(raw)
    return int(match.group(1)) if match is not None else None


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


def _comparison_value(key: str, value: SpecValue) -> SpecValue | tuple[str, ...]:
    """Treat order-independent color lists as the same reported color."""
    if key == "color" and isinstance(value, str):
        return tuple(sorted(part.strip().casefold() for part in value.split("/")))
    return value


def build_specifications(
    category: Category, source_rows: list[dict[str, Any]], item_id: str | None = None
) -> dict[str, Specification]:
    """Build one specification map from source rows with conflict evidence.

    Args:
        category: Hardware category whose field mappings apply.
        source_rows: Original rows returned by the local catalog.
        item_id: Stable catalog ID for reviewed manufacturer facts.

    Returns:
        Normalized fields; conflicting values have a null value and all evidence.
    """
    sources = [SourceRecord.model_validate(row) for row in source_rows]
    specifications: dict[str, Specification] = {}
    for key, definition in SPEC_DEFINITIONS[category].items():
        evidence_map: dict[tuple[str, str, SpecValue], SpecificationEvidence] = {}
        for source in sources:
            for field in definition.fields:
                value = (
                    _parse_ram_name_value(source.data.get(field), key)
                    if category is Category.RAM and field == "name"
                    else (
                        _parse_psu_name_value(source.data.get(field), key)
                        if category is Category.PSU and field == "name"
                        else (
                            _parse_storage_capacity(source.data.get(field))
                            if category is Category.STORAGE and field == "name"
                            else _parse_value(source.data.get(field), definition, key)
                        )
                    )
                )
                if value is not None:
                    evidence_map[(source.dataset, field, value)] = SpecificationEvidence(
                        dataset=source.dataset, field=field, value=value
                    )
        fact = verified_facts().get((item_id, key)) if item_id is not None else None
        reported = (
            reported_colors().get(item_id) if item_id is not None and key == "color" else None
        )
        reported_spec = reported_specs().get((item_id, key)) if item_id is not None else None
        if not evidence_map and fact is None:
            if reported is not None and reported.category is category:
                specifications[key] = Specification(
                    value=reported.color,
                    unit=definition.unit,
                    status="reported",
                    evidence=[reported.as_evidence()],
                )
            elif reported_spec is not None and reported_spec.category is category:
                specifications[key] = Specification(
                    value=reported_spec.value,
                    unit=definition.unit,
                    status="reported",
                    evidence=[reported_spec.as_evidence()],
                )
            continue
        evidence = [evidence_map[index] for index in sorted(evidence_map, key=str)]
        if fact is not None and fact.category is category:
            specifications[key] = Specification(
                value=fact.value,
                unit=definition.unit,
                status="verified",
                evidence=[*evidence, fact.as_evidence()],
            )
            continue
        values = {_comparison_value(key, entry.value) for entry in evidence}
        is_conflict = len(values) > 1
        specifications[key] = Specification(
            value=None if is_conflict else evidence[0].value,
            unit=definition.unit,
            status="conflict" if is_conflict else "reported",
            evidence=evidence,
        )
    return specifications
