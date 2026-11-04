"""Hardware catalog backed by SQLite or PostgreSQL."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import TracebackType
from typing import Any

import psycopg
from psycopg.rows import dict_row
from pydantic import SecretStr

from scan_hardware.core.matching import normalize_identifier
from scan_hardware.core.specifications import build_specifications
from scan_hardware.curation import verified_images
from scan_hardware.image_enrichment import image_for_item
from scan_hardware.models.item import Category, Item, ItemInput
from scan_hardware.models.price import PriceOffer
from scan_hardware.reference_prices import reference_price_for

MAX_PRICE_AGE = timedelta(days=14)
INTEL_LGA1151_NEW_SERIES = 3
INTEL_CORE_MODEL_DIGITS = 4


def has_consistent_socket_vendor(
    category: Category, brand: str, socket: str, chipset: str | None = None
) -> bool:
    """Reject a CPU or vendor-branded board with a contradictory socket family."""
    normalized = re.sub(r"[^A-Z0-9]", "", socket.upper())
    vendor = (
        "intel"
        if normalized.startswith(("LGA", "FCLGA"))
        else "amd"
        if re.fullmatch(r"(?:AM|FM)\d+|TR4|STRX4|SP3|STR5", normalized)
        else None
    )
    known_brand = brand.casefold()
    if category not in {Category.CPU, Category.MOTHERBOARD}:
        return True
    if vendor is not None and known_brand in {"amd", "intel"} and known_brand != vendor:
        return False
    if category is Category.MOTHERBOARD and chipset and vendor is not None:
        chipset_vendor = chipset.split(maxsplit=1)[0].casefold()
        if chipset_vendor in {"amd", "intel"} and chipset_vendor != vendor:
            return False
    return True


def has_supported_intel_lga1151_generation(chipset: str | None, cpu_model: str) -> bool:
    """Exclude impossible Core models and known LGA1151 chipset mismatches."""
    model = cpu_model.upper()
    chipset_match = (
        re.search(r"\b[HBQZ]([123])\d{2}\b", chipset.upper())
        if chipset and chipset.upper().startswith("INTEL ")
        else None
    )
    if chipset_match is not None:
        series = int(chipset_match.group(1))
        if re.search(r"\bXEON\s+(?:E-2[12]\d{2}(?!\d)|E3-\d{4}[A-Z]?\s+V[56]\b)", model):
            return False
        if re.search(r"\bPENTIUM\s+GOLD\s+G5\d{3}\b", model):
            return series == INTEL_LGA1151_NEW_SERIES
    core_match = re.search(r"\bCORE\s+I[3579]-(\d{3,5})([A-Z]{0,3})\b", model)
    if core_match is None:
        return True
    digits, suffix = core_match.groups()
    if len(digits) != INTEL_CORE_MODEL_DIGITS or digits[0] not in "6789" or suffix.startswith("X"):
        return False
    if chipset_match is None:
        return True
    series, generation = int(chipset_match.group(1)), int(digits[0])
    return (series in {1, 2} and generation in {6, 7}) or (
        series == INTEL_LGA1151_NEW_SERIES and generation in {8, 9}
    )


class IdentifierConflictError(Exception):
    """A normalized identifier already belongs to another catalog item."""


class PostgresConnection:
    """Adapt existing parameterized catalog queries to psycopg transactions."""

    def __init__(self, database_url: SecretStr) -> None:
        """Open a PostgreSQL connection without exposing credentials in logs."""
        self._connection = psycopg.connect(
            database_url.get_secret_value(), row_factory=dict_row, connect_timeout=5
        )

    def __enter__(self) -> PostgresConnection:
        """Enter a transaction context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit or roll back and close the connection."""
        self._connection.__exit__(exc_type, exc_value, traceback)

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> Any:
        """Run one query with positional parameters."""
        return self._connection.execute(query.replace("?", "%s"), parameters)

    def executemany(self, query: str, rows: list[tuple[Any, ...]]) -> None:
        """Run one statement for a batch of parameter rows."""
        with self._connection.cursor() as cursor:
            cursor.executemany(query.replace("?", "%s"), rows)


class Catalog:
    """Persist hardware records and their alternate printed identifiers."""

    def __init__(self, path: Path | None = None, *, database_url: SecretStr | None = None) -> None:
        """Initialize the database schema at the configured path.

        Args:
            path: SQLite database file location for offline tools.
            database_url: PostgreSQL connection URL for the runtime service.
        """
        if (path is None) == (database_url is None):
            raise ValueError("Provide exactly one catalog path or database URL")
        self.path = path
        self.database_url = database_url
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            schema = """
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
            if database_url is None:
                connection.executescript(schema)
            else:
                for statement in schema.split(";"):
                    if statement.strip():
                        connection.execute(statement)

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
                """INSERT INTO price_observations
                (item_id, retailer, source_url, identifier, price_cents, observed_at)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
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

    def _connect(self) -> Any:
        """Create a transactional database connection with a finite timeout."""
        if self.database_url is not None:
            return PostgresConnection(self.database_url)
        if self.path is None:
            raise RuntimeError("Catalog path is missing")
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection

    def count_items(self) -> int:
        """Count published items for deployment readiness checks."""
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM items").fetchone()
        return int(row["total"])

    def count_category(self, category: Category) -> int:
        """Count one hardware category without loading the whole catalog."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM items WHERE category = ?", (category.value,)
            ).fetchone()
        return int(row["total"])

    def page_category(
        self, category: Category, *, limit: int = 20, offset: int = 0
    ) -> tuple[int, list[Item]]:
        """Read a stable page of one category with complete catalog details.

        Args:
            category: Hardware category to browse.
            limit: Maximum number of items in the page.
            offset: Number of sorted items to skip.

        Returns:
            Total category count and the requested item page.
        """
        with self._connect() as connection:
            total = connection.execute(
                "SELECT COUNT(*) AS total FROM items WHERE category = ?", (category.value,)
            ).fetchone()["total"]
            rows = connection.execute(
                """SELECT id FROM items WHERE category = ?
                ORDER BY brand, model, id LIMIT ? OFFSET ?""",
                (category.value, limit, offset),
            ).fetchall()
        items = [item for row in rows if (item := self.get_item(row["id"])) is not None]
        return int(total), items

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
        except (sqlite3.IntegrityError, psycopg.IntegrityError) as error:
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

    def list_socket_related(
        self,
        socket: str,
        category: Category,
        *,
        source_item: Item,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[int, list[Item]]:
        """Find catalog records with the same unambiguous reported socket.

        Args:
            socket: Normalized socket of the source hardware.
            category: Opposite hardware category to search.
            source_item: Item whose socket relationship is being requested.
            limit: Maximum number of records returned.
            offset: Position in the stable, alphabetic result order.

        Returns:
            Total matches and the requested page of complete catalog items.
        """
        if category not in {Category.CPU, Category.MOTHERBOARD}:
            raise ValueError("Socket relationships require a CPU or motherboard category")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, brand, model FROM items WHERE category = ? ORDER BY brand, model, id",
                (category.value,),
            ).fetchall()
            source_rows = connection.execute(
                """SELECT source_records.item_id, dataset, file_name, row_number, payload_json
                FROM source_records JOIN items ON items.id = source_records.item_id
                WHERE items.category = ? ORDER BY dataset, file_name, row_number""",
                (category.value,),
            ).fetchall()
        sources: dict[str, list[dict[str, Any]]] = {}
        for row in source_rows:
            sources.setdefault(row["item_id"], []).append(
                {"dataset": row["dataset"], "data": json.loads(row["payload_json"])}
            )
        matching_ids: list[str] = []
        source_chipset = source_item.specifications.get("chipset")
        source_board_chipset = (
            source_chipset.value
            if source_item.category is Category.MOTHERBOARD
            and source_chipset is not None
            and isinstance(source_chipset.value, str)
            else None
        )
        for row in rows:
            specifications = build_specifications(category, sources.get(row["id"], []), row["id"])
            specification = specifications.get("socket")
            chipset_specification = specifications.get("chipset")
            board_chipset = (
                chipset_specification.value
                if category is Category.MOTHERBOARD
                and chipset_specification is not None
                and isinstance(chipset_specification.value, str)
                else source_board_chipset
            )
            if (
                specification is not None
                and isinstance(specification.value, str)
                and re.sub(r"\s+", "", specification.value).upper()
                == re.sub(r"\s+", "", socket).upper()
                and has_consistent_socket_vendor(category, row["brand"], socket, board_chipset)
                and (
                    re.sub(r"\s+", "", socket).upper() != "LGA1151"
                    or has_supported_intel_lga1151_generation(
                        board_chipset,
                        row["model"] if category is Category.CPU else source_item.model,
                    )
                )
            ):
                matching_ids.append(row["id"])
        page: list[Item] = []
        for item_id in matching_ids[offset : offset + limit]:
            item = self.get_item(item_id)
            if item is not None:
                page.append(item)
        return len(matching_ids), page

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
                is_primary = CASE WHEN item_images.is_primary = 1 OR excluded.is_primary = 1
                                  THEN 1 ELSE 0 END""",
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
