"""Single asynchronous worker around blocking durable job handlers."""

import asyncio
from collections.abc import Callable, Mapping

from recoll_modern.domain.jobs import Job, JobState
from recoll_modern.storage.jobs import JobRepository


class JobWorker:
    def __init__(
        self, jobs: JobRepository, handlers: Mapping[str, Callable[[Job], None]]
    ) -> None:
        self._jobs = jobs
        self._handlers = handlers
        self._wake = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._jobs.recover_running()
        self._stopping = False
        self._task = asyncio.create_task(self._run())
        self._wake.set()

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            await self._task
            self._task = None

    def notify(self) -> None:
        self._wake.set()

    async def run_once(self) -> bool:
        job = await asyncio.to_thread(self._jobs.claim_next)
        if job is None:
            return False
        handler = self._handlers.get(job.kind)
        if handler is None:
            await asyncio.to_thread(
                self._jobs.fail, job.id, "invalid_job_request", "Job kind is not supported"
            )
            return True
        try:
            await asyncio.to_thread(handler, job)
        except Exception:
            await asyncio.to_thread(
                self._jobs.fail, job.id, "job_failed", "Job failed during processing"
            )
        else:
            current = await asyncio.to_thread(self._jobs.get, job.id)
            if current is not None and current.state is JobState.RUNNING:
                await asyncio.to_thread(self._jobs.complete, job.id)
        return True

    async def _run(self) -> None:
        while not self._stopping:
            if await self.run_once():
                continue
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            except TimeoutError:
                pass
