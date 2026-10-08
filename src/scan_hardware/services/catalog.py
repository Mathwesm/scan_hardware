"""SQLite catalog for independently running scanner deployments."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from scan_hardware.core.matching import normalize_identifier
from scan_hardware.models.item import Category, Item, ItemInput


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
                """
            )

    def _connect(self) -> sqlite3.Connection:
        """Create a connection with foreign keys and a finite lock timeout."""
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection

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
        return Item(
            id=row["id"],
            category=Category(row["category"]),
            brand=row["brand"],
            model=row["model"],
            image_url=row["image_url"],
            identifiers=[alias["display"] for alias in aliases],
            has_local_image=row["image_digest"] is not None,
            local_image_url=f"/items/{item_id}/image" if row["image_digest"] else None,
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
        return [
            Item(
                id=row["id"],
                category=Category(row["category"]),
                brand=row["brand"],
                model=row["model"],
                image_url=row["image_url"],
                identifiers=aliases.get(row["id"], []),
                has_local_image=row["image_digest"] is not None,
                local_image_url=f"/items/{row['id']}/image" if row["image_digest"] else None,
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
