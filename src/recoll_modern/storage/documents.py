"""Persist content identities and their root-relative paths."""

from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection, Row

from recoll_modern.indexing.discovery import ObservedFile
from recoll_modern.storage.database import Database


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    content_hash: str
    byte_size: int
    state: str
    canonical_path: str | None
    paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservationResult:
    documents: tuple[DocumentRecord, ...]


class DocumentRepository:
    """Maintain one document per digest and one canonical live path."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, content_hash: str) -> DocumentRecord | None:
        with self._database.connect() as connection:
            return _record(connection, content_hash)

    def observe_files(
        self,
        files: list[ObservedFile],
        *,
        reconcile_paths: tuple[str, ...] = (),
    ) -> ObservationResult:
        """Observe files atomically; only explicit reconciliation retires unseen paths."""
        now = datetime.now(UTC).isoformat()
        seen = {file.relative_path for file in files}
        affected: set[str] = set()
        with self._database.transaction() as connection:
            for file in files:
                prior = connection.execute(
                    "SELECT document_hash FROM document_paths WHERE relative_path = ?",
                    (file.relative_path,),
                ).fetchone()
                if prior is not None:
                    affected.add(str(prior[0]))
                affected.add(file.content_hash)
                connection.execute(
                    "INSERT INTO documents "
                    "(content_hash, byte_size, state, created_at, updated_at) "
                    "VALUES (?, ?, 'present', ?, ?) "
                    "ON CONFLICT(content_hash) DO UPDATE SET "
                    "byte_size = excluded.byte_size, state = 'present', "
                    "updated_at = excluded.updated_at",
                    (file.content_hash, file.byte_size, now, now),
                )
                connection.execute(
                    "INSERT INTO document_paths "
                    "(document_hash, relative_path, is_canonical, last_seen_at, missing_at) "
                    "VALUES (?, ?, 0, ?, NULL) "
                    "ON CONFLICT(relative_path) DO UPDATE SET "
                    "document_hash = excluded.document_hash, is_canonical = 0, "
                    "last_seen_at = excluded.last_seen_at, missing_at = NULL",
                    (file.content_hash, file.relative_path, now),
                )
            for path in set(reconcile_paths) - seen:
                row = connection.execute(
                    "SELECT document_hash FROM document_paths WHERE relative_path = ?",
                    (path,),
                ).fetchone()
                if row is not None:
                    affected.add(str(row[0]))
                    connection.execute(
                        "UPDATE document_paths SET missing_at = ? WHERE relative_path = ?",
                        (now, path),
                    )
            # Clear first: a partial unique index permits only one canonical path.
            for content_hash in affected:
                connection.execute(
                    "UPDATE document_paths SET is_canonical = 0 WHERE document_hash = ?",
                    (content_hash,),
                )
            for content_hash in affected:
                live = connection.execute(
                    "SELECT relative_path FROM document_paths "
                    "WHERE document_hash = ? AND missing_at IS NULL ORDER BY relative_path LIMIT 1",
                    (content_hash,),
                ).fetchone()
                if live is None:
                    connection.execute(
                        "UPDATE documents SET state = 'missing', updated_at = ? "
                        "WHERE content_hash = ?",
                        (now, content_hash),
                    )
                else:
                    connection.execute(
                        "UPDATE documents SET state = 'present', updated_at = ? "
                        "WHERE content_hash = ?",
                        (now, content_hash),
                    )
                    connection.execute(
                        "UPDATE document_paths SET is_canonical = 1 WHERE relative_path = ?",
                        (str(live[0]),),
                    )
            records = tuple(
                record
                for content_hash in sorted(affected)
                if (record := _record(connection, content_hash)) is not None
            )
        return ObservationResult(records)


def _record(connection: Connection, content_hash: str) -> DocumentRecord | None:
    row: Row | None = connection.execute(
        "SELECT content_hash, byte_size, state FROM documents WHERE content_hash = ?",
        (content_hash,),
    ).fetchone()
    if row is None:
        return None
    paths = tuple(
        str(path["relative_path"])
        for path in connection.execute(
            "SELECT relative_path FROM document_paths "
            "WHERE document_hash = ? AND missing_at IS NULL ORDER BY relative_path",
            (content_hash,),
        )
    )
    return DocumentRecord(
        str(row["content_hash"]),
        int(row["byte_size"]),
        str(row["state"]),
        paths[0] if paths else None,
        paths,
    )
