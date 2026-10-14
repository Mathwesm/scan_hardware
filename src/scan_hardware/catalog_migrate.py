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

_CATEGORY_SOURCE_FILE = {
    "ram": "Memory.csv",
    "psu": "PSU.csv",
    "case": "Case.csv",
    "cooler": "Cooler.csv",
    "storage": "Storage.csv",
}


def _rows(connection: Any, query: str) -> list[tuple[Any, ...]]:
    """Read ordered rows from a fixed migration query."""
    return [tuple(row) for row in connection.execute(query).fetchall()]


def _category_rows(
    connection: Any, table: str, category: str, source_file: str
) -> list[tuple[Any, ...]]:
    """Read one category's transfer rows in stable order."""
    columns = ", ".join(f"{table}.{column}" for column in TABLE_COLUMNS[table])
    if table == "source_records":
        query = f"SELECT {columns} FROM {table} WHERE file_name = %s ORDER BY row_number"  # noqa: S608
        statement = (
            query.replace("%s", "?") if isinstance(connection, sqlite3.Connection) else query
        )
        return [tuple(row) for row in connection.execute(statement, (source_file,)).fetchall()]
    if table == "items":
        query = f"SELECT {columns} FROM items WHERE category = %s ORDER BY id"  # noqa: S608
    else:
        query = (
            f"SELECT {columns} FROM {table} JOIN items ON items.id = {table}.item_id "  # noqa: S608
            f"WHERE items.category = %s ORDER BY {table}.{TABLE_COLUMNS[table][0]}"
        )
    statement = query.replace("%s", "?") if isinstance(connection, sqlite3.Connection) else query
    return [tuple(row) for row in connection.execute(statement, (category,)).fetchall()]


def _extend_catalog(source: Any, destination: Any, previous: str, current: str) -> None:
    """Append entirely new categories without replacing existing PostgreSQL records."""
    source_categories = {row[0] for row in _rows(source, "SELECT DISTINCT category FROM items")}
    destination_categories = {
        row[0] for row in _rows(destination, "SELECT DISTINCT category FROM items")
    }
    added = source_categories - destination_categories
    if not added or not added.issubset(_CATEGORY_SOURCE_FILE):
        raise RuntimeError("PostgreSQL catalog was imported from another SQLite version")
    for table in ("items", "identifiers", "source_records"):
        if table == "source_records":
            files = tuple(_CATEGORY_SOURCE_FILE[category] for category in sorted(added))
            placeholders = ", ".join(["%s"] * len(files))
            query = (
                "SELECT dataset, file_name, row_number, payload_json, item_id, status, reason "  # noqa: S608
                f"FROM source_records WHERE file_name NOT IN ({placeholders}) "
                "ORDER BY dataset, file_name, row_number"
            )
            old_source = [
                tuple(row) for row in source.execute(query.replace("%s", "?"), files).fetchall()
            ]
            old_destination = [tuple(row) for row in destination.execute(query, files).fetchall()]
        else:
            if table == "items":
                columns = "items.id, items.category, items.brand, items.model, items.image_url"
                query = f"SELECT {columns} FROM items WHERE category = %s ORDER BY id"  # noqa: S608
            else:
                columns = ", ".join(f"{table}.{column}" for column in TABLE_COLUMNS[table])
                query = (
                    f"SELECT {columns} FROM identifiers "  # noqa: S608
                    "JOIN items ON items.id = identifiers.item_id "
                    "WHERE items.category = %s ORDER BY identifiers.normalized"
                )
            old_source = [
                tuple(row)
                for category in sorted(destination_categories)
                for row in source.execute(query.replace("%s", "?"), (category,)).fetchall()
            ]
            old_destination = [
                tuple(row)
                for category in sorted(destination_categories)
                for row in destination.execute(query, (category,)).fetchall()
            ]
        if old_source != old_destination:
            raise RuntimeError("PostgreSQL catalog was imported from another SQLite version")
    for category in sorted(added):
        for table, column_names in TABLE_COLUMNS.items():
            rows = _category_rows(source, table, category, _CATEGORY_SOURCE_FILE[category])
            if rows:
                placeholders = ", ".join(["%s"] * len(column_names))
                statement = (
                    f"INSERT INTO {table} ({', '.join(column_names)}) "  # noqa: S608
                    f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                )
                with destination.cursor() as target:
                    target.executemany(statement, rows)
            if rows != _category_rows(
                destination, table, category, _CATEGORY_SOURCE_FILE[category]
            ):
                raise RuntimeError(
                    f"PostgreSQL {category} extension differs from SQLite in {table}"
                )
    destination.execute(
        "UPDATE catalog_imports SET source_digest = %s WHERE source_digest = %s",
        (current, previous),
    )
    logger.info("Catalog extension verified categories={}", sorted(added))


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
                    _extend_catalog(source, destination, prior[0], manifest_digest)
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
