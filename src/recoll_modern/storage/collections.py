"""SQLite persistence for collection metadata and cleanup paths."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime
from sqlite3 import Connection

from recoll_modern.domain.collections import CollectionPage, CollectionPaths, normalize_name
from recoll_modern.domain.errors import AppError
from recoll_modern.domain.jobs import Job
from recoll_modern.domain.models import Collection, CollectionCreate, CollectionPatch, _Unset
from recoll_modern.storage.database import Database
from recoll_modern.storage.jobs import JobRepository


class SQLiteCollectionRepository:
    """Store collections in SQLite while preserving domain error contracts."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, collection: CollectionCreate) -> Collection:
        """Store a new collection, retrying the exceptionally unlikely ID collision."""
        name, name_key = normalize_name(collection.name)
        created_at = datetime.now(UTC)
        timestamp = created_at.isoformat()

        while True:
            collection_id = f"c{secrets.token_hex(5)}"
            try:
                with self._database.transaction() as connection:
                    connection.execute(
                        "INSERT INTO collections "
                        "(id, name, name_key, description, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            collection_id,
                            name,
                            name_key,
                            collection.description,
                            timestamp,
                            timestamp,
                        ),
                    )
            except sqlite3.IntegrityError as error:
                if _is_name_key_conflict(error):
                    raise _collection_name_taken() from None
                if _is_id_conflict(error):
                    continue
                raise
            return Collection(
                id=collection_id,
                name=name,
                description=collection.description,
                created_at=created_at,
                updated_at=created_at,
            )

    def get(self, collection_id: str) -> Collection | None:
        """Return the collection with this ID, if present."""
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, name, description, created_at, updated_at "
                "FROM collections WHERE id = ?",
                (collection_id,),
            ).fetchone()
        return _collection_from_row(row) if row is not None else None

    def list(self, limit: int, offset: int) -> CollectionPage:
        """Return a stable metadata page and the count before pagination."""
        with self._database.connect() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM collections").fetchone()[0])
            rows = connection.execute(
                "SELECT id, name, description, created_at, updated_at "
                "FROM collections ORDER BY created_at, id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_collection_from_row(row) for row in rows], total

    def patch(self, collection_id: str, patch: CollectionPatch) -> Collection:
        """Persist supplied metadata fields and return the changed collection."""
        current = self.get(collection_id)
        if current is None:
            raise _collection_not_found()

        name = current.name if patch.name is None else normalize_name(patch.name)[0]
        name_key = normalize_name(name)[1]
        description = (
            current.description if isinstance(patch.description, _Unset) else patch.description
        )
        updated_at = datetime.now(UTC)
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    "UPDATE collections "
                    "SET name = ?, name_key = ?, description = ?, updated_at = ? "
                    "WHERE id = ?",
                    (name, name_key, description, updated_at.isoformat(), collection_id),
                )
                if cursor.rowcount == 0:
                    raise _collection_not_found()
        except sqlite3.IntegrityError as error:
            if _is_name_key_conflict(error):
                raise _collection_name_taken() from None
            raise
        return Collection(
            id=collection_id,
            name=name,
            description=description,
            created_at=current.created_at,
            updated_at=updated_at,
        )

    def delete(self, collection_id: str) -> CollectionPaths:
        """Return effective canonical paths before SQLite cascades memberships away."""
        with self._database.transaction() as connection:
            return self._delete_in_transaction(connection, collection_id)

    def delete_with_cleanup(self, collection_id: str, jobs: JobRepository) -> Job:
        """Delete metadata and queue its index cleanup in one durable transaction."""
        with self._database.transaction() as connection:
            paths = self._delete_in_transaction(connection, collection_id)
            return jobs.enqueue_in_transaction(
                connection, "collection_cleanup", {"version": 1, "paths": paths}, False
            )

    def _delete_in_transaction(
        self, connection: Connection, collection_id: str
    ) -> CollectionPaths:
        paths = [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT paths.relative_path "
                "FROM document_paths AS paths "
                "JOIN ("
                "  SELECT direct.document_hash "
                "  FROM direct_memberships AS direct "
                "  WHERE direct.collection_id = ? "
                "  UNION "
                "  SELECT rule_memberships.document_hash "
                "  FROM rule_memberships "
                "  JOIN directory_rules AS rules ON rules.id = rule_memberships.rule_id "
                "  WHERE rules.collection_id = ? "
                "    AND NOT EXISTS ("
                "      SELECT 1 FROM membership_exclusions AS exclusions "
                "      WHERE exclusions.collection_id = rules.collection_id "
                "        AND exclusions.document_hash = rule_memberships.document_hash"
                "    )"
                ") AS members ON members.document_hash = paths.document_hash "
                "WHERE paths.is_canonical = 1 "
                "ORDER BY paths.relative_path",
                (collection_id, collection_id),
            )
        ]
        deleted = connection.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        if deleted.rowcount != 1:
            raise _collection_not_found()
        return paths


SqliteCollectionRepository = SQLiteCollectionRepository


def _collection_from_row(row: sqlite3.Row) -> Collection:
    """Convert a SQLite metadata row to the domain type."""
    return Collection(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]) if row["description"] is not None else None,
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def _is_name_key_conflict(error: sqlite3.IntegrityError) -> bool:
    """Identify the unique constraint that represents duplicate collection names."""
    return "collections.name_key" in str(error)


def _is_id_conflict(error: sqlite3.IntegrityError) -> bool:
    """Identify an opaque ID collision so generation can safely retry."""
    return "collections.id" in str(error)


def _collection_name_taken() -> AppError:
    """Create the standard duplicate collection name error."""
    return AppError(
        code="collection_name_taken",
        message="A collection with that name already exists",
        status=409,
    )


def _collection_not_found() -> AppError:
    """Create the standard collection absence error."""
    return AppError(
        code="collection_not_found",
        message="Collection was not found",
        status=404,
    )
