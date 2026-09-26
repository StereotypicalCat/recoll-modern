import asyncio
from pathlib import Path

import pytest

from recoll_modern.domain.jobs import Job, JobState
from recoll_modern.indexing.worker import JobWorker
from recoll_modern.storage.database import Database
from recoll_modern.storage.jobs import JobRepository


@pytest.mark.asyncio
async def test_worker_runs_one_job_and_records_completion(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    jobs = JobRepository(database)
    job = jobs.enqueue("test", {}, False)
    handled: list[str] = []

    def handle(claimed: Job) -> None:
        handled.append(claimed.id)

    worker = JobWorker(jobs, {"test": handle})
    assert await worker.run_once()
    assert handled == [job.id]
    assert jobs.get(job.id).state == JobState.COMPLETED  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_worker_failure_is_durable(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    jobs = JobRepository(database)
    job = jobs.enqueue("test", {}, False)

    def fail(_claimed: Job) -> None:
        raise RuntimeError("private filesystem path")

    worker = JobWorker(jobs, {"test": fail})
    assert await worker.run_once()
    failed = jobs.get(job.id)
    assert failed is not None and failed.state == JobState.FAILED
    assert "private" not in (failed.error_message or "")


@pytest.mark.asyncio
async def test_worker_start_recovers_and_drains_queue(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    jobs = JobRepository(database)
    job = jobs.enqueue("test", {}, False)
    jobs.claim_next()
    handled: list[str] = []
    worker = JobWorker(jobs, {"test": lambda claimed: handled.append(claimed.id)})
    worker.start()
    for _ in range(100):
        current = jobs.get(job.id)
        if current is not None and current.state == JobState.COMPLETED:
            break
        await asyncio.sleep(0.01)
    await worker.stop()
    assert handled == [job.id]
    assert jobs.get(job.id).state == JobState.COMPLETED  # type: ignore[union-attr]
