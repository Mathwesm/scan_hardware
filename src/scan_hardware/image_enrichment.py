"""Enrich the catalog with exact product-image links from a public JSONL feed."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from loguru import logger
from pydantic import BaseModel, HttpUrl, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from scan_hardware.config import settings
from scan_hardware.core.matching import normalize_identifier
from scan_hardware.curation import verified_images
from scan_hardware.models.item import Category

SOURCE_REVISION = "06c3b6a71867b57f018354a0258ef4214072579a"
SOURCE_URL = (
    "https://huggingface.co/datasets/Doshiba/pcpartpicker-parts-dataset/resolve/"
    f"{SOURCE_REVISION}/pcpartpicker_parts.jsonl"
)
SOURCE_NAME = "Doshiba/pcpartpicker-parts-dataset"
SOURCE_SHA256 = "5e7c8a602951e085a298dc9fc0df72fce3bd190299e16bf7c13ea951d9d1d509"
SOURCE_PATH = Path("data/raw/huggingface/pcpartpicker_parts.jsonl")
PACKAGE_MANIFEST = Path(__file__).parent / "curation" / "external_images.json"
MAX_SOURCE_BYTES = 60_000_000
MIN_NEW_IMAGES = {Category.CPU: 300, Category.GPU: 3500, Category.MOTHERBOARD: 1500}
SourceCategory = Literal["cpu", "motherboard", "video-card"]
ProductKey = tuple[Category, str, str]


class ImageSourceError(Exception):
    """The external feed or resulting image catalog is not trustworthy enough."""


class FeedProduct(BaseModel):
    """Validate only the fields needed to join one source product and its image."""

    category: SourceCategory
    brand: str
    name: str
    image_url: HttpUrl
    url: HttpUrl
    source_id: str
    specs: dict[str, Any]


class CatalogImage(BaseModel):
    """One image linked to a catalog item by exact original product fields."""

    item_id: str
    category: Category
    model: str
    image_url: HttpUrl
    source_url: HttpUrl
    source_id: str


class ImageManifest(BaseModel):
    """Packaged image URLs tied to a pinned source revision."""

    source: str
    revision: str
    images: list[CatalogImage]


def _usable_image_url(value: str) -> bool:
    """Reject missing-image placeholders and non-HTTPS image links."""
    parsed = urlsplit(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and "." in parsed.hostname
        and not re.search(r"no[-_]image|placeholder|default[-_]image", parsed.path, re.I)
    )


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    wait=wait_random_exponential(multiplier=1, max=16),
    stop=stop_after_attempt(3),
    reraise=True,
)
def download_feed(destination: Path) -> Path:
    """Fetch one pinned public export with a size cap and reusable local cache.

    Args:
        destination: Ignored local path for the raw JSONL feed.

    Returns:
        Path to a complete cached download.

    Raises:
        ImageSourceError: The response exceeds the configured byte limit.
        httpx.HTTPError: The source cannot be fetched after retries.
    """
    if destination.is_file():
        if _sha256(destination) != SOURCE_SHA256:
            raise ImageSourceError(f"Cached image feed has an unexpected SHA-256: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".download")
    headers = {"User-Agent": "scan_hardware/0.1 (+https://github.com/Mathwesm/scan_hardware)"}
    try:
        with httpx.stream(
            "GET", SOURCE_URL, headers=headers, follow_redirects=True, timeout=60
        ) as response:
            response.raise_for_status()
            total = 0
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        raise ImageSourceError("Public image feed exceeds the 60 MB limit")
                    output.write(chunk)
        if _sha256(temporary) != SOURCE_SHA256:
            raise ImageSourceError("Downloaded image feed has an unexpected SHA-256")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _sha256(path: Path) -> str:
    """Hash a source file without loading the entire feed into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _product_key(product: FeedProduct) -> ProductKey:
    """Join GPU variants on chipset as well as the printed product name."""
    category = Category.GPU if product.category == "video-card" else Category(product.category)
    chipset = product.specs.get("Chipset") if category is Category.GPU else None
    return (
        category,
        normalize_identifier(product.name),
        normalize_identifier(chipset) if isinstance(chipset, str) else "",
    )


def _load_feed(path: Path) -> tuple[dict[ProductKey, list[FeedProduct]], Counter[str]]:
    """Parse the cached export and quarantine malformed or placeholder records."""
    index: dict[ProductKey, list[FeedProduct]] = defaultdict(list)
    rejected: Counter[str] = Counter()
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                rejected["invalid_json"] += 1
                continue
            if not isinstance(payload, dict) or payload.get("category") not in {
                "cpu",
                "video-card",
                "motherboard",
            }:
                continue
            try:
                product = FeedProduct.model_validate(payload)
            except ValidationError:
                rejected["invalid_product"] += 1
                continue
            if not _usable_image_url(str(product.image_url)):
                rejected["placeholder"] += 1
                continue
            if product.category == "video-card" and not isinstance(
                product.specs.get("Chipset"), str
            ):
                rejected["missing_chipset"] += 1
                continue
            if not normalize_identifier(product.brand) or not normalize_identifier(product.name):
                rejected["empty_identifier"] += 1
                continue
            index[_product_key(product)].append(product)
            if line_number % 10_000 == 0:
                logger.debug("Image feed parsed line={} valid_keys={}", line_number, len(index))
    return index, rejected


def _catalog_records(path: Path) -> tuple[list[sqlite3.Row], dict[str, list[dict[str, Any]]]]:
    """Read item metadata and original source rows without changing the catalog."""
    if not path.is_file():
        raise FileNotFoundError(f"Catalog is missing: {path}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        items = connection.execute(
            "SELECT id, category, brand, model, image_url FROM items ORDER BY id"
        ).fetchall()
        sources = connection.execute(
            "SELECT item_id, payload_json FROM source_records WHERE item_id IS NOT NULL "
            "ORDER BY item_id, dataset, file_name, row_number"
        ).fetchall()
    finally:
        connection.close()
    by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        by_item[source["item_id"]].append(json.loads(source["payload_json"]))
    return items, by_item


def build_manifest(
    feed_path: Path,
    catalog_path: Path,
    minimums: dict[Category, int] | None = None,
) -> tuple[ImageManifest, dict[str, Any]]:
    """Select images only for unique, exact source-name and GPU-chipset joins.

    Args:
        feed_path: Downloaded public JSONL export.
        catalog_path: Existing published SQLite catalog.
        minimums: Per-category publication minimums; defaults to the production gate.

    Returns:
        Validated image manifest and quality report.

    Raises:
        ImageSourceError: Coverage is below the minimum for a safe publication.
    """
    index, rejected = _load_feed(feed_path)
    items, sources = _catalog_records(catalog_path)
    counts: Counter[str] = Counter()
    selected: list[CatalogImage] = []
    curated = verified_images()
    for item in items:
        category = Category(item["category"])
        counts[f"total_{category.value}"] += 1
        if item["image_url"] or item["id"] in curated:
            counts[f"existing_{category.value}"] += 1
            continue
        candidates: dict[str, FeedProduct] = {}
        for raw in sources[item["id"]]:
            name = raw.get("name")
            if not isinstance(name, str):
                continue
            chipset = raw.get("chipset") if category is Category.GPU else None
            if category is Category.GPU and not isinstance(chipset, str):
                continue
            key = (
                category,
                normalize_identifier(name),
                normalize_identifier(chipset) if isinstance(chipset, str) else "",
            )
            for product in index.get(key, []):
                if normalize_identifier(product.brand) == normalize_identifier(item["brand"]):
                    candidates[str(product.image_url)] = product
        if len(candidates) == 1:
            product = next(iter(candidates.values()))
            selected.append(
                CatalogImage(
                    item_id=item["id"],
                    category=category,
                    model=item["model"],
                    image_url=product.image_url,
                    source_url=product.url,
                    source_id=product.source_id,
                )
            )
            counts[f"added_{category.value}"] += 1
        else:
            reason = "ambiguous" if candidates else "no_exact_match"
            counts[f"{reason}_{category.value}"] += 1
    minimums = MIN_NEW_IMAGES if minimums is None else minimums
    failures = [
        f"{category.value} added={counts[f'added_{category.value}']} < {minimum}"
        for category, minimum in minimums.items()
        if counts[f"added_{category.value}"] < minimum
    ]
    if failures:
        raise ImageSourceError("Image coverage gate failed: " + "; ".join(failures))
    manifest = ImageManifest(source=SOURCE_NAME, revision=SOURCE_REVISION, images=selected)
    report = {
        "catalog": dict(counts),
        "feed_rejected": dict(rejected),
        "feed_sha256": SOURCE_SHA256,
        "new_images": len(selected),
    }
    return manifest, report


def save_manifest(manifest: ImageManifest, report: dict[str, Any], output_root: Path) -> Path:
    """Keep each generated manifest and quality report under an immutable run ID."""
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    directory = output_root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (directory / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest_path


@lru_cache(maxsize=1)
def catalog_images() -> dict[str, CatalogImage]:
    """Load the packaged exact-match image links used by the API."""
    path = files("scan_hardware").joinpath("curation", "external_images.json")
    if not path.is_file():
        return {}
    manifest = ImageManifest.model_validate_json(path.read_text(encoding="utf-8"))
    images: dict[str, CatalogImage] = {}
    for image in manifest.images:
        if image.item_id in images:
            raise ImageSourceError(f"Duplicate external image for {image.item_id}")
        images[image.item_id] = image
    return images


def image_for_item(item_id: str, category: Category, model: str) -> CatalogImage | None:
    """Use a packaged photo only while its catalog identity still matches."""
    image = catalog_images().get(item_id)
    if image is None or image.category is not category:
        return None
    if normalize_identifier(image.model) != normalize_identifier(model):
        return None
    return image


@logger.catch(reraise=True)
def main() -> None:
    """Download, exact-match, audit, and optionally package image references."""
    parser = argparse.ArgumentParser(description="Enrich catalog images by exact product keys")
    parser.add_argument("--feed", type=Path, default=SOURCE_PATH)
    parser.add_argument("--catalog", type=Path, default=settings.resolved_catalog_path)
    parser.add_argument("--output-root", type=Path, default=Path("data/processed/images"))
    parser.add_argument("--publish-package", action="store_true")
    args = parser.parse_args()
    feed_path = download_feed(args.feed)
    manifest, report = build_manifest(feed_path, args.catalog)
    output = save_manifest(manifest, report, args.output_root)
    if args.publish_package:
        if PACKAGE_MANIFEST.is_file():
            snapshot = output.parent / "previous-package-manifest.json"
            shutil.copy2(PACKAGE_MANIFEST, snapshot)
        shutil.copy2(output, PACKAGE_MANIFEST)
    logger.info(
        "Image manifest path={} new_images={} published={}",
        output,
        len(manifest.images),
        args.publish_package,
    )


if __name__ == "__main__":
    main()
