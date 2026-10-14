"""Prepare a persistent catalog before starting a scanner deployment."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from scan_hardware.__main__ import main as serve
from scan_hardware.catalog_import import import_archives
from scan_hardware.catalog_migrate import migrate_catalog
from scan_hardware.config import Settings, settings
from scan_hardware.image_seed import seed_images
from scan_hardware.models.item import Category
from scan_hardware.price_import import import_prices
from scan_hardware.services.catalog import Catalog


def prepare_catalog(config: Settings) -> Path:
    """Reuse a published catalog or import the supplied Kaggle archives once.

    Args:
        config: Paths and readiness policy for this deployment.

    Returns:
        Path of a nonempty, validated SQLite catalog.

    Raises:
        FileNotFoundError: A required source archive is absent.
        RuntimeError: No import source exists or the published catalog is empty.
    """
    if not config.catalog_latest_pointer.exists() and config.catalog_path is None:
        rohit = config.import_rohit_path
        warcoder = config.import_warcoder_path
        if rohit is None or warcoder is None:
            raise RuntimeError("Catalog archives must be configured on first start")
        for archive in (rohit, warcoder):
            if not archive.is_file():
                raise FileNotFoundError(f"Catalog archive is missing: {archive}")
        import_archives(
            rohit,
            warcoder,
            config.catalog_latest_pointer.parent / "processed",
            config.catalog_latest_pointer,
        )
    path = config.resolved_catalog_path
    catalog = Catalog(path)
    if config.catalog_path is None and catalog.count_category(Category.RAM) == 0:
        rohit = config.import_rohit_path
        warcoder = config.import_warcoder_path
        if rohit is not None and warcoder is not None:
            logger.info("Published catalog lacks RAM; rebuilding from configured archives")
            import_archives(
                rohit,
                warcoder,
                config.catalog_latest_pointer.parent / "processed",
                config.catalog_latest_pointer,
            )
            path = config.resolved_catalog_path
            catalog = Catalog(path)
    count = catalog.count_items()
    if count == 0:
        raise RuntimeError(f"Published catalog is empty: {path}")
    logger.info("Catalog ready path={} items={}", path, count)
    return path


@logger.catch(reraise=True)
def main() -> None:
    """Import on first start and launch the HTTP service."""
    catalog_path = prepare_catalog(settings)
    if settings.database_url is not None:
        migrate_catalog(catalog_path, settings.database_url)
        catalog = Catalog(database_url=settings.database_url)
    else:
        catalog = Catalog(catalog_path)
    if settings.image_import_manifest is not None and settings.image_import_manifest.is_file():
        seed_images(
            settings.image_import_manifest,
            catalog,
            settings.image_dir,
            settings.catalog_latest_pointer.parent / "processed" / "image-import",
            settings.max_upload_bytes,
        )
    if settings.price_import_manifest is not None and settings.price_import_manifest.is_file():
        import_prices(
            settings.price_import_manifest,
            catalog,
            settings.catalog_latest_pointer.parent / "processed" / "price-import",
        )
    serve()


if __name__ == "__main__":
    main()
