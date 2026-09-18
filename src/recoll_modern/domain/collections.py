"""Collection lifecycle behavior independent from persistence and indexing."""

from __future__ import annotations

import unicodedata
from typing import Protocol

from recoll_modern.domain.errors import AppError
from recoll_modern.domain.models import Collection, CollectionCreate, CollectionPatch

type CollectionPage = tuple[list[Collection], int]
type CollectionPaths = list[str]


class CollectionRepository(Protocol):
    """Persistence operations required by collection lifecycle behavior."""

    def create(self, collection: CollectionCreate) -> Collection:
        """Persist a new collection."""

    def get(self, collection_id: str) -> Collection | None:
        """Return a collection when it exists."""

    def list(self, limit: int, offset: int) -> CollectionPage:
        """Return one page of collections and their total count."""

    def patch(self, collection_id: str, patch: CollectionPatch) -> Collection:
        """Persist changed collection metadata."""

    def delete(self, collection_id: str) -> CollectionPaths:
        """Delete a collection and return its formerly affected canonical paths."""


def normalize_name(value: str) -> tuple[str, str]:
    """Validate a display name and derive its NFC, case-folded comparison key."""
    normalized = unicodedata.normalize("NFC", value)
    if not normalized.strip():
        raise AppError(
            code="validation_failed",
            message="Collection name must contain at least one non-whitespace character",
            status=422,
            details={"field": "name"},
        )
    return value, normalized.casefold()


class CollectionService:
    """Coordinate collection behavior while keeping indexing out of metadata changes."""

    def __init__(self, repository: CollectionRepository) -> None:
        self._repository = repository

    def create(self, collection: CollectionCreate) -> Collection:
        """Create a collection after validating its display name."""
        normalize_name(collection.name)
        return self._repository.create(collection)

    def get(self, collection_id: str) -> Collection:
        """Fetch one collection or report the stable not-found error."""
        collection = self._repository.get(collection_id)
        if collection is None:
            raise _collection_not_found()
        return collection

    def list(self, limit: int, offset: int) -> CollectionPage:
        """Return a page of collection metadata."""
        return self._repository.list(limit, offset)

    def patch(self, collection_id: str, patch: CollectionPatch) -> Collection:
        """Change collection metadata without scheduling any indexing work."""
        self.get(collection_id)
        if patch.name is not None:
            normalize_name(patch.name)
        return self._repository.patch(collection_id, patch)

    def delete(self, collection_id: str) -> CollectionPaths:
        """Delete collection metadata and expose paths for a later cleanup job."""
        self.get(collection_id)
        return self._repository.delete(collection_id)


def _collection_not_found() -> AppError:
    """Create the standard collection absence error."""
    return AppError(
        code="collection_not_found",
        message="Collection was not found",
        status=404,
    )
