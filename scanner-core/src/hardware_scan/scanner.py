"""Read printed model codes and look them up in a small local catalog."""

from __future__ import annotations

import json
import re
from gzip import decompress
from io import BytesIO
from pathlib import Path
from typing import Protocol

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, TypeAdapter
from rapidocr import RapidOCR

MAX_IMAGE_BYTES = 10_000_000
MAX_IMAGE_PIXELS = 20_000_000


class Hardware(BaseModel):
    """One catalog item and the codes printed on its label or PCB."""

    id: str
    category: str
    brand: str
    model: str
    identifiers: list[str] = Field(min_length=1)
    specs: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    image_url: str | None = None


class ScanResult(BaseModel):
    """Recognized text and exact catalog candidates."""

    detected_text: list[str]
    matches: list[Hardware]


class OcrEngine(Protocol):
    """OCR callable used by the scanner."""

    def __call__(self, image: bytes) -> object:
        """Recognize an encoded image."""


def normalize(value: str) -> str:
    """Keep only uppercase ASCII letters and digits for code comparison."""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def load_catalog(path: Path) -> list[Hardware]:
    """Load and validate a JSON or gzip-compressed JSON catalog."""
    content = (
        decompress(path.read_bytes()).decode("utf-8")
        if path.suffix == ".gz"
        else path.read_text(encoding="utf-8")
    )
    data = json.loads(content)
    return TypeAdapter(list[Hardware]).validate_python(data)


def _contains_code(observation: str, code: str) -> bool:
    """Accept a complete code or a code followed by a PCB revision."""
    position = observation.find(code)
    if position < 0:
        return False
    suffix = observation[position + len(code) :]
    return not suffix or re.fullmatch(r"(?:V|REV|R)\d{1,3}", suffix) is not None


def match_text(lines: list[str], catalog: list[Hardware]) -> ScanResult:
    """Return items whose complete printed code appears in OCR text."""
    observations = [normalize(line) for line in lines]
    matches = [
        item
        for item in catalog
        if any(
            len(normalize(code)) >= 4
            and any(_contains_code(line, normalize(code)) for line in observations)
            for code in item.identifiers
        )
    ]
    return ScanResult(detected_text=lines, matches=matches)


class Scanner:
    """A small offline OCR adapter; an app supplies JPEG, PNG, or WebP bytes."""

    def __init__(self, engine: RapidOCR | OcrEngine | None = None) -> None:
        """Use the supplied OCR engine or load RapidOCR on first scan."""
        self._engine = engine

    def scan(self, image: bytes, catalog: list[Hardware]) -> ScanResult:
        """Validate a photo, recognize text, and look up printed codes."""
        if not image or len(image) > MAX_IMAGE_BYTES:
            raise ValueError("Image must contain between 1 and 10000000 bytes")
        try:
            with Image.open(BytesIO(image)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Only JPEG, PNG, and WebP images are supported")
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image exceeds 20 megapixels")
                source.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError("Image is corrupt or unsupported") from error
        engine = self._engine or RapidOCR()
        self._engine = engine
        output = engine(image)
        texts = getattr(output, "txts", None) or ()
        lines = [str(text).strip() for text in texts if str(text).strip()]
        return match_text(lines, catalog)
