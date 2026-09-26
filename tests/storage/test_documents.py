import hashlib
from pathlib import Path

from recoll_modern.indexing.discovery import ObservedFile
from recoll_modern.storage.database import Database
from recoll_modern.storage.documents import DocumentRepository


def _repository(tmp_path: Path) -> DocumentRepository:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    return DocumentRepository(database)


def _file(path: str, data: bytes) -> ObservedFile:
    return ObservedFile(path, hashlib.sha256(data).hexdigest(), len(data))


def test_same_bytes_have_one_document_and_one_canonical_path(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    result = repository.observe_files([_file("z.txt", b"same"), _file("a.txt", b"same")])
    assert len(result.documents) == 1
    assert result.documents[0].canonical_path == "a.txt"
    assert result.documents[0].paths == ("a.txt", "z.txt")


def test_same_name_with_changed_content_creates_second_document(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    old = repository.observe_files([_file("a.txt", b"old")]).documents[0]
    result = repository.observe_files([_file("a.txt", b"new")])
    assert len(result.documents) == 2
    assert repository.get(old.content_hash).state == "missing"  # type: ignore[union-attr]


def test_reconcile_promotes_remaining_duplicate_path(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    file_a = _file("a.txt", b"same")
    file_b = _file("b.txt", b"same")
    repository.observe_files([file_a, file_b])
    result = repository.observe_files([file_b], reconcile_paths=("a.txt", "b.txt"))
    assert result.documents[0].canonical_path == "b.txt"


def test_incremental_observation_does_not_mark_unseen_paths_missing(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.observe_files([_file("a.txt", b"a")])
    result = repository.observe_files([_file("b.txt", b"b")])
    assert len(result.documents) == 1
    assert repository.get(_file("a.txt", b"a").content_hash).state == "present"  # type: ignore[union-attr]


def test_path_moves_to_existing_document_without_canonical_conflict(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.observe_files([_file("a.txt", b"old"), _file("b.txt", b"new")])
    result = repository.observe_files([_file("a.txt", b"new")])
    assert repository.get(_file("a.txt", b"old").content_hash).state == "missing"  # type: ignore[union-attr]
    present = next(document for document in result.documents if document.state == "present")
    assert present.canonical_path == "a.txt"
