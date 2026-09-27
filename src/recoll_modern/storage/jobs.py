"""Atomic SQLite transitions for indexing jobs."""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from sqlite3 import Connection

from recoll_modern.domain.jobs import Job, JobFileError, JobState
from recoll_modern.storage.database import Database


class JobRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def enqueue(
        self, kind: str, request: Mapping[str, object], fail_on_file_error: bool
    ) -> Job:
        with self._database.transaction() as connection:
            return self.enqueue_in_transaction(connection, kind, request, fail_on_file_error)

    def enqueue_in_transaction(
        self, connection: Connection, kind: str, request: Mapping[str, object],
        fail_on_file_error: bool,
    ) -> Job:
        """Write a job in a caller-owned transaction when state and work must be atomic."""
        serialized = json.dumps(dict(request), sort_keys=True)
        now = datetime.now(UTC).isoformat()
        while True:
            job_id = f"j{secrets.token_hex(16)}"
            try:
                connection.execute(
                    "INSERT INTO jobs "
                    "(id, kind, state, request_json, fail_on_file_error, created_at) "
                    "VALUES (?, ?, 'queued', ?, ?, ?)",
                    (job_id, kind, serialized, int(fail_on_file_error), now),
                )
            except sqlite3.IntegrityError as error:
                if "jobs.id" in str(error):
                    continue
                raise
            return Job(
                job_id, kind, JobState.QUEUED, dict(request), fail_on_file_error, 0, 0
            )

    def get(self, job_id: str) -> Job | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return _job_from_row(row) if row is not None else None

    def list_jobs(self, limit: int, offset: int) -> tuple[list[Job], int]:
        with self._database.connect() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [_job_from_row(row) for row in rows], total

    def claim_next(self) -> Job | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE state = 'queued' ORDER BY created_at, rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "UPDATE jobs SET state = 'running', started_at = ?, finished_at = NULL "
                "WHERE id = ? AND state = 'queued'",
                (now, row["id"]),
            )
            updated = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (row["id"],)
            ).fetchone()
            return _job_from_row(updated)

    def progress(self, job_id: str, progress: int, total: int) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET progress = ?, total = ? "
                "WHERE id = ? AND state = 'running'",
                (progress, total, job_id),
            )

    def add_file_error(self, job_id: str, error: JobFileError) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO job_file_errors "
                "(job_id, relative_path, code, message) VALUES (?, ?, ?, ?)",
                (job_id, error.relative_path, error.code, error.message),
            )

    def file_errors(self, job_id: str) -> list[JobFileError]:
        with self._database.connect() as connection:
            return [
                JobFileError(str(row[0]), str(row[1]), str(row[2]))
                for row in connection.execute(
                    "SELECT relative_path, code, message FROM job_file_errors "
                    "WHERE job_id = ? ORDER BY relative_path",
                    (job_id,),
                )
            ]

    def record_reindex_paths(self, job_id: str, paths: tuple[str, ...]) -> tuple[str, ...]:
        """Write paths ahead of a destructive membership mutation for replay."""
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT request_json FROM jobs WHERE id = ? AND state = 'running'", (job_id,)
            ).fetchone()
            if row is None:
                raise ValueError("job is not running")
            request = json.loads(str(row[0]))
            prior = request.get("reindex_paths", [])
            if not isinstance(prior, list) or not all(isinstance(item, str) for item in prior):
                raise ValueError("invalid replay paths")
            combined = tuple(sorted(set(prior) | set(paths)))
            request["reindex_paths"] = list(combined)
            connection.execute(
                "UPDATE jobs SET request_json = ? WHERE id = ?",
                (json.dumps(request, sort_keys=True), job_id),
            )
            return combined

    def complete(self, job_id: str, *, with_errors: bool = False) -> None:
        state = "completed_with_errors" if with_errors else "completed"
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET state = ?, finished_at = ? "
                "WHERE id = ? AND state = 'running'",
                (state, datetime.now(UTC).isoformat(), job_id),
            )

    def fail(self, job_id: str, code: str, message: str) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET state = 'failed', error_code = ?, error_message = ?, "
                "finished_at = ? WHERE id = ? AND state = 'running'",
                (code, message, datetime.now(UTC).isoformat(), job_id),
            )

    def recover_running(self) -> None:
        with self._database.transaction() as connection:
            for row in connection.execute(
                "SELECT id, kind, request_json FROM jobs WHERE state = 'running'"
            ).fetchall():
                if _valid_request(str(row["kind"]), str(row["request_json"])):
                    connection.execute(
                        "DELETE FROM job_file_errors WHERE job_id = ?", (row["id"],)
                    )
                    connection.execute(
                        "UPDATE jobs SET state = 'queued', started_at = NULL, "
                        "progress = 0, total = 0 WHERE id = ?",
                        (row["id"],),
                    )
                else:
                    connection.execute(
                        "UPDATE jobs SET state = 'failed', error_code = 'invalid_job_request', "
                        "error_message = 'Job request is invalid', finished_at = ? WHERE id = ?",
                        (datetime.now(UTC).isoformat(), row["id"]),
                    )

    def retry(self, job_id: str) -> None:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET state = 'queued', error_code = NULL, error_message = NULL, "
                "started_at = NULL, finished_at = NULL, progress = 0, total = 0 "
                "WHERE id = ? AND state IN ('failed', 'completed_with_errors')",
                (job_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("job is not retryable")
            connection.execute("DELETE FROM job_file_errors WHERE job_id = ?", (job_id,))


def _valid_request(kind: str, raw: str) -> bool:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(value, dict):
        return False
    if value.get("version") != 1:
        return False
    replay_paths = value.get("reindex_paths", [])
    if not _string_list(replay_paths):
        return False
    if kind == "membership_add":
        sources = value.get("sources")
        if not isinstance(value.get("collection_id"), str) or not isinstance(sources, list):
            return False
        return all(_valid_source(source) for source in sources)
    if kind == "membership_remove":
        return isinstance(value.get("collection_id"), str) and isinstance(
            value.get("document_hash"), str
        )
    if kind == "rule_patch":
        return isinstance(value.get("rule_id"), str) and _string_list(
            value.get("excluded_directories")
        )
    if kind == "rule_delete":
        return isinstance(value.get("rule_id"), str)
    if kind == "collection_cleanup":
        return _string_list(value.get("paths"))
    if kind == "reindex":
        return _string_list(value.get("paths")) and _string_list(value.get("collections"))
    if kind == "reconcile_rules":
        return True
    return False


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _valid_source(value: object) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        return False
    if value.get("type") == "file":
        return True
    if value.get("type") == "directory":
        return value.get("mode") in ("snapshot", "persistent") and _string_list(
            value.get("excluded_directories", [])
        )
    return False


def _job_from_row(row: sqlite3.Row) -> Job:
    try:
        value = json.loads(str(row["request_json"]))
    except json.JSONDecodeError:
        value = {}
    request = value if isinstance(value, dict) else {}
    return Job(
        id=str(row["id"]), kind=str(row["kind"]), state=JobState(str(row["state"])),
        request=request, fail_on_file_error=bool(row["fail_on_file_error"]),
        progress=int(row["progress"]), total=int(row["total"]),
        error_code=str(row["error_code"]) if row["error_code"] is not None else None,
        error_message=str(row["error_message"]) if row["error_message"] is not None else None,
    )
