import hashlib
import os
from pathlib import Path

from recoll_modern.indexing.discovery import Source, discover_sources, hash_file_stable
from recoll_modern.indexing.paths import PathPolicy


def test_directory_symlink_is_not_walked(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    books = root / "books"
    books.mkdir(parents=True)
    (books / "a.txt").write_text("a")
    target = root / "secret"
    target.mkdir()
    (target / "secret.pdf").write_text("secret")
    (books / "link").symlink_to(target, target_is_directory=True)
    report = discover_sources(PathPolicy(root), [Source.directory("books", mode="snapshot")])
    assert report.relative_paths == ("books/a.txt",)
    assert report.errors == ()


def test_directory_source_symlink_is_not_walked(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    target = root / "real"
    target.mkdir(parents=True)
    (target / "a.txt").write_text("a")
    (root / "link").symlink_to(target, target_is_directory=True)
    report = discover_sources(PathPolicy(root), [Source.directory("link", mode="snapshot")])
    assert report.files == ()


def test_exact_recursive_exclusion(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    for name in ("books/keep/a.txt", "books/skip/b.txt", "books/skip/deep/c.txt"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    report = discover_sources(PathPolicy(root), [Source.directory(
        "books", mode="persistent", excluded_directories=("books/skip",)
    )])
    assert report.relative_paths == ("books/keep/a.txt",)


def test_outside_file_symlink_reports_stable_error(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("secret")
    (root / "link").symlink_to(outside)
    report = discover_sources(PathPolicy(root), [Source.file("link")])
    assert [error.code for error in report.errors] == ["file_outside_root"]


def test_vanished_file_reports_error(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    report = discover_sources(PathPolicy(root), [Source.file("gone.txt")])
    assert [error.code for error in report.errors] == ["file_vanished"]


def test_unreadable_file_reports_error(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.txt").write_text("a")
    real_open = Path.open

    def denied(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if path.name == "a.txt":
            raise PermissionError("denied")
        return real_open(path, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(Path, "open", denied)
    report = discover_sources(PathPolicy(root), [Source.file("a.txt")])
    assert [error.code for error in report.errors] == ["file_unreadable"]


def test_hash_file_stable_detects_mutation(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "a.txt"
    path.write_text("before")
    real_fstat = os.fstat
    calls = 0

    def mutating_fstat(fd: int) -> os.stat_result:
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_text("after mutation")
        return real_fstat(fd)

    monkeypatch.setattr(os, "fstat", mutating_fstat)
    result = hash_file_stable(path)
    assert result.code == "file_changed_during_scan"


def test_discovery_hashes_file_bytes(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"hello")
    report = discover_sources(PathPolicy(tmp_path), [Source.file("a.txt")])
    assert report.files[0].content_hash == hashlib.sha256(b"hello").hexdigest()
    assert report.files[0].byte_size == 5
