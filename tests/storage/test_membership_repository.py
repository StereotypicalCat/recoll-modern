from pathlib import Path

from recoll_modern.domain.models import CollectionCreate
from recoll_modern.storage.collections import SQLiteCollectionRepository
from recoll_modern.storage.database import Database
from recoll_modern.storage.membership import MembershipRepository

HASH = "a" * 64


def _repo(tmp_path: Path) -> tuple[MembershipRepository, str]:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    collection = SQLiteCollectionRepository(database).create(CollectionCreate("Books"))
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO documents VALUES (?, 1, 'present', ?, ?)",
            (HASH, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO document_paths "
            "(document_hash, relative_path, is_canonical, last_seen_at) VALUES (?, ?, 1, ?)",
            (HASH, "books/a.txt", "2026-01-01T00:00:00+00:00"),
        )
    return MembershipRepository(database), collection.id


def test_direct_membership_wins_over_rule_exclusions(tmp_path: Path) -> None:
    repo, collection_id = _repo(tmp_path)
    repo.add_direct(collection_id, HASH)
    repo.exclude_document(collection_id, HASH)
    assert repo.effective_collections(HASH) == [collection_id]


def test_removing_one_overlapping_rule_keeps_other_source(tmp_path: Path) -> None:
    repo, collection_id = _repo(tmp_path)
    rule_a = repo.create_rule(collection_id, "books", ())
    rule_b = repo.create_rule(collection_id, "other", ())
    repo.replace_rule_members(rule_a.id, [HASH])
    repo.replace_rule_members(rule_b.id, [HASH])
    repo.delete_rule(rule_a.id)
    assert repo.effective_collections(HASH) == [collection_id]


def test_removing_document_suppresses_rule_until_explicit_add(tmp_path: Path) -> None:
    repo, collection_id = _repo(tmp_path)
    rule = repo.create_rule(collection_id, "books", ())
    repo.replace_rule_members(rule.id, [HASH])
    repo.remove_document(collection_id, HASH)
    assert repo.effective_collections(HASH) == []
    repo.add_direct(collection_id, HASH)
    assert repo.effective_collections(HASH) == [collection_id]


def test_rule_deletion_reports_changed_document_hashes(tmp_path: Path) -> None:
    repo, collection_id = _repo(tmp_path)
    rule = repo.create_rule(collection_id, "books", ())
    repo.replace_rule_members(rule.id, [HASH])
    assert repo.delete_rule(rule.id) == ["books/a.txt"]
