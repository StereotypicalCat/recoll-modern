from pathlib import Path

import pytest

from recoll_modern.domain.models import CollectionCreate
from recoll_modern.indexing.discovery import DiscoveryReport, FileError
from recoll_modern.indexing.paths import PathPolicy
from recoll_modern.indexing.reconcile import reconcile_rule
from recoll_modern.storage.collections import SQLiteCollectionRepository
from recoll_modern.storage.database import Database
from recoll_modern.storage.documents import DocumentRepository
from recoll_modern.storage.membership import MembershipRepository


def test_rule_reconciliation_removes_departed_file_without_touching_direct(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    books = root / "books"
    books.mkdir()
    (books / "keep.txt").write_text("keep")
    (books / "gone.txt").write_text("gone")
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    collection_id = SQLiteCollectionRepository(database).create(CollectionCreate("Books")).id
    membership = MembershipRepository(database)
    documents = DocumentRepository(database)
    rule = membership.create_rule(collection_id, "books", ())
    first = reconcile_rule(rule.id, PathPolicy(root), documents, membership)
    departed = next(
        file for file in first.discovery.files if file.relative_path == "books/gone.txt"
    )
    membership.add_direct(collection_id, departed.content_hash)
    (books / "gone.txt").unlink()
    second = reconcile_rule(rule.id, PathPolicy(root), documents, membership)
    assert departed.content_hash not in membership.rule_documents(rule.id)
    assert membership.has_direct(collection_id, departed.content_hash)
    assert second.discovery.errors == ()


def test_excluded_file_is_not_marked_missing(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    skipped = root / "books" / "skip"
    skipped.mkdir(parents=True)
    (skipped / "a.txt").write_text("a")
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    collection_id = SQLiteCollectionRepository(database).create(CollectionCreate("Books")).id
    membership = MembershipRepository(database)
    documents = DocumentRepository(database)
    rule = membership.create_rule(collection_id, "books", ())
    first = reconcile_rule(rule.id, PathPolicy(root), documents, membership)
    content_hash = first.discovery.files[0].content_hash
    membership.patch_rule(rule.id, ("books/skip",))
    reconcile_rule(rule.id, PathPolicy(root), documents, membership)
    record = documents.get(content_hash)
    assert record is not None and record.state == "present"
    assert membership.rule_documents(rule.id) == set()


def test_unreadable_file_retains_rule_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "docs"
    books = root / "books"
    books.mkdir(parents=True)
    (books / "a.txt").write_text("a")
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    collection_id = SQLiteCollectionRepository(database).create(CollectionCreate("Books")).id
    membership = MembershipRepository(database)
    documents = DocumentRepository(database)
    rule = membership.create_rule(collection_id, "books", ())
    first = reconcile_rule(rule.id, PathPolicy(root), documents, membership)
    content_hash = first.discovery.files[0].content_hash
    monkeypatch.setattr(
        "recoll_modern.indexing.reconcile.discover_sources",
        lambda _policy, _sources: DiscoveryReport(
            (), (FileError("books/a.txt", "file_unreadable"),)
        ),
    )
    second = reconcile_rule(rule.id, PathPolicy(root), documents, membership)
    assert second.discovery.errors[0].code == "file_unreadable"
    assert membership.rule_documents(rule.id) == {content_hash}
    assert documents.get(content_hash).state == "present"  # type: ignore[union-attr]
