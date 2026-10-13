"""Estimate visible hardware colors from an uploaded photograph."""

from __future__ import annotations

from collections import Counter, deque
from colorsys import rgb_to_hsv
from io import BytesIO
from typing import cast

from PIL import Image

MAX_SAMPLE_SIDE = 180
MIN_FOREGROUND_RATIO = 0.03
MIN_PRIMARY_RATIO = 0.18
MIN_SECONDARY_RATIO = 0.18
MAX_UNIFORM_RATIO = 0.98
MIN_WHITE_BORDER_RATIO = 0.70
WHITE_VALUE = 0.90
WHITE_SATURATION = 0.10
BLACK_VALUE = 0.13
DARK_VALUE = 0.28
DARK_SATURATION = 0.23
GRAY_SATURATION = 0.12
RED_WRAP_START = 0.96
BACKDROP_BLACK_MAX = 25
HUE_BANDS = (
    (0.04, "Red"),
    (0.11, "Orange"),
    (0.17, "Gold"),
    (0.24, "Yellow"),
    (0.56, "Green"),
    (0.74, "Blue"),
    (0.86, "Purple"),
)


def _color_name(red: int, green: int, blue: int) -> str:
    """Map one RGB pixel to a broad, readable hardware color."""
    hue, saturation, value = rgb_to_hsv(red / 255, green / 255, blue / 255)
    if value > WHITE_VALUE and saturation < WHITE_SATURATION:
        return "White"
    if value < BLACK_VALUE or (value < DARK_VALUE and saturation < DARK_SATURATION):
        return "Black"
    if saturation < GRAY_SATURATION:
        return "Gray"
    if hue >= RED_WRAP_START:
        return "Red"
    return next((name for upper_bound, name in HUE_BANDS if hue < upper_bound), "Pink")


def _is_white_background(image: Image.Image) -> bool:
    """Detect a white studio backdrop from the outside edge only."""
    step = max(1, min(image.width, image.height) // 45)
    points = [
        *((x, 0) for x in range(0, image.width, step)),
        *((x, image.height - 1) for x in range(0, image.width, step)),
        *((0, y) for y in range(0, image.height, step)),
        *((image.width - 1, y) for y in range(0, image.height, step)),
    ]
    white = sum(
        _color_name(*cast(tuple[int, int, int], image.getpixel(point))) == "White"
        for point in points
    )
    return white / len(points) >= MIN_WHITE_BORDER_RATIO


def _foreground_pixels(image: Image.Image) -> list[tuple[int, int, int]]:
    """Exclude white backdrop and any dark backdrop joined to its outer edge."""
    pixels = [cast(tuple[int, int, int], pixel) for pixel in image.get_flattened_data()]
    if not _is_white_background(image):
        return pixels
    width, height = image.size
    is_white = [_color_name(*pixel) == "White" for pixel in pixels]
    is_backdrop_black = [max(pixel) < BACKDROP_BLACK_MAX for pixel in pixels]
    connected: set[int] = set()
    queue = deque(
        index
        for index in range(len(pixels))
        if (index < width or index >= width * (height - 1) or index % width in {0, width - 1})
        and is_backdrop_black[index]
    )
    while queue:
        index = queue.popleft()
        if index in connected or not is_backdrop_black[index]:
            continue
        connected.add(index)
        x, y = index % width, index // width
        queue.extend(
            neighbor_y * width + neighbor_x
            for neighbor_x, neighbor_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            if 0 <= neighbor_x < width and 0 <= neighbor_y < height
        )
    return [
        pixel
        for index, pixel in enumerate(pixels)
        if not is_white[index] and index not in connected
    ]


def estimate_photo_color(content: bytes) -> str | None:
    """Estimate one or two dominant colors of a photographed component.

    Args:
        content: Already validated JPEG, PNG, or WebP image bytes.

    Returns:
        Broad color names, or ``None`` when the pixels are insufficient.
    """
    with Image.open(BytesIO(content)) as source:
        image = source.convert("RGB")
    image.thumbnail((MAX_SAMPLE_SIDE, MAX_SAMPLE_SIDE), resample=Image.Resampling.NEAREST)
    counts = Counter(_color_name(*pixel) for pixel in _foreground_pixels(image))
    foreground = counts.total()
    if foreground < image.width * image.height * MIN_FOREGROUND_RATIO:
        return None
    ranked = counts.most_common(2)
    if not ranked or ranked[0][1] / foreground < MIN_PRIMARY_RATIO:
        return None
    if ranked[0][1] / foreground > MAX_UNIFORM_RATIO and not _is_white_background(image):
        return None
    colors = [ranked[0][0]]
    if len(ranked) > 1 and ranked[1][1] / foreground >= MIN_SECONDARY_RATIO:
        colors.append(ranked[1][0])
    return " / ".join(colors)
