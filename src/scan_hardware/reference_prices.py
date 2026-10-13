"""Pin historical and dataset snapshot prices to exact catalog products."""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field, HttpUrl

from scan_hardware.image_enrichment import (
    PACKAGE_MANIFEST,
    SOURCE_NAME,
    SOURCE_PATH,
    download_feed,
)
from scan_hardware.models.item import Category

PACKAGE_DIR = Path(__file__).parent / "curation"
HISTORICAL_MANIFEST = PACKAGE_DIR / "historical_prices.json"
REFERENCE_MANIFEST = PACKAGE_DIR / "reference_prices.json"
MIN_REFERENCE_PRICES = 400


class ReferencePrice(BaseModel):
    """A labeled price reference that is not a current Brazilian retail offer."""

    item_id: str
    category: Category
    model: str
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    currency: Literal["USD", "EUR"]
    context: Literal["historical_review", "dataset_snapshot"]
    source_url: HttpUrl
    source_date: date | None = None


class FeedPrice(BaseModel):
    """Fields needed from the pinned PCPartPicker dataset row."""

    source_id: str
    price_eur: Decimal | None = None
    url: HttpUrl


def build_reference_prices(feed_path: Path, images_path: Path) -> list[ReferencePrice]:
    """Join priced feed rows only through reviewed exact image associations."""
    images = json.loads(images_path.read_text(encoding="utf-8"))["images"]
    by_source_id = {image["source_id"]: image for image in images}
    prices: dict[str, ReferencePrice] = {}
    with feed_path.open(encoding="utf-8") as feed:
        for line in feed:
            row = FeedPrice.model_validate_json(line)
            image = by_source_id.get(row.source_id)
            if image is None or row.price_eur is None or str(row.url) != image["source_url"]:
                continue
            prices[image["item_id"]] = ReferencePrice(
                item_id=image["item_id"],
                category=image["category"],
                model=image["model"],
                amount=row.price_eur,
                currency="EUR",
                context="dataset_snapshot",
                source_url=row.url,
            )
    historical = json.loads(HISTORICAL_MANIFEST.read_text(encoding="utf-8"))
    for raw in historical:
        price = ReferencePrice.model_validate(raw)
        prices[price.item_id] = price
    return [prices[item_id] for item_id in sorted(prices)]


def publish_reference_prices(feed_path: Path, images_path: Path, output_path: Path) -> int:
    """Write a deterministic packaged manifest from the pinned source snapshot."""
    prices = build_reference_prices(feed_path, images_path)
    if len(prices) < MIN_REFERENCE_PRICES:
        raise ValueError("Reference price coverage fell below 400 exact products")
    output = {
        "source": SOURCE_NAME,
        "prices": [price.model_dump(mode="json", exclude_none=True) for price in prices],
    }
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(prices)


@lru_cache(maxsize=1)
def reference_prices() -> dict[str, ReferencePrice]:
    """Load packaged prices, indexed by catalog item ID."""
    data = json.loads(REFERENCE_MANIFEST.read_text(encoding="utf-8"))
    prices = [ReferencePrice.model_validate(raw) for raw in data["prices"]]
    return {price.item_id: price for price in prices}


def reference_price_for(item_id: str, category: Category, model: str) -> ReferencePrice | None:
    """Return a reference only while its catalog identity still matches."""
    price = reference_prices().get(item_id)
    if price is None or price.category is not category or price.model != model:
        return None
    return price


@logger.catch(reraise=True)
def main() -> None:
    """Regenerate package data from the exact pinned feed."""
    parser = argparse.ArgumentParser(description="Build exact historical price references")
    parser.add_argument("--feed", type=Path, default=SOURCE_PATH)
    parser.add_argument("--images", type=Path, default=PACKAGE_MANIFEST)
    parser.add_argument("--output", type=Path, default=REFERENCE_MANIFEST)
    args = parser.parse_args()
    feed = download_feed(args.feed) if args.feed == SOURCE_PATH else args.feed
    count = publish_reference_prices(feed, args.images, args.output)
    logger.info("Reference prices published count={} output={}", count, args.output)


if __name__ == "__main__":
    main()
