"""SQLite provenance for direct and directory-rule membership."""

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from recoll_modern.storage.database import Database


@dataclass(frozen=True, slots=True)
class DirectoryRule:
    id: str
    collection_id: str
    relative_path: str
    excluded_directories: tuple[str, ...]


class MembershipRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create_rule(
        self, collection_id: str, relative_path: str, excluded_directories: tuple[str, ...]
    ) -> DirectoryRule:
        now = datetime.now(UTC).isoformat()
        while True:
            rule_id = f"r{secrets.token_hex(5)}"
            try:
                with self._database.transaction() as connection:
                    connection.execute(
                        "INSERT INTO directory_rules "
                        "(id, collection_id, relative_path, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (rule_id, collection_id, relative_path, now, now),
                    )
                    connection.executemany(
                        "INSERT INTO directory_rule_exclusions(rule_id, relative_path) "
                        "VALUES (?, ?)",
                        [(rule_id, path) for path in excluded_directories],
                    )
            except sqlite3.IntegrityError as error:
                if "directory_rules.id" in str(error):
                    continue
                raise
            return DirectoryRule(rule_id, collection_id, relative_path, excluded_directories)

    def get_rule(self, rule_id: str) -> DirectoryRule | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, collection_id, relative_path FROM directory_rules WHERE id = ?",
                (rule_id,),
            ).fetchone()
            if row is None:
                return None
            exclusions = tuple(
                str(item[0])
                for item in connection.execute(
                    "SELECT relative_path FROM directory_rule_exclusions "
                    "WHERE rule_id = ? ORDER BY relative_path",
                    (rule_id,),
                )
            )
            return DirectoryRule(str(row[0]), str(row[1]), str(row[2]), exclusions)

    def patch_rule(self, rule_id: str, excluded_directories: tuple[str, ...]) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "DELETE FROM directory_rule_exclusions WHERE rule_id = ?", (rule_id,)
            )
            connection.executemany(
                "INSERT INTO directory_rule_exclusions(rule_id, relative_path) VALUES (?, ?)",
                [(rule_id, path) for path in excluded_directories],
            )
            connection.execute(
                "UPDATE directory_rules SET updated_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), rule_id),
            )

    def rule_documents(self, rule_id: str) -> set[str]:
        with self._database.connect() as connection:
            return {
                str(row[0])
                for row in connection.execute(
                    "SELECT document_hash FROM rule_memberships WHERE rule_id = ?", (rule_id,)
                )
            }

    def replace_rule_members(self, rule_id: str, hashes: list[str]) -> list[str]:
        with self._database.transaction() as connection:
            old = {
                str(row[0])
                for row in connection.execute(
                    "SELECT document_hash FROM rule_memberships WHERE rule_id = ?", (rule_id,)
                )
            }
            affected = old | set(hashes)
            before = _effective_for_hashes(connection, affected)
            connection.execute("DELETE FROM rule_memberships WHERE rule_id = ?", (rule_id,))
            now = datetime.now(UTC).isoformat()
            connection.executemany(
                "INSERT INTO rule_memberships(rule_id, document_hash, last_seen_at) "
                "VALUES (?, ?, ?)",
                [(rule_id, content_hash, now) for content_hash in set(hashes)],
            )
            return _changed_paths(connection, affected, before)

    def delete_rule(self, rule_id: str) -> list[str]:
        with self._database.transaction() as connection:
            hashes = {
                str(row[0])
                for row in connection.execute(
                    "SELECT document_hash FROM rule_memberships WHERE rule_id = ?", (rule_id,)
                )
            }
            before = _effective_for_hashes(connection, hashes)
            connection.execute("DELETE FROM directory_rules WHERE id = ?", (rule_id,))
            return _changed_paths(connection, hashes, before)

    def add_direct(self, collection_id: str, content_hash: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._database.transaction() as connection:
            connection.execute(
                "DELETE FROM membership_exclusions "
                "WHERE collection_id = ? AND document_hash = ?",
                (collection_id, content_hash),
            )
            connection.execute(
                "INSERT OR IGNORE INTO direct_memberships "
                "(collection_id, document_hash, created_at) VALUES (?, ?, ?)",
                (collection_id, content_hash, now),
            )

    def has_direct(self, collection_id: str, content_hash: str) -> bool:
        with self._database.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM direct_memberships WHERE collection_id = ? AND document_hash = ?",
                (collection_id, content_hash),
            ).fetchone() is not None

    def exclude_document(self, collection_id: str, content_hash: str) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO membership_exclusions "
                "(collection_id, document_hash, created_at) VALUES (?, ?, ?)",
                (collection_id, content_hash, datetime.now(UTC).isoformat()),
            )

    def remove_document(self, collection_id: str, content_hash: str) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "DELETE FROM direct_memberships "
                "WHERE collection_id = ? AND document_hash = ?",
                (collection_id, content_hash),
            )
            connection.execute(
                "INSERT OR IGNORE INTO membership_exclusions "
                "(collection_id, document_hash, created_at) VALUES (?, ?, ?)",
                (collection_id, content_hash, datetime.now(UTC).isoformat()),
            )

    def effective_collections(self, content_hash: str) -> list[str]:
        with self._database.connect() as connection:
            return _effective(connection, content_hash)


def _effective(connection: sqlite3.Connection, content_hash: str) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT collection_id FROM direct_memberships WHERE document_hash = ? "
            "UNION SELECT r.collection_id FROM rule_memberships AS rm "
            "JOIN directory_rules AS r ON r.id = rm.rule_id "
            "WHERE rm.document_hash = ? "
            "AND NOT EXISTS (SELECT 1 FROM membership_exclusions AS e "
            "WHERE e.collection_id = r.collection_id AND e.document_hash = rm.document_hash) "
            "ORDER BY collection_id",
            (content_hash, content_hash),
        )
    ]


def _effective_for_hashes(
    connection: sqlite3.Connection, hashes: set[str]
) -> dict[str, list[str]]:
    return {content_hash: _effective(connection, content_hash) for content_hash in hashes}


def _changed_paths(
    connection: sqlite3.Connection, hashes: set[str], before: dict[str, list[str]]
) -> list[str]:
    paths: list[str] = []
    for content_hash in hashes:
        if before[content_hash] == _effective(connection, content_hash):
            continue
        row = connection.execute(
            "SELECT relative_path FROM document_paths "
            "WHERE document_hash = ? AND is_canonical = 1 AND missing_at IS NULL",
            (content_hash,),
        ).fetchone()
        if row is not None:
            paths.append(str(row[0]))
    return sorted(paths)
