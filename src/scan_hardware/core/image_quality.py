"""Conservative framing checks for reviewed product photographs."""

from __future__ import annotations

from io import BytesIO
from statistics import median

from PIL import Image

PREVIEW_SIZE = 400
MIN_DIMENSION = 2
BACKGROUND_DISTANCE = 45
FOREGROUND_DISTANCE = 60
MIN_UNIFORM_BORDER = 0.8


def foreground_coverage(content: bytes) -> float | None:
    """Estimate subject bounding-box coverage on a nearly uniform background.

    Returns:
        Frame fraction, or None when the background is too complex to judge.
    """
    with Image.open(BytesIO(content)) as image:
        preview = image.convert("RGB")
        preview.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.BILINEAR)
    width, height = preview.size
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        return None
    pixels = preview.tobytes()

    def pixel_at(x: int, y: int) -> tuple[int, int, int]:
        offset = (y * width + x) * 3
        return pixels[offset], pixels[offset + 1], pixels[offset + 2]

    border = [pixel_at(x, 0) for x in range(width)]
    border.extend(pixel_at(x, height - 1) for x in range(width))
    border.extend(pixel_at(0, y) for y in range(height))
    border.extend(pixel_at(width - 1, y) for y in range(height))
    background = tuple(int(median(pixel[channel] for pixel in border)) for channel in range(3))

    def distance(pixel: tuple[int, int, int]) -> int:
        return sum(abs(pixel[channel] - background[channel]) for channel in range(3))

    uniform = sum(distance(pixel) <= BACKGROUND_DISTANCE for pixel in border) / len(border)
    if uniform < MIN_UNIFORM_BORDER:
        return None
    left, top, right, bottom = width, height, 0, 0
    found = False
    for y in range(height):
        for x in range(width):
            if distance(pixel_at(x, y)) > FOREGROUND_DISTANCE:
                found = True
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    if not found:
        return None
    return (right - left + 1) * (bottom - top + 1) / (width * height)
