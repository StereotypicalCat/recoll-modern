"""Durable membership job application after complete source discovery."""

from pathlib import Path
from typing import Protocol

from recoll_modern.domain.jobs import Job, JobFileError
from recoll_modern.domain.membership import MembershipService
from recoll_modern.indexing.discovery import Source, discover_sources
from recoll_modern.indexing.map_export import MembershipMapRows, export_membership_map
from recoll_modern.indexing.paths import PathPolicy
from recoll_modern.storage.documents import DocumentRepository
from recoll_modern.storage.jobs import JobRepository
from recoll_modern.storage.membership import MembershipRepository


class ForceIndexer(Protocol):
    def force_reindex(self, paths: tuple[str, ...]) -> None: ...


class MembershipJobHandler:
    def __init__(
        self,
        policy: PathPolicy,
        documents: DocumentRepository,
        memberships: MembershipRepository,
        jobs: JobRepository,
        membership_map_path: Path,
        indexer: ForceIndexer,
    ) -> None:
        self._policy = policy
        self._service = MembershipService(policy, documents, memberships)
        self._map_rows = MembershipMapRows(memberships, policy.root)
        self._map_path = membership_map_path
        self._indexer = indexer
        self._jobs = jobs

    def handle(self, job: Job) -> None:
        try:
            collection_id = job.request["collection_id"]
            source_values = job.request["sources"]
            if not isinstance(collection_id, str) or not isinstance(source_values, list):
                raise ValueError
            sources = [_parse_source(value) for value in source_values]
        except (KeyError, ValueError, TypeError):
            self._jobs.fail(job.id, "invalid_job_request", "Job request is invalid")
            return
        discovered = [(source, discover_sources(self._policy, [source])) for source in sources]
        errors = [error for _, report in discovered for error in report.errors]
        for error in errors:
            self._jobs.add_file_error(
                job.id, JobFileError(error.relative_path, error.code, "File could not be read")
            )
        total = sum(len(report.files) + len(report.errors) for _, report in discovered)
        self._jobs.progress(job.id, 0, total)
        if errors and job.fail_on_file_error:
            self._jobs.fail(job.id, "file_error", "One or more files could not be read")
            return
        try:
            result = self._service.apply_discovered(collection_id, discovered)
        except ValueError:
            self._jobs.fail(job.id, "invalid_job_request", "Job request is invalid")
            return
        export_membership_map(self._map_rows, self._map_path)
        changed_paths = tuple(
            str(self._policy.root / path) for path in sorted(set(result.changed_paths))
        )
        if changed_paths:
            self._indexer.force_reindex(changed_paths)
        self._jobs.progress(job.id, total, total)
        self._jobs.complete(job.id, with_errors=bool(errors))


def _parse_source(value: object) -> Source:
    if not isinstance(value, dict):
        raise ValueError
    kind = value.get("type")
    path = value.get("path")
    if not isinstance(path, str):
        raise ValueError
    if kind == "file":
        return Source.file(path)
    if kind == "directory":
        mode = value.get("mode")
        exclusions = value.get("excluded_directories", [])
        if mode not in ("snapshot", "persistent") or not isinstance(exclusions, list):
            raise ValueError
        if not all(isinstance(item, str) for item in exclusions):
            raise ValueError
        return Source.directory(path, mode, tuple(exclusions))
    raise ValueError
