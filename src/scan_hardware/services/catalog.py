"""SQLite catalog for independently running scanner deployments."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from scan_hardware.core.matching import normalize_identifier
from scan_hardware.core.specifications import build_specifications
from scan_hardware.curation import verified_images
from scan_hardware.image_enrichment import image_for_item
from scan_hardware.models.item import Category, Item, ItemInput
from scan_hardware.models.price import PriceOffer
from scan_hardware.reference_prices import reference_price_for

MAX_PRICE_AGE = timedelta(days=14)


class IdentifierConflictError(Exception):
    """A normalized identifier already belongs to another catalog item."""


class Catalog:
    """Persist hardware records and their alternate printed identifiers."""

    def __init__(self, path: Path) -> None:
        """Initialize the database schema at the configured path.

        Args:
            path: SQLite database file location.
        """
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    brand TEXT NOT NULL,
                    model TEXT NOT NULL,
                    image_url TEXT,
                    image_digest TEXT
                );
                CREATE TABLE IF NOT EXISTS identifiers (
                    normalized TEXT PRIMARY KEY,
                    display TEXT NOT NULL,
                    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_identifiers_item_id ON identifiers(item_id);
                CREATE TABLE IF NOT EXISTS source_records (
                    dataset TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    row_number INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    item_id TEXT REFERENCES items(id) ON DELETE SET NULL,
                    status TEXT NOT NULL CHECK(status IN ('imported', 'rejected')),
                    reason TEXT,
                    PRIMARY KEY (dataset, file_name, row_number)
                );
                CREATE INDEX IF NOT EXISTS idx_source_records_item ON source_records(item_id);
                CREATE TABLE IF NOT EXISTS item_images (
                    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    file_name TEXT NOT NULL,
                    view TEXT NOT NULL CHECK(view IN ('front', 'side', 'back', 'detail', 'other')),
                    width INTEGER NOT NULL CHECK(width > 0),
                    height INTEGER NOT NULL CHECK(height > 0),
                    is_primary INTEGER NOT NULL CHECK(is_primary IN (0, 1)),
                    PRIMARY KEY (item_id, file_name)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_item_images_primary
                ON item_images(item_id) WHERE is_primary = 1;
                CREATE TABLE IF NOT EXISTS price_observations (
                    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    retailer TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    identifier TEXT NOT NULL,
                    price_cents INTEGER NOT NULL CHECK(price_cents > 0),
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY (item_id, source_url, observed_at)
                );
                CREATE INDEX IF NOT EXISTS idx_price_observations_item
                ON price_observations(item_id, observed_at);
                """
            )

    def record_price_offer(self, offer: PriceOffer) -> None:
        """Store one exact-identifier price observation without overwriting history."""
        if offer.observed_at > datetime.now(UTC):
            raise ValueError("Price observation cannot be in the future")
        item = self.get_item(offer.item_id)
        if item is None:
            raise KeyError(offer.item_id)
        identifier = normalize_identifier(offer.identifier)
        if identifier not in {normalize_identifier(value) for value in item.identifiers}:
            raise ValueError("Price identifier does not belong to the catalog item")
        cents = int((offer.price_brl * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO price_observations
                (item_id, retailer, source_url, identifier, price_cents, observed_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    offer.item_id,
                    offer.retailer.strip(),
                    str(offer.source_url),
                    offer.identifier.strip(),
                    cents,
                    offer.observed_at.isoformat(),
                ),
            )

    def price_summary(
        self, item_id: str, *, at: datetime | None = None
    ) -> tuple[float, int, datetime] | None:
        """Average the newest standard offer per retailer from the last 14 days."""
        now = at or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("Price summary time must include a timezone")
        cutoff = (now - MAX_PRICE_AGE).astimezone(UTC)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT retailer, price_cents, observed_at FROM price_observations
                WHERE item_id = ?""",
                (item_id,),
            ).fetchall()
        latest: dict[str, tuple[sqlite3.Row, datetime]] = {}
        for row in rows:
            observed = datetime.fromisoformat(row["observed_at"])
            if not cutoff <= observed <= now:
                continue
            retailer = row["retailer"].casefold()
            if retailer not in latest or observed > latest[retailer][1]:
                latest[retailer] = (row, observed)
        if not latest:
            return None
        mean_cents = (
            Decimal(sum(row["price_cents"] for row, _ in latest.values())) / len(latest)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        newest = max(observed for _, observed in latest.values())
        return float(mean_cents / 100), len(latest), newest

    def _connect(self) -> sqlite3.Connection:
        """Create a connection with foreign keys and a finite lock timeout."""
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection

    def count_items(self) -> int:
        """Count published items for deployment readiness checks."""
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM items").fetchone()
        return int(row["total"])

    def put_item(self, item_id: str, item: ItemInput) -> Item:
        """Create or replace one item atomically.

        Args:
            item_id: Stable ID supplied by the catalog owner.
            item: Validated item details.

        Returns:
            Stored item.

        Raises:
            IdentifierConflictError: An alias is owned by another item.
        """
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO items (id, category, brand, model, image_url)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET category=excluded.category,
                    brand=excluded.brand, model=excluded.model, image_url=excluded.image_url""",
                    (
                        item_id,
                        item.category.value,
                        item.brand,
                        item.model,
                        str(item.image_url) if item.image_url else None,
                    ),
                )
                connection.execute("DELETE FROM identifiers WHERE item_id = ?", (item_id,))
                connection.executemany(
                    "INSERT INTO identifiers (normalized, display, item_id) VALUES (?, ?, ?)",
                    [(normalize_identifier(value), value, item_id) for value in item.identifiers],
                )
        except sqlite3.IntegrityError as error:
            raise IdentifierConflictError("Identifier already belongs to another item") from error
        stored = self.get_item(item_id)
        if stored is None:
            raise RuntimeError("Stored item could not be read")
        return stored

    def get_item(self, item_id: str) -> Item | None:
        """Read one item and all of its aliases."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return None
            aliases = connection.execute(
                "SELECT display FROM identifiers WHERE item_id = ? ORDER BY display", (item_id,)
            ).fetchall()
        curated_image = verified_images().get(item_id)
        external_image = image_for_item(item_id, Category(row["category"]), row["model"])
        price = self.price_summary(item_id)
        reference = reference_price_for(item_id, Category(row["category"]), row["model"])
        return Item(
            id=row["id"],
            category=Category(row["category"]),
            brand=row["brand"],
            model=row["model"],
            image_url=(
                str(curated_image.image_url)
                if curated_image
                else row["image_url"] or (str(external_image.image_url) if external_image else None)
            ),
            identifiers=[alias["display"] for alias in aliases],
            has_local_image=row["image_digest"] is not None,
            local_image_url=f"/items/{item_id}/image" if row["image_digest"] else None,
            estimated_price_brl=price[0] if price else None,
            price_offer_count=price[1] if price else None,
            price_observed_at=price[2] if price else None,
            price_status=(
                "average"
                if price and price[1] > 1
                else "observed"
                if price
                else "reference_only"
                if reference
                else "unavailable"
            ),
            reference_price_amount=float(reference.amount) if reference else None,
            reference_price_currency=reference.currency if reference else None,
            reference_price_context=reference.context if reference else None,
            reference_price_source_url=str(reference.source_url) if reference else None,
            reference_price_date=reference.source_date if reference else None,
            image_attribution=(
                curated_image.attribution()
                if curated_image and row["image_digest"] is None
                else None
            ),
            specifications=build_specifications(
                Category(row["category"]), self.get_source_records(item_id), item_id
            ),
        )

    def list_items(self) -> list[Item]:
        """List catalog items with two queries for a large imported catalog."""
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM items ORDER BY id").fetchall()
            alias_rows = connection.execute(
                "SELECT item_id, display FROM identifiers ORDER BY item_id, display"
            ).fetchall()
        aliases: dict[str, list[str]] = {}
        for alias in alias_rows:
            aliases.setdefault(alias["item_id"], []).append(alias["display"])
        curated_images = verified_images()
        return [
            Item(
                id=row["id"],
                category=Category(row["category"]),
                brand=row["brand"],
                model=row["model"],
                image_url=(
                    str(curated_images[row["id"]].image_url)
                    if row["id"] in curated_images
                    else row["image_url"]
                    or (
                        str(external_image.image_url)
                        if (
                            external_image := image_for_item(
                                row["id"], Category(row["category"]), row["model"]
                            )
                        )
                        else None
                    )
                ),
                identifiers=aliases.get(row["id"], []),
                has_local_image=row["image_digest"] is not None,
                local_image_url=f"/items/{row['id']}/image" if row["image_digest"] else None,
                image_attribution=(
                    curated_images[row["id"]].attribution()
                    if row["id"] in curated_images and row["image_digest"] is None
                    else None
                ),
            )
            for row in rows
        ]

    def put_source_record(
        self,
        dataset: str,
        file_name: str,
        row_number: int,
        payload: dict[str, Any],
        item_id: str | None,
        reason: str | None = None,
    ) -> None:
        """Store every original column and the import decision idempotently."""
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO source_records
                (dataset, file_name, row_number, payload_json, item_id, status, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, file_name, row_number) DO UPDATE SET
                payload_json=excluded.payload_json, item_id=excluded.item_id,
                status=excluded.status, reason=excluded.reason""",
                (
                    dataset,
                    file_name,
                    row_number,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    item_id,
                    "imported" if item_id else "rejected",
                    reason,
                ),
            )

    def get_source_records(self, item_id: str) -> list[dict[str, Any]]:
        """Return original source rows associated with one item."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT dataset, file_name, row_number, payload_json
                FROM source_records WHERE item_id = ? ORDER BY dataset, file_name, row_number""",
                (item_id,),
            ).fetchall()
        return [
            {
                "dataset": row["dataset"],
                "file_name": row["file_name"],
                "row_number": row["row_number"],
                "data": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def set_image_digest(self, item_id: str, digest: str) -> None:
        """Point an existing item to immutable image bytes."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE items SET image_digest = ? WHERE id = ?", (digest, item_id)
            )
            if cursor.rowcount == 0:
                raise KeyError(item_id)

    def get_image_digest(self, item_id: str) -> str | None:
        """Return the local image digest if one exists."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT image_digest FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        return None if row is None else row["image_digest"]

    def add_image(
        self,
        item_id: str,
        file_name: str,
        view: str,
        width: int,
        height: int,
        is_primary: bool,
    ) -> None:
        """Attach immutable local image bytes to a product gallery idempotently."""
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone()
            if exists is None:
                raise KeyError(item_id)
            if is_primary:
                connection.execute(
                    "UPDATE item_images SET is_primary = 0 WHERE item_id = ?", (item_id,)
                )
            connection.execute(
                """INSERT INTO item_images (item_id, file_name, view, width, height, is_primary)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id, file_name) DO UPDATE SET
                view = CASE WHEN excluded.is_primary = 1 THEN excluded.view
                            ELSE item_images.view END,
                width = excluded.width, height = excluded.height,
                is_primary = MAX(item_images.is_primary, excluded.is_primary)""",
                (item_id, file_name, view, width, height, int(is_primary)),
            )
            if is_primary:
                connection.execute(
                    "UPDATE items SET image_digest = ? WHERE id = ?", (file_name, item_id)
                )

    def list_images(self, item_id: str) -> list[dict[str, Any]]:
        """Return the primary image first, preserving legacy single-image uploads."""
        with self._connect() as connection:
            item = connection.execute(
                "SELECT image_digest FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if item is None:
                raise KeyError(item_id)
            rows = connection.execute(
                """SELECT file_name, view, width, height, is_primary
                FROM item_images WHERE item_id = ?
                ORDER BY is_primary DESC, view, file_name""",
                (item_id,),
            ).fetchall()
        images = [dict(row) for row in rows]
        legacy = item["image_digest"]
        if legacy and not any(image["file_name"] == legacy for image in images):
            images.insert(
                0,
                {
                    "file_name": legacy,
                    "view": "other",
                    "width": None,
                    "height": None,
                    "is_primary": 1,
                },
            )
        return images

    def has_image(self, item_id: str, file_name: str) -> bool:
        """Check that an immutable image belongs to the requested item."""
        return any(image["file_name"] == file_name for image in self.list_images(item_id))
