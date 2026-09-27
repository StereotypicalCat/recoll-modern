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

    class NoopIndexer:
        def force_reindex(self, paths: tuple[str, ...]) -> None:
            pass

    handler = MembershipJobHandler(
        PathPolicy(root), DocumentRepository(database), membership, jobs,
        tmp_path / "membership.map", NoopIndexer(),
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


def test_handler_exports_map_before_forced_reindex(tmp_path: Path) -> None:
    root, jobs, membership, _, collection_id = _setup(tmp_path)
    map_path = tmp_path / "membership.map"
    calls: list[tuple[str, ...]] = []

    class FakeIndexer:
        def force_reindex(self, paths: tuple[str, ...]) -> None:
            assert map_path.read_bytes().startswith(b"RCM1")
            assert collection_id.encode() in map_path.read_bytes()
            calls.append(paths)

    database = Database(tmp_path / "state.sqlite3")
    handler = MembershipJobHandler(
        PathPolicy(root), DocumentRepository(database), membership, jobs,
        map_path, FakeIndexer(),
    )
    job = jobs.enqueue("membership_add", {
        "collection_id": collection_id,
        "sources": [{"type": "file", "path": "good.txt"}],
    }, False)
    claimed = jobs.claim_next()
    assert claimed is not None
    handler.handle(claimed)
    assert calls == [(str(root / "good.txt"),)]
    assert jobs.get(job.id).state == JobState.COMPLETED  # type: ignore[union-attr]


def test_persistent_source_replays_after_index_failure(tmp_path: Path) -> None:
    root, jobs, membership, _, collection_id = _setup(tmp_path)
    (root / "books").mkdir()
    (root / "books" / "a.txt").write_text("book")
    forced: list[tuple[str, ...]] = []

    class FlakyIndexer:
        def force_reindex(self, paths: tuple[str, ...]) -> None:
            forced.append(paths)
            if len(forced) == 1:
                raise RuntimeError("simulated index failure")

    handler = MembershipJobHandler(
        PathPolicy(root), DocumentRepository(Database(tmp_path / "state.sqlite3")),
        membership, jobs, tmp_path / "membership.map", FlakyIndexer(),
    )
    job = jobs.enqueue("membership_add", {
        "version": 1, "collection_id": collection_id,
        "sources": [{"type": "directory", "path": "books", "mode": "persistent",
                     "excluded_directories": []}],
    }, False)
    claimed = jobs.claim_next()
    assert claimed is not None
    try:
        handler.handle(claimed)
    except RuntimeError:
        pass
    assert len(membership.list_rules()) == 1
    handler.handle(claimed)
    assert jobs.get(job.id).state == JobState.COMPLETED  # type: ignore[union-attr]
    assert forced == [(str(root / "books" / "a.txt"),)] * 2
