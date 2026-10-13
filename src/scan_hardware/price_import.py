"""Import reviewed current BRL offers into the local catalog."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, ValidationError

from scan_hardware.config import settings
from scan_hardware.models.price import PriceOffer
from scan_hardware.services.catalog import Catalog


class PriceManifest(BaseModel):
    """Input envelope; each observation is validated independently."""

    offers: list[dict[str, Any]]


def import_prices(manifest_path: Path, catalog: Catalog, report_root: Path) -> dict[str, int]:
    """Quarantine invalid offers and write a versioned import report."""
    manifest = PriceManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    counts: Counter[str] = Counter()
    for position, raw in enumerate(manifest.offers, start=1):
        try:
            offer = PriceOffer.model_validate(raw)
            catalog.record_price_offer(offer)
            counts["imported"] += 1
        except (ValidationError, ValueError, KeyError) as error:
            counts["rejected"] += 1
            logger.warning("Price import rejected position={} reason={}", position, str(error))
        if position % max(1, len(manifest.offers) // 20) == 0:
            filled = position * 20 // len(manifest.offers)
            logger.info(
                "Price import progress=[{}{}] {}/{}",
                "#" * filled,
                "." * (20 - filled),
                position,
                len(manifest.offers),
            )
    counts["total"] = len(manifest.offers)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report = report_root / run_id / "report.json"
    report.parent.mkdir(parents=True, exist_ok=False)
    report.write_text(json.dumps(dict(counts), indent=2), encoding="utf-8")
    if counts["total"] and not counts["imported"]:
        raise RuntimeError(f"No price offers could be imported: {report}")
    logger.info("Price import complete report={} counts={}", report, dict(counts))
    return dict(counts)


@logger.catch(reraise=True)
def main() -> None:
    """Import a selected local offer manifest without network access."""
    parser = argparse.ArgumentParser(description="Import reviewed Brazilian price offers")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=settings.resolved_catalog_path)
    parser.add_argument("--output-root", type=Path, default=Path("data/processed/price-import"))
    args = parser.parse_args()
    import_prices(args.manifest, Catalog(args.catalog), args.output_root)


if __name__ == "__main__":
    main()
