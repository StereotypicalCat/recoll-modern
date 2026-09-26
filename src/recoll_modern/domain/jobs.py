"""Durable indexing-job state shared by storage and workers."""

from dataclasses import dataclass
from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    kind: str
    state: JobState
    request: dict[str, object]
    fail_on_file_error: bool
    progress: int
    total: int
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class JobFileError:
    relative_path: str
    code: str
    message: str
