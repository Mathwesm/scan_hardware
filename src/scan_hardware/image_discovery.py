"""Find exact motherboard photographs through permitted catalog and media APIs."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, Field, HttpUrl, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from scan_hardware.config import settings
from scan_hardware.core.matching import normalize_identifier
from scan_hardware.curation import ImageManifest, VerifiedImage, verified_images
from scan_hardware.image_enrichment import catalog_images
from scan_hardware.models.item import Category, Item
from scan_hardware.services.catalog import Catalog

OPENVERSE_URL = "https://api.openverse.org/v1/images/"
ICECAT_URL = "https://live.icecat.biz/api"
ICECAT_LICENSE_URL = "https://iceclog.com/open-content-license/"
PACKAGE_MANIFEST = Path(__file__).parent / "curation" / "verified_images.json"
USER_AGENT = "scan_hardware/0.1 (+https://github.com/Mathwesm/scan_hardware)"
MIN_INTERVAL_SECONDS = 1.5
MIN_WIDTH = 600
MIN_HEIGHT = 500
MIN_ASPECT = 0.7
MAX_ASPECT = 1.5


class OpenverseResult(BaseModel):
    """Fields required to associate and attribute an image search result."""

    title: str
    url: HttpUrl
    foreign_landing_url: HttpUrl
    creator: str | None = None
    license: str
    license_version: str | None = None
    license_url: HttpUrl | None = None
    width: int | None = None
    height: int | None = None


class IcecatGeneralInfo(BaseModel):
    """Identity returned by Icecat for one requested product code."""

    brand: str = Field(alias="Brand")
    part_code: str = Field(alias="BrandPartCode")
    icecat_id: int = Field(alias="IcecatId")
    category: dict[str, Any] = Field(alias="Category")


class IcecatPicture(BaseModel):
    """Main product image and its source-reported dimensions."""

    url: HttpUrl = Field(alias="HighPic")
    width: int = Field(alias="HighPicWidth")
    height: int = Field(alias="HighPicHeight")


class IcecatProduct(BaseModel):
    """Validated product identity and its primary image."""

    general: IcecatGeneralInfo = Field(alias="GeneralInfo")
    picture: IcecatPicture = Field(alias="Image")


class DiscoveryRow(BaseModel):
    """Auditable decision for one motherboard with no reference image."""

    item_id: str
    model: str
    status: str
    candidates: list[str]


def _model_name(item: Item) -> str:
    """Remove a duplicated brand prefix from a catalog model."""
    model = item.model.strip()
    brand = item.brand.strip()
    while model.casefold().startswith(brand.casefold() + " "):
        model = model[len(brand) :].strip()
    return model


def _matches_exact_model(title: str, model: str, sibling_models: set[str]) -> bool:
    """Reject lookalike variants whose full identifier extends the searched model."""
    normalized_title = normalize_identifier(title)
    normalized_model = normalize_identifier(model)
    if not normalized_model or normalized_model not in normalized_title:
        return False
    return not any(
        len(sibling) > len(normalized_model) and sibling in normalized_title
        for sibling in sibling_models
        if sibling.startswith(normalized_model)
    )


def _usable_image(result: OpenverseResult) -> bool:
    """Require a reasonably large, board-shaped openly licensed photograph."""
    if (
        not result.width
        or not result.height
        or result.width < MIN_WIDTH
        or result.height < MIN_HEIGHT
    ):
        return False
    aspect = result.width / result.height
    return (
        MIN_ASPECT <= aspect <= MAX_ASPECT
        and result.license_url is not None
        and bool(result.creator)
    )


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    wait=wait_random_exponential(multiplier=1, max=16),
    stop=stop_after_attempt(3),
    reraise=True,
)
def search_icecat(client: httpx.Client, item: Item, shopname: str) -> VerifiedImage | None:
    """Request one exact Open Icecat board by brand and manufacturer product code."""
    model = _model_name(item)
    response = client.get(
        ICECAT_URL,
        params={"lang": "EN", "shopname": shopname, "Brand": item.brand, "ProductCode": model},
        timeout=20,
    )
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("msg") != "OK":
        return None
    product = IcecatProduct.model_validate(payload.get("data"))
    identity = product.general
    category_name = identity.category.get("Name")
    if (
        normalize_identifier(identity.brand) != normalize_identifier(item.brand)
        or normalize_identifier(identity.part_code) != normalize_identifier(model)
        or not isinstance(category_name, dict)
        or category_name.get("Value") != "Motherboards"
    ):
        return None
    picture = product.picture
    if picture.width < MIN_HEIGHT or picture.height < MIN_HEIGHT:
        return None
    aspect = picture.width / picture.height
    if not MIN_ASPECT <= aspect <= MAX_ASPECT:
        return None
    source = httpx.URL(ICECAT_URL).copy_merge_params(
        {"lang": "EN", "shopname": "openicecat-live", "icecat_id": identity.icecat_id}
    )
    return VerifiedImage(
        item_id=item.id,
        image_url=picture.url,
        creator="Open Icecat and product manufacturer",
        source_url=str(source),
        license_name="Open Icecat Content License",
        license_url=ICECAT_LICENSE_URL,
    )


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    wait=wait_random_exponential(multiplier=1, max=16),
    stop=stop_after_attempt(3),
    reraise=True,
)
def search_images(client: httpx.Client, query: str) -> list[OpenverseResult]:
    """Search one model with a timeout and a bounded response page."""
    response = client.get(OPENVERSE_URL, params={"q": query, "page_size": 20}, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Openverse response has no image result list")
    results: list[OpenverseResult] = []
    for raw in payload["results"]:
        try:
            results.append(OpenverseResult.model_validate(raw))
        except ValidationError:
            continue
    return results


def _discover_openverse_item(
    client: httpx.Client, item: Item, sibling_models: set[str]
) -> tuple[VerifiedImage | None, DiscoveryRow]:
    """Select one exact, licensed Openverse candidate for a motherboard."""
    model = _model_name(item)
    results = search_images(client, f"{item.brand} {model} motherboard")
    candidates = [
        result
        for result in results
        if _usable_image(result)
        and normalize_identifier(item.brand) in normalize_identifier(result.title)
        and _matches_exact_model(result.title, model, sibling_models)
    ]
    image = None
    if len(candidates) == 1:
        result = candidates[0]
        license_name = f"CC {result.license.upper()} {result.license_version or ''}".strip()
        image = VerifiedImage(
            item_id=item.id,
            image_url=result.url,
            creator=result.creator or "Unknown",
            source_url=result.foreign_landing_url,
            license_name=license_name,
            license_url=result.license_url,
        )
    row = DiscoveryRow(
        item_id=item.id,
        model=item.model,
        status="accepted" if image else "ambiguous" if candidates else "no_match",
        candidates=[str(candidate.foreign_landing_url) for candidate in candidates],
    )
    return image, row


def _discover_icecat_item(
    client: httpx.Client, item: Item, shopname: str
) -> tuple[VerifiedImage | None, DiscoveryRow]:
    """Select an exact Open Icecat product photo with source attribution."""
    image = search_icecat(client, item, shopname)
    row = DiscoveryRow(
        item_id=item.id,
        model=item.model,
        status="accepted" if image else "no_match",
        candidates=[str(image.source_url)] if image else [],
    )
    return image, row


def discover_images(
    catalog: Catalog,
    client: httpx.Client,
    *,
    limit: int,
    offset: int = 0,
    delay_seconds: float = MIN_INTERVAL_SECONDS,
    provider: str = "openverse",
    icecat_shopname: str | None = None,
) -> tuple[list[VerifiedImage], list[DiscoveryRow]]:
    """Search missing board photos and accept only one unambiguous exact-model hit."""
    if provider not in {"openverse", "icecat"}:
        raise ValueError(f"Unknown image provider: {provider}")
    if provider == "icecat" and (
        not icecat_shopname or icecat_shopname.casefold() == "openicecat-live"
    ):
        raise ValueError("Icecat discovery requires a registered Channel Partner shopname")
    boards = [item for item in catalog.list_items() if item.category is Category.MOTHERBOARD]
    known = set(verified_images()) | set(catalog_images())
    sibling_models = {normalize_identifier(_model_name(item)) for item in boards}
    missing = [
        item
        for item in boards
        if not item.image_url and not item.has_local_image and item.id not in known
    ][offset : offset + limit]
    accepted: list[VerifiedImage] = []
    decisions: list[DiscoveryRow] = []
    for position, item in enumerate(missing):
        if position:
            time.sleep(delay_seconds)
        try:
            image, decision = (
                _discover_icecat_item(client, item, icecat_shopname or "")
                if provider == "icecat"
                else _discover_openverse_item(client, item, sibling_models)
            )
        except (httpx.HTTPError, ValueError, ValidationError) as error:
            logger.warning("Image search failed item_id={} error={}", item.id, type(error).__name__)
            decisions.append(
                DiscoveryRow(
                    item_id=item.id, model=item.model, status="search_error", candidates=[]
                )
            )
            continue
        if image is not None:
            accepted.append(image)
        decisions.append(decision)
        logger.info(
            "Image discovery progress={}/{} accepted={}", position + 1, len(missing), len(accepted)
        )
    return accepted, decisions


def save_run(images: list[VerifiedImage], decisions: list[DiscoveryRow], output_root: Path) -> Path:
    """Write an immutable manifest and the decision trail for later review."""
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    directory = output_root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "manifest.json").write_text(
        ImageManifest(images=images).model_dump_json(indent=2), encoding="utf-8"
    )
    (directory / "report.json").write_text(
        json.dumps([row.model_dump() for row in decisions], indent=2), encoding="utf-8"
    )
    return directory


def publish_images(images: list[VerifiedImage], path: Path) -> int:
    """Append new exact-model images without replacing existing curated images."""
    existing = ImageManifest.model_validate_json(path.read_text(encoding="utf-8"))
    known = {image.item_id for image in existing.images}
    additions = [image for image in images if image.item_id not in known]
    if additions:
        merged = ImageManifest(images=[*existing.images, *additions])
        path.write_text(merged.model_dump_json(indent=2) + "\n", encoding="utf-8")
        verified_images.cache_clear()
    return len(additions)


def approved_images(images: list[VerifiedImage], path: Path) -> list[VerifiedImage]:
    """Load reviewed item IDs and reject approvals absent from this run."""
    approved_ids = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    candidates = {image.item_id: image for image in images}
    unknown = approved_ids - candidates.keys()
    if unknown:
        raise ValueError(f"Approved item IDs are absent from this run: {sorted(unknown)}")
    return [image for image in images if image.item_id in approved_ids]


def load_review_run(directory: Path, catalog: Catalog) -> list[VerifiedImage]:
    """Recheck saved image identities before a reviewed publication."""
    manifest = ImageManifest.model_validate_json(
        (directory / "manifest.json").read_text(encoding="utf-8")
    )
    rows = [
        DiscoveryRow.model_validate(row)
        for row in json.loads((directory / "report.json").read_text(encoding="utf-8"))
    ]
    accepted = {row.item_id: row for row in rows if row.status == "accepted"}
    for image in manifest.images:
        row = accepted.get(image.item_id)
        item = catalog.get_item(image.item_id)
        if (
            row is None
            or item is None
            or item.category is not Category.MOTHERBOARD
            or item.model != row.model
            or item.image_url is not None
            or item.has_local_image
        ):
            raise ValueError(f"Reviewed image no longer matches an empty board: {image.item_id}")
    return manifest.images


@logger.catch(reraise=True)
def main() -> None:
    """Discover missing board images and optionally publish verified exact hits."""
    parser = argparse.ArgumentParser(description="Discover exact motherboard images")
    parser.add_argument("--catalog", type=Path, default=settings.resolved_catalog_path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--provider", choices=("openverse", "icecat"), default="openverse")
    parser.add_argument("--icecat-shopname", default=settings.icecat_shopname)
    parser.add_argument("--output-root", type=Path, default=Path("data/processed/image-discovery"))
    parser.add_argument("--publish-package", action="store_true")
    parser.add_argument("--approved-ids", type=Path)
    parser.add_argument("--review-run", type=Path)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.offset < 0:
        parser.error("--offset must not be negative")
    if args.publish_package:
        if args.approved_ids is None or args.review_run is None:
            parser.error("--publish-package requires --review-run and --approved-ids")
        images = load_review_run(args.review_run, Catalog(args.catalog))
        reviewed = approved_images(images, args.approved_ids)
        published = publish_images(reviewed, PACKAGE_MANIFEST)
        logger.info("Image review run={} published={}", args.review_run, published)
        return
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        images, decisions = discover_images(
            Catalog(args.catalog),
            client,
            limit=args.limit,
            offset=args.offset,
            provider=args.provider,
            icecat_shopname=args.icecat_shopname,
        )
    run = save_run(images, decisions, args.output_root)
    logger.info("Image discovery run={} searched={} accepted={}", run, len(decisions), len(images))


if __name__ == "__main__":
    main()
