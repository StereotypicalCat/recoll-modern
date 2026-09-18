"""Tests for the initial SQLite schema migration."""

import sqlite3
from pathlib import Path

import pytest

from recoll_modern.storage import database as database_module
from recoll_modern.storage.database import Database

EXPECTED_TABLES = {
    "schema_migrations",
    "collections",
    "documents",
    "document_paths",
    "direct_memberships",
    "directory_rules",
    "directory_rule_exclusions",
    "rule_memberships",
    "membership_exclusions",
    "jobs",
    "job_file_errors",
    "users",
    "sessions",
}


@pytest.fixture
def database(tmp_path: Path) -> Database:
    """Provide an isolated database for each test."""
    return Database(tmp_path / "recoll-modern.sqlite3")


def test_migrate_creates_all_tables_and_records_version(database: Database) -> None:
    """Fail if initial migration omits schema or is not recorded exactly once."""
    database.migrate()
    database.migrate()

    connection = database.connect()
    try:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    finally:
        connection.close()

    assert EXPECTED_TABLES <= names
    assert versions == [1]


def test_one_canonical_path_per_document(database: Database) -> None:
    """Fail if the partial unique index allows two canonical paths per document."""
    database.migrate()
    _seed_document_with_two_paths(database)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute("UPDATE document_paths SET is_canonical = 1 WHERE id = 1")
            connection.execute("UPDATE document_paths SET is_canonical = 1 WHERE id = 2")

    connection = database.connect()
    try:
        canonical_count = connection.execute(
            "SELECT COUNT(*) FROM document_paths WHERE is_canonical = 1"
        ).fetchone()[0]
    finally:
        connection.close()
    assert canonical_count == 0


def test_foreign_keys_reject_orphaned_document_path(database: Database) -> None:
    """Fail if a document path can refer to a non-existent document."""
    database.migrate()

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO document_paths VALUES (?, ?, ?, ?, ?, ?)",
                (1, "missing", "books/a.pdf", 1, "2026-09-18T00:00:00+00:00", None),
            )


def test_collection_name_keys_are_unique(database: Database) -> None:
    """Fail if two application-normalized collection names can coexist."""
    database.migrate()

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            _insert_collection(connection, "c1", "Café", "café")
            _insert_collection(connection, "c2", "CAFÉ", "café")


def test_directory_rules_are_unique_within_a_collection(database: Database) -> None:
    """Fail if a collection can contain the same directory rule twice."""
    database.migrate()

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            _insert_collection(connection, "c1", "Books", "books")
            _insert_directory_rule(connection, "r1", "c1", "books")
            _insert_directory_rule(connection, "r2", "c1", "books")


def test_deletes_cascade_to_related_rows(database: Database) -> None:
    """Fail if removing a collection leaves membership or rule records behind."""
    database.migrate()

    with database.transaction() as connection:
        _insert_collection(connection, "c1", "Books", "books")
        _insert_document(connection, "hash")
        connection.execute(
            "INSERT INTO direct_memberships VALUES (?, ?, ?)",
            ("c1", "hash", "2026-09-18T00:00:00+00:00"),
        )
        _insert_directory_rule(connection, "r1", "c1", "books")
        connection.execute(
            "INSERT INTO directory_rule_exclusions VALUES (?, ?)", ("r1", "books/private")
        )
        connection.execute(
            "INSERT INTO rule_memberships VALUES (?, ?, ?)",
            ("r1", "hash", "2026-09-18T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO membership_exclusions VALUES (?, ?, ?)",
            ("c1", "hash", "2026-09-18T00:00:00+00:00"),
        )
        connection.execute("DELETE FROM collections WHERE id = ?", ("c1",))

    connection = database.connect()
    try:
        for table in (
            "direct_memberships",
            "directory_rules",
            "directory_rule_exclusions",
            "rule_memberships",
            "membership_exclusions",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    finally:
        connection.close()


def test_migrations_are_atomic(database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if a bad later migration leaves earlier schema changes committed."""
    monkeypatch.setattr(
        database_module,
        "_migration_scripts",
        lambda: [
            (
                1,
                "CREATE TABLE schema_migrations("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);"
                "CREATE TABLE first_change(id INTEGER PRIMARY KEY);",
            ),
            (2, "CREATE TABLE broken_change(id INTEGER PRIMARY KEY); INVALID SQL;"),
        ],
    )

    with pytest.raises(sqlite3.OperationalError):
        database.migrate()

    connection = database.connect()
    try:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        connection.close()
    assert "first_change" not in names
    assert "broken_change" not in names


def test_migrations_apply_in_version_order(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail if an out-of-order resource list cannot establish its prerequisite schema."""
    monkeypatch.setattr(
        database_module,
        "_migration_scripts",
        lambda: [
            (2, "CREATE TABLE second_change(id INTEGER PRIMARY KEY);"),
            (
                1,
                "CREATE TABLE schema_migrations("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);"
                "CREATE TABLE first_change(id INTEGER PRIMARY KEY);",
            ),
        ],
    )

    database.migrate()

    connection = database.connect()
    try:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    finally:
        connection.close()
    assert versions == [1, 2]


def test_migrations_refuse_duplicate_versions(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail if two scripts with one version could be applied ambiguously."""
    monkeypatch.setattr(
        database_module,
        "_migration_scripts",
        lambda: [(1, "SELECT 1;"), (1, "SELECT 1;")],
    )

    with pytest.raises(ValueError, match="duplicate migration version: 1"):
        database.migrate()


def _seed_document_with_two_paths(database: Database) -> None:
    with database.transaction() as connection:
        _insert_document(connection, "hash")
        connection.execute(
            "INSERT INTO document_paths VALUES (?, ?, ?, ?, ?, ?)",
            (1, "hash", "books/a.pdf", 0, "2026-09-18T00:00:00+00:00", None),
        )
        connection.execute(
            "INSERT INTO document_paths VALUES (?, ?, ?, ?, ?, ?)",
            (2, "hash", "books/b.pdf", 0, "2026-09-18T00:00:00+00:00", None),
        )


def _insert_collection(
    connection: sqlite3.Connection, collection_id: str, name: str, name_key: str
) -> None:
    connection.execute(
        "INSERT INTO collections VALUES (?, ?, ?, ?, ?, ?)",
        (
            collection_id,
            name,
            name_key,
            None,
            "2026-09-18T00:00:00+00:00",
            "2026-09-18T00:00:00+00:00",
        ),
    )


def _insert_document(connection: sqlite3.Connection, content_hash: str) -> None:
    connection.execute(
        "INSERT INTO documents VALUES (?, ?, ?, ?, ?)",
        (content_hash, 1, "present", "2026-09-18T00:00:00+00:00", "2026-09-18T00:00:00+00:00"),
    )


def _insert_directory_rule(
    connection: sqlite3.Connection, rule_id: str, collection_id: str, relative_path: str
) -> None:
    connection.execute(
        "INSERT INTO directory_rules VALUES (?, ?, ?, ?, ?)",
        (
            rule_id,
            collection_id,
            relative_path,
            "2026-09-18T00:00:00+00:00",
            "2026-09-18T00:00:00+00:00",
        ),
    )
