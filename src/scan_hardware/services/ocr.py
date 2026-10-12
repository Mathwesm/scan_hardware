"""Offline optical character recognition for hardware labels."""

from __future__ import annotations

import re
from collections.abc import Iterator
from io import BytesIO
from itertools import pairwise
from threading import Lock

from PIL import Image, ImageOps, UnidentifiedImageError
from rapidocr import RapidOCR
from rapidocr.utils.output import RapidOCROutput

from scan_hardware.core.matching import normalize_identifier
from scan_hardware.curation import VerifiedBoardRevision, verified_board_revisions

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


def _revision_crops(
    content: bytes, result: RapidOCROutput, confidence: float
) -> Iterator[tuple[VerifiedBoardRevision, bytes]]:
    """Crop near a known board code so tiny adjacent revision text can be read."""
    if result.txts is None or result.scores is None or result.boxes is None:
        return
    boards = {
        normalize_identifier(board.model_code): board
        for board in verified_board_revisions().values()
    }
    with Image.open(BytesIO(content)) as source:
        for line, score, box in zip(result.txts, result.scores, result.boxes, strict=True):
            board = boards.get(normalize_identifier(line))
            if board is None or score < confidence:
                continue
            horizontal = [float(point[0]) for point in box]
            vertical = [float(point[1]) for point in box]
            margin = max(
                160,
                int(max(max(horizontal) - min(horizontal), max(vertical) - min(vertical)) * 0.85),
            )
            bounds = (
                max(0, int(min(horizontal) - margin)),
                max(0, int(min(vertical) - margin)),
                min(source.width, int(max(horizontal) + margin)),
                min(source.height, int(max(vertical) + margin)),
            )
            cropped = ImageOps.autocontrast(ImageOps.grayscale(source.crop(bounds)))
            output = BytesIO()
            cropped.save(output, format="PNG")
            yield board, output.getvalue()


def _confirmed_revision(lines: list[str], board: VerifiedBoardRevision) -> str | None:
    """Accept only a manufacturer-listed revision next to the model in one crop."""
    if not any(
        normalize_identifier(line) == normalize_identifier(board.model_code) for line in lines
    ):
        return None
    spans = [*lines, *(f"{first} {second}" for first, second in pairwise(lines))]
    for revision in board.pcb_revisions:
        pattern = rf"\bREV(?:ISION)?\.?\s*{re.escape(revision)}\b"
        if any(re.search(pattern, span, flags=re.IGNORECASE) for span in spans):
            return revision
        # OCR reading order can split vertical PCB text into distant list entries.
        if any(
            re.fullmatch(r"REV(?:ISION)?\.?", line, flags=re.IGNORECASE) for line in lines
        ) and any(line.strip() == revision for line in lines):
            return revision
    return None


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
            elif isinstance(result, RapidOCROutput):
                for board, crop in _revision_crops(content, result, self.min_confidence):
                    revision_lines = _recognized_lines(self._engine(crop), self.min_confidence)
                    revision = _confirmed_revision(revision_lines, board)
                    if revision is not None:
                        lines.append(f"{board.model_code} REV {revision}")
                        break
        return list(dict.fromkeys(lines))
