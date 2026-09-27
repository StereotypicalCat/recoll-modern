from pathlib import Path

import pytest

from recoll_modern.domain.jobs import JobFileError, JobState
from recoll_modern.storage.database import Database
from recoll_modern.storage.jobs import JobRepository


def _repo(tmp_path: Path) -> JobRepository:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    return JobRepository(database)


def _membership_request(sources: object = None) -> dict[str, object]:
    return {"version": 1, "collection_id": "c1", "sources": [] if sources is None else sources}


def test_claim_next_is_durable_and_oldest_first(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    first = repo.enqueue("membership_add", _membership_request(), False)
    second = repo.enqueue("membership_add", _membership_request(), False)
    assert repo.claim_next().id == first.id  # type: ignore[union-attr]
    assert repo.claim_next().id == second.id  # type: ignore[union-attr]
    assert repo.claim_next() is None


def test_recover_running_requeues_valid_jobs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = repo.enqueue("membership_add", _membership_request(), False)
    repo.claim_next()
    repo.recover_running()
    assert repo.get(job.id).state == JobState.QUEUED  # type: ignore[union-attr]


def test_recover_running_fails_malformed_request(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    repo = JobRepository(database)
    job = repo.enqueue("membership_add", _membership_request(), False)
    repo.claim_next()
    with database.transaction() as connection:
        connection.execute("UPDATE jobs SET request_json = ? WHERE id = ?", ("{", job.id))
    repo.recover_running()
    recovered = repo.get(job.id)
    assert recovered is not None and recovered.state == JobState.FAILED
    assert recovered.error_code == "invalid_job_request"


def test_recover_running_fails_invalid_source_shape(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    repo = JobRepository(database)
    job = repo.enqueue("membership_add", _membership_request("not a list"), False)
    repo.claim_next()
    repo.recover_running()
    assert repo.get(job.id).state == JobState.FAILED  # type: ignore[union-attr]


def test_recover_running_clears_errors_from_interrupted_attempt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = repo.enqueue("membership_add", _membership_request(), False)
    repo.claim_next()
    repo.add_file_error(job.id, JobFileError("gone.txt", "file_vanished", "File vanished"))
    repo.recover_running()
    assert repo.file_errors(job.id) == []


def test_failed_job_can_be_retried(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = repo.enqueue("membership_add", _membership_request(), False)
    repo.claim_next()
    repo.fail(job.id, "engine_unavailable", "Engine unavailable")
    repo.retry(job.id)
    assert repo.get(job.id).state == JobState.QUEUED  # type: ignore[union-attr]


@pytest.mark.parametrize("kind,payload", [
    ("rule_delete", {"version": 1}),
    ("rule_patch", {"version": 1, "rule_id": "r1", "excluded_directories": "bad"}),
    ("reindex", {"version": 1, "paths": "bad", "collections": []}),
    ("collection_cleanup", {"version": 2, "paths": []}),
    ("unknown", {"version": 1}),
])
def test_recovery_rejects_invalid_kind_payload(
    tmp_path: Path, kind: str, payload: dict[str, object]
) -> None:
    repo = _repo(tmp_path)
    job = repo.enqueue(kind, payload, False)
    repo.claim_next()
    repo.recover_running()
    recovered = repo.get(job.id)
    assert recovered is not None and recovered.state == JobState.FAILED
    assert recovered.error_code == "invalid_job_request"
