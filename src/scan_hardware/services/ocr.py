"""Offline optical character recognition for hardware labels."""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from threading import Lock

from PIL import Image, ImageOps, UnidentifiedImageError
from rapidocr import RapidOCR
from rapidocr.utils.output import RapidOCROutput

MAX_IMAGE_PIXELS = 20_000_000
MIN_MODEL_CODE_LENGTH = 5
MIN_MODEL_CODE_DIGITS = 2


class InvalidImageError(Exception):
    """Uploaded bytes are not a supported or reasonably sized image."""


def _recognized_lines(result: object, min_confidence: float) -> list[str]:
    """Keep recognized lines that pass the confidence floor."""
    if not isinstance(result, RapidOCROutput) or result.txts is None:
        return []
    scores = result.scores or ()
    return [
        line.strip()
        for line, score in zip(result.txts, scores, strict=True)
        if line.strip() and score >= min_confidence
    ]


def _has_model_code(lines: list[str]) -> bool:
    """Check whether OCR found a plausible letter-and-digit model code."""
    for line in lines:
        code = "".join(
            character for character in line if character.isascii() and character.isalnum()
        )
        if (
            len(code) >= MIN_MODEL_CODE_LENGTH
            and sum(character.isdigit() for character in code) >= MIN_MODEL_CODE_DIGITS
            and any(character.isalpha() for character in code)
        ):
            return True
    return False


def _inverted_bands(content: bytes) -> Iterator[bytes]:
    """Expose dark-board lettering at a larger OCR scale."""
    with Image.open(BytesIO(content)) as source:
        grayscale = ImageOps.grayscale(source)
    band_height = max(1, grayscale.height // 2)
    center = (grayscale.height - band_height) // 2
    for top in dict.fromkeys((center, 0, grayscale.height - band_height)):
        band = ImageOps.invert(grayscale.crop((0, top, grayscale.width, top + band_height)))
        output = BytesIO()
        band.save(output, format="PNG")
        yield output.getvalue()


def validate_image(content: bytes, max_bytes: int) -> None:
    """Reject empty, oversized, corrupt, or decompression-bomb images.

    Args:
        content: Uploaded image bytes.
        max_bytes: Maximum accepted upload size.

    Raises:
        InvalidImageError: The image cannot be processed safely.
    """
    if not content or len(content) > max_bytes:
        raise InvalidImageError(f"Image must contain between 1 and {max_bytes} bytes")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise InvalidImageError("Only JPEG, PNG, and WebP images are supported")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise InvalidImageError("Image exceeds the 20 megapixel limit")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise InvalidImageError("Image is corrupt or unsupported") from error


class OcrScanner:
    """Run a local ONNX OCR model with serialized inference calls."""

    def __init__(self, min_confidence: float = 0.4) -> None:
        """Configure the OCR confidence floor without loading the model yet."""
        self.min_confidence = min_confidence
        self._engine: RapidOCR | None = None
        self._lock = Lock()

    def read_text(self, content: bytes) -> list[str]:
        """Recognize text in an already validated image.

        Args:
            content: Encoded image bytes.

        Returns:
            OCR lines above the configured confidence floor.
        """
        with self._lock:
            if self._engine is None:
                self._engine = RapidOCR()
            result = self._engine(content)
            lines = _recognized_lines(result, self.min_confidence)
            if not _has_model_code(lines):
                for band in _inverted_bands(content):
                    lines.extend(_recognized_lines(self._engine(band), self.min_confidence))
                    if _has_model_code(lines):
                        break
        return list(dict.fromkeys(lines))
