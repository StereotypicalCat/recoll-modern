"""Tests for SQLite connection and transaction behavior."""

import sqlite3
from pathlib import Path

import pytest

from recoll_modern.domain.errors import AppError
from recoll_modern.indexing.paths import PathPolicyError
from recoll_modern.storage.database import Database


@pytest.fixture
def database(tmp_path: Path) -> Database:
    """Provide an isolated database for each test."""
    return Database(tmp_path / "recoll-modern.sqlite3")


def test_connect_configures_sqlite_policy(database: Database) -> None:
    """Fail if a connection stops enforcing the required SQLite safeguards."""
    connection = database.connect()
    try:
        assert connection.row_factory is sqlite3.Row
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        connection.close()


def test_transaction_commits_and_closes_connection(database: Database) -> None:
    """Fail if a successful transaction loses data or leaks its connection."""
    database.migrate()
    with database.transaction() as transaction_connection:
        transaction_connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
            ("u1", "Ada", "ada", "hash", "2026-09-18T00:00:00+00:00", None),
        )

    check = database.connect()
    try:
        assert check.execute("SELECT username FROM users").fetchone()[0] == "Ada"
    finally:
        check.close()

    assert transaction_connection is not None
    with pytest.raises(sqlite3.ProgrammingError):
        transaction_connection.execute("SELECT 1")


def test_transaction_rolls_back_and_closes_connection(database: Database) -> None:
    """Fail if an exception leaves a partial write or an open connection behind."""
    database.migrate()
    transaction_connection: sqlite3.Connection | None = None

    with pytest.raises(RuntimeError, match="abort"):
        with database.transaction() as current_connection:
            transaction_connection = current_connection
            current_connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
                ("u1", "Ada", "ada", "hash", "2026-09-18T00:00:00+00:00", None),
            )
            raise RuntimeError("abort")

    check = database.connect()
    try:
        assert check.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    finally:
        check.close()

    assert transaction_connection is not None
    with pytest.raises(sqlite3.ProgrammingError):
        transaction_connection.execute("SELECT 1")


@pytest.mark.parametrize(
    "error",
    [AppError("example", "Expected error", 422), PathPolicyError("invalid_source")],
)
def test_transaction_preserves_application_exceptions(
    database: Database, error: Exception
) -> None:
    database.migrate()
    with pytest.raises(type(error)) as caught:
        with database.transaction():
            raise error
    assert caught.value is error
