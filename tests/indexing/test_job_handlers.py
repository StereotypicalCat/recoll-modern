from pathlib import Path

from recoll_modern.domain.jobs import JobState
from recoll_modern.domain.models import CollectionCreate
from recoll_modern.indexing.handlers import MembershipJobHandler
from recoll_modern.indexing.paths import PathPolicy
from recoll_modern.storage.collections import SQLiteCollectionRepository
from recoll_modern.storage.database import Database
from recoll_modern.storage.documents import DocumentRepository
from recoll_modern.storage.jobs import JobRepository
from recoll_modern.storage.membership import MembershipRepository


def _setup(
    tmp_path: Path,
) -> tuple[Path, JobRepository, MembershipRepository, MembershipJobHandler, str]:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "good.txt").write_text("good")
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    collection_id = SQLiteCollectionRepository(database).create(CollectionCreate("Books")).id
    jobs = JobRepository(database)
    membership = MembershipRepository(database)
    handler = MembershipJobHandler(
        PathPolicy(root), DocumentRepository(database), membership, jobs
    )
    return root, jobs, membership, handler, collection_id


def _request(collection_id: str) -> dict[str, object]:
    return {"collection_id": collection_id, "sources": [
        {"type": "file", "path": "good.txt"},
        {"type": "file", "path": "gone.txt"},
    ]}


def test_strict_discovery_error_applies_nothing(tmp_path: Path) -> None:
    _, jobs, membership, handler, collection_id = _setup(tmp_path)
    job = jobs.enqueue("membership_add", _request(collection_id), True)
    claimed = jobs.claim_next()
    assert claimed is not None
    handler.handle(claimed)
    assert jobs.get(job.id).state == JobState.FAILED  # type: ignore[union-attr]
    assert membership.direct_documents(collection_id) == set()


def test_best_effort_applies_valid_files_and_records_errors(tmp_path: Path) -> None:
    _, jobs, membership, handler, collection_id = _setup(tmp_path)
    job = jobs.enqueue("membership_add", _request(collection_id), False)
    claimed = jobs.claim_next()
    assert claimed is not None
    handler.handle(claimed)
    assert jobs.get(job.id).state == JobState.COMPLETED_WITH_ERRORS  # type: ignore[union-attr]
    assert len(membership.direct_documents(collection_id)) == 1
    assert [(error.relative_path, error.code) for error in jobs.file_errors(job.id)] == [
        ("gone.txt", "file_vanished")
    ]
