"""Tests for collection identity and domain behavior."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pytest

from recoll_modern.domain.collections import (
    CollectionPage,
    CollectionPaths,
    CollectionRepository,
    CollectionService,
    normalize_name,
)
from recoll_modern.domain.errors import AppError
from recoll_modern.domain.models import Collection, CollectionCreate, CollectionPatch, _Unset


@dataclass
class MemoryCollectionRepository:
    """Small real-behavior repository used to isolate service behavior."""

    collections: dict[str, Collection] = field(default_factory=dict)
    created: list[CollectionCreate] = field(default_factory=list)

    def create(self, collection: CollectionCreate) -> Collection:
        identifier = f"c{len(self.collections):010x}"
        result = Collection(id=identifier, name=collection.name, description=collection.description)
        self.collections[identifier] = result
        self.created.append(collection)
        return result

    def get(self, collection_id: str) -> Collection | None:
        return self.collections.get(collection_id)

    def list(self, limit: int, offset: int) -> CollectionPage:
        values = list(self.collections.values())
        return values[offset : offset + limit], len(values)

    def patch(self, collection_id: str, patch: CollectionPatch) -> Collection:
        collection = self.collections[collection_id]
        description = (
            collection.description
            if isinstance(patch.description, _Unset)
            else patch.description
        )
        result = Collection(
            id=collection.id,
            name=patch.name if patch.name is not None else collection.name,
            description=description,
        )
        self.collections[collection_id] = result
        return result

    def delete(self, collection_id: str) -> CollectionPaths:
        del self.collections[collection_id]
        return []


@pytest.fixture
def repository() -> CollectionRepository:
    """Return an in-memory repository for service-level behavior tests."""
    return MemoryCollectionRepository()


@pytest.fixture
def service(repository: CollectionRepository) -> CollectionService:
    """Create the service under test."""
    return CollectionService(repository)


def test_collection_ids_are_opaque(service: CollectionService) -> None:
    """Fail if a collection ID is not the required opaque server value."""
    collection = service.create(CollectionCreate(name="Tech Books"))

    assert re.fullmatch(r"c[0-9a-f]{10}", collection.id)


def test_normalize_name_preserves_display_name_and_casefolds_nfc() -> None:
    """Fail if display names are altered or equivalent Unicode names get different keys."""
    name, name_key = normalize_name("Stra\u00dfe")

    assert name == "Stra\u00dfe"
    assert name_key == "strasse"


def test_normalize_name_rejects_whitespace_only_name() -> None:
    """Fail if a name without a visible character can reach storage."""
    with pytest.raises(AppError) as caught:
        normalize_name(" \t\n ")

    assert caught.value.code == "validation_failed"


def test_patch_rejects_unknown_collection(service: CollectionService) -> None:
    """Fail if an update silently succeeds for a missing collection."""
    with pytest.raises(AppError) as caught:
        service.patch("c000000000", CollectionPatch(name="Reference"))

    assert caught.value.code == "collection_not_found"
