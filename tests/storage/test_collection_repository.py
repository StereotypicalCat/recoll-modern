"""Tests for SQLite collection persistence."""

from pathlib import Path

import pytest

from recoll_modern.domain.errors import AppError
from recoll_modern.domain.models import CollectionCreate, CollectionPatch
from recoll_modern.storage.collections import SQLiteCollectionRepository
from recoll_modern.storage.database import Database


@pytest.fixture
def database(tmp_path: Path) -> Database:
    """Provide a migrated database for each repository test."""
    result = Database(tmp_path / "recoll-modern.sqlite3")
    result.migrate()
    return result


@pytest.fixture
def repository(database: Database) -> SQLiteCollectionRepository:
    """Create the repository under test."""
    return SQLiteCollectionRepository(database)


def test_create_assigns_opaque_id_and_persists_optional_description(
    repository: SQLiteCollectionRepository,
) -> None:
    """Fail if creation leaks a caller-controlled ID or loses the description."""
    collection = repository.create(CollectionCreate(name="Tech Books", description="Shelf one"))

    assert collection.id.startswith("c")
    assert len(collection.id) == 11
    assert collection.name == "Tech Books"
    assert collection.description == "Shelf one"
    assert repository.get(collection.id) == collection


def test_create_maps_normalized_name_conflict_to_app_error(
    repository: SQLiteCollectionRepository,
) -> None:
    """Fail if equivalent Unicode names expose a raw SQLite uniqueness error."""
    repository.create(CollectionCreate(name="Stra\u00dfe"))

    with pytest.raises(AppError) as caught:
        repository.create(CollectionCreate(name="STRASSE"))

    assert caught.value.code == "collection_name_taken"
    assert caught.value.status == 409


def test_list_returns_page_and_total_count(repository: SQLiteCollectionRepository) -> None:
    """Fail if list pagination omits the full collection count or returns the wrong page."""
    first = repository.create(CollectionCreate(name="One"))
    second = repository.create(CollectionCreate(name="Two"))
    repository.create(CollectionCreate(name="Three"))

    page, total = repository.list(limit=1, offset=1)

    assert total == 3
    assert page == [second]
    assert first not in page


def test_patch_updates_only_requested_fields(repository: SQLiteCollectionRepository) -> None:
    """Fail if a rename alters an unchanged description or does not persist the new name."""
    collection = repository.create(CollectionCreate(name="Tech Books", description="Shelf one"))

    changed = repository.patch(collection.id, CollectionPatch(name="Reference"))

    assert changed.name == "Reference"
    assert changed.description == "Shelf one"
    assert repository.get(collection.id) == changed


def test_patch_can_clear_description(repository: SQLiteCollectionRepository) -> None:
    """Fail if an explicit null description cannot remove existing metadata."""
    collection = repository.create(CollectionCreate(name="Tech Books", description="Shelf one"))

    changed = repository.patch(collection.id, CollectionPatch(description=None))

    assert changed.description is None
    assert repository.get(collection.id) == changed


def test_delete_returns_canonical_paths_before_memberships_cascade(
    database: Database, repository: SQLiteCollectionRepository
) -> None:
    """Fail if deletion loses the paths that must later be reindexed."""
    collection = repository.create(CollectionCreate(name="Tech Books"))
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?)",
            ("a" * 64, 1, "present", "2026-09-18T00:00:00+00:00", "2026-09-18T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO document_paths "
            "(document_hash, relative_path, is_canonical, last_seen_at, missing_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("a" * 64, "books/a.pdf", 1, "2026-09-18T00:00:00+00:00", None),
        )
        connection.execute(
            "INSERT INTO direct_memberships VALUES (?, ?, ?)",
            (collection.id, "a" * 64, "2026-09-18T00:00:00+00:00"),
        )

    paths = repository.delete(collection.id)

    assert paths == ["books/a.pdf"]
    assert repository.get(collection.id) is None
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM direct_memberships").fetchone()[0] == 0


def test_delete_includes_non_excluded_rule_memberships(
    database: Database, repository: SQLiteCollectionRepository
) -> None:
    """Fail if deletion misses canonical paths contributed by persistent rules."""
    collection = repository.create(CollectionCreate(name="Tech Books"))
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?)",
            ("b" * 64, 1, "present", "2026-09-18T00:00:00+00:00", "2026-09-18T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO document_paths "
            "(document_hash, relative_path, is_canonical, last_seen_at, missing_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("b" * 64, "books/b.pdf", 1, "2026-09-18T00:00:00+00:00", None),
        )
        connection.execute(
            "INSERT INTO directory_rules VALUES (?, ?, ?, ?, ?)",
            (
                "r1",
                collection.id,
                "books",
                "2026-09-18T00:00:00+00:00",
                "2026-09-18T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO rule_memberships VALUES (?, ?, ?)",
            ("r1", "b" * 64, "2026-09-18T00:00:00+00:00"),
        )

    assert repository.delete(collection.id) == ["books/b.pdf"]


def test_repository_does_not_leak_sqlite_error_for_name_conflicts(
    repository: SQLiteCollectionRepository,
) -> None:
    """Fail if the domain boundary exposes database implementation failures."""
    repository.create(CollectionCreate(name="Same"))

    with pytest.raises(AppError):
        repository.create(CollectionCreate(name="same"))
