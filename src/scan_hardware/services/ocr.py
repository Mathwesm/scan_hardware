"""Offline optical character recognition for hardware labels."""

from __future__ import annotations

from io import BytesIO
from threading import Lock

from PIL import Image, UnidentifiedImageError
from rapidocr import RapidOCR
from rapidocr.utils.output import RapidOCROutput

MAX_IMAGE_PIXELS = 20_000_000


class InvalidImageError(Exception):
    """Uploaded bytes are not a supported or reasonably sized image."""


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
        if not isinstance(result, RapidOCROutput) or result.txts is None:
            return []
        scores = result.scores or ()
        return [
            line.strip()
            for line, score in zip(result.txts, scores, strict=True)
            if line.strip() and score >= self.min_confidence
        ]
