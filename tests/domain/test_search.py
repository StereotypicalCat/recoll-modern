"""Search projections use current membership and Unicode text bounds."""

from pathlib import Path

from recoll_modern.domain.models import CollectionCreate
from recoll_modern.domain.search import SearchInput, SearchService
from recoll_modern.engine.fake import FakeEngine, FakeRecord
from recoll_modern.indexing.discovery import ObservedFile
from recoll_modern.indexing.paths import PathPolicy
from recoll_modern.storage.collections import SQLiteCollectionRepository
from recoll_modern.storage.database import Database
from recoll_modern.storage.documents import DocumentRepository
from recoll_modern.storage.membership import MembershipRepository


def test_unicode_limit_and_stale_membership_are_checked_against_sqlite(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "é.txt"
    path.write_text("🦊alpha")
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    collection = SQLiteCollectionRepository(database).create(CollectionCreate("Books", None))
    documents = DocumentRepository(database)
    digest = "e" * 64
    documents.observe_files([ObservedFile("é.txt", digest, path.stat().st_size)])
    memberships = MembershipRepository(database)
    memberships.add_direct(collection.id, digest)
    engine = FakeEngine([FakeRecord(
        str(path), "Book", "🦊alpha", (collection.id, "c0000000000")
    )])
    service = SearchService(engine, documents, memberships, PathPolicy(root), 2)
    result = service.search(SearchInput("alpha", (collection.id,), ("text", "collections"),
                                        text_limit=20))
    assert result.hits == [{"document_id": digest, "collections": [collection.id],
                            "text": "🦊a", "text_truncated": True}]
