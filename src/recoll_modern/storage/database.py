"""SQLite connection, transaction, and migration support."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path


class Database:
    """Provide consistently configured SQLite connections for one database file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        """Open a connection with the service's SQLite safety policy."""
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        """Yield an immediate transaction that commits or rolls back atomically."""
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def migrate(self) -> None:
        """Apply every pending migration as one immediate transaction."""
        migrations = sorted(_migration_scripts(), key=lambda migration: migration[0])
        _ensure_unique_versions(migrations)

        connection = self.connect()
        try:
            applied_versions = _applied_versions(connection)
            pending = [
                migration for migration in migrations if migration[0] not in applied_versions
            ]
            if not pending:
                return

            applied_at = datetime.now(UTC).isoformat()
            script = ["BEGIN IMMEDIATE;"]
            for version, migration_sql in pending:
                script.append(migration_sql)
                script.append(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    f"VALUES ({version}, '{applied_at}');"
                )
            script.append("COMMIT;")
            connection.executescript("\n".join(script))
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _migration_scripts() -> list[tuple[int, str]]:
    """Read numbered SQL migrations bundled with the storage package."""
    migrations: list[tuple[int, str]] = []
    for resource in files("recoll_modern.storage.migrations").iterdir():
        if not resource.name.endswith(".sql"):
            continue
        version_text, separator, _ = resource.name.partition("_")
        if not separator or not version_text.isdigit():
            raise ValueError(f"invalid migration filename: {resource.name}")
        migrations.append((int(version_text), resource.read_text(encoding="utf-8")))
    return migrations


def _ensure_unique_versions(migrations: list[tuple[int, str]]) -> None:
    """Reject ambiguous migration histories before modifying the database."""
    versions = [version for version, _ in migrations]
    for version in versions:
        if versions.count(version) > 1:
            raise ValueError(f"duplicate migration version: {version}")


def _applied_versions(connection: sqlite3.Connection) -> set[int]:
    """Return applied versions, treating a new database as having none."""
    try:
        return {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
    except sqlite3.OperationalError as error:
        if "no such table: schema_migrations" not in str(error):
            raise
        return set()
