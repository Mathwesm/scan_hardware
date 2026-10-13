"""Copy a validated SQLite catalog into PostgreSQL without changing stable IDs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from loguru import logger
from pydantic import SecretStr

from scan_hardware.services.catalog import Catalog

TABLE_COLUMNS = {
    "items": ("id", "category", "brand", "model", "image_url", "image_digest"),
    "identifiers": ("normalized", "display", "item_id"),
    "source_records": (
        "dataset",
        "file_name",
        "row_number",
        "payload_json",
        "item_id",
        "status",
        "reason",
    ),
    "item_images": ("item_id", "file_name", "view", "width", "height", "is_primary"),
    "price_observations": (
        "item_id",
        "retailer",
        "source_url",
        "identifier",
        "price_cents",
        "observed_at",
    ),
}


def _signature(connection: Any, table: str, columns: tuple[str, ...]) -> tuple[int, str]:
    """Count and hash all rows in primary-key order for exact migration validation."""
    order = {
        "items": "id",
        "identifiers": "normalized",
        "source_records": "dataset, file_name, row_number",
        "item_images": "item_id, file_name",
        "price_observations": "item_id, source_url, observed_at",
    }[table]
    # table and columns come exclusively from the fixed allowlist above.
    cursor = connection.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}")  # noqa: S608
    digest = hashlib.sha256()
    count = 0
    while rows := cursor.fetchmany(1000):
        for row in rows:
            digest.update(json.dumps(tuple(row), ensure_ascii=False).encode("utf-8"))
            digest.update(b"\n")
            count += 1
    return count, digest.hexdigest()


def migrate_catalog(sqlite_path: Path, database_url: SecretStr) -> dict[str, int]:
    """Copy five normalized tables atomically and verify exact row contents.

    Args:
        sqlite_path: Published local catalog file.
        database_url: PostgreSQL URL, including credentials.

    Returns:
        Row counts for all copied tables.

    Raises:
        FileNotFoundError: The source catalog is absent.
        RuntimeError: The destination differs from the source.
    """
    if not sqlite_path.is_file():
        raise FileNotFoundError(sqlite_path)
    Catalog(database_url=database_url)
    counts: dict[str, int] = {}
    with sqlite3.connect(sqlite_path) as source:
        source.execute("BEGIN")
        with psycopg.connect(database_url.get_secret_value(), connect_timeout=5) as destination:
            destination.execute(
                """CREATE TABLE IF NOT EXISTS catalog_imports (
                source_digest TEXT PRIMARY KEY,
                imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            signatures = {
                table: _signature(source, table, columns)
                for table, columns in TABLE_COLUMNS.items()
            }
            manifest_digest = hashlib.sha256(
                json.dumps(signatures, sort_keys=True).encode("utf-8")
            ).hexdigest()
            prior = destination.execute("SELECT source_digest FROM catalog_imports").fetchone()
            if prior is not None:
                if prior[0] != manifest_digest:
                    raise RuntimeError(
                        "PostgreSQL catalog was imported from another SQLite version"
                    )
                return {table: signature[0] for table, signature in signatures.items()}
            for table, columns in TABLE_COLUMNS.items():
                source_count, source_digest = signatures[table]
                destination_count, destination_digest = _signature(destination, table, columns)
                if destination_count == 0:
                    placeholders = ", ".join(["%s"] * len(columns))
                    # Every SQL identifier comes from TABLE_COLUMNS, never from input.
                    statement = (
                        f"INSERT INTO {table} ({', '.join(columns)}) "  # noqa: S608
                        f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                    )
                    cursor = source.execute(f"SELECT {', '.join(columns)} FROM {table}")  # noqa: S608
                    with destination.cursor() as target:
                        while rows := cursor.fetchmany(1000):
                            target.executemany(statement, rows)
                    destination_count, destination_digest = _signature(destination, table, columns)
                if (source_count, source_digest) != (destination_count, destination_digest):
                    raise RuntimeError(f"PostgreSQL catalog differs from SQLite in {table}")
                counts[table] = source_count
                logger.info("Catalog table verified table={} rows={}", table, source_count)
            destination.execute(
                "INSERT INTO catalog_imports (source_digest) VALUES (%s)", (manifest_digest,)
            )
    return counts
