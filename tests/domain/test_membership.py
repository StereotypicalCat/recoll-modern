from pathlib import Path

import pytest

from recoll_modern.domain.membership import MembershipService
from recoll_modern.domain.models import CollectionCreate
from recoll_modern.indexing.discovery import DiscoveryReport, FileError, Source
from recoll_modern.indexing.paths import PathPolicy
from recoll_modern.storage.collections import SQLiteCollectionRepository
from recoll_modern.storage.database import Database
from recoll_modern.storage.documents import DocumentRepository
from recoll_modern.storage.membership import MembershipRepository


def test_plan_add_rejects_exclusion_outside_rule(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    collection_id = SQLiteCollectionRepository(database).create(CollectionCreate("Books")).id
    service = MembershipService(
        PathPolicy(root), DocumentRepository(database), MembershipRepository(database)
    )
    with pytest.raises(ValueError, match="descendant"):
        service.plan_add(collection_id, [Source.directory(
            "books", mode="persistent", excluded_directories=("other",)
        )])


def test_plan_add_direct_file_keeps_existing_rule_membership(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.txt").write_text("a")
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    collection_id = SQLiteCollectionRepository(database).create(CollectionCreate("Books")).id
    membership = MembershipRepository(database)
    service = MembershipService(PathPolicy(root), DocumentRepository(database), membership)
    result = service.plan_add(collection_id, [Source.file("a.txt")])
    content_hash = result.discovery.files[0].content_hash
    assert membership.has_direct(collection_id, content_hash)
    assert membership.effective_collections(content_hash) == [collection_id]


def test_earlier_duplicate_reindexes_old_and_new_canonical_paths(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "b.txt").write_text("same")
    (root / "a.txt").write_text("same")
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    collection_id = SQLiteCollectionRepository(database).create(CollectionCreate("Books")).id
    service = MembershipService(
        PathPolicy(root), DocumentRepository(database), MembershipRepository(database)
    )
    service.plan_add(collection_id, [Source.file("b.txt")])
    result = service.plan_add(collection_id, [Source.file("a.txt")])
    assert result.changed_paths == ("a.txt", "b.txt")


def test_resubmitted_rule_preserves_member_on_discovery_error(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    books = root / "books"
    books.mkdir(parents=True)
    (books / "a.txt").write_text("same")
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    collection_id = SQLiteCollectionRepository(database).create(CollectionCreate("Books")).id
    membership = MembershipRepository(database)
    service = MembershipService(PathPolicy(root), DocumentRepository(database), membership)
    source = Source.directory("books", mode="persistent")
    first = service.plan_add(collection_id, [source])
    content_hash = first.discovery.files[0].content_hash
    result = service.apply_discovered(
        collection_id,
        [(source, DiscoveryReport((), (FileError("books/a.txt", "file_unreadable"),)))],
    )
    assert result.discovery.errors[0].code == "file_unreadable"
    assert membership.rule_documents(membership.list_rules()[0].id) == {content_hash}
