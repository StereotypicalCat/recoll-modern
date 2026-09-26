from pathlib import Path

import pytest

from recoll_modern.indexing.paths import PathPolicy, PathPolicyError


@pytest.mark.parametrize("path", ["/etc/passwd", "../escape", "a/../b", "bad\x00name"])
def test_rejects_unsafe_relative_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(PathPolicyError):
        PathPolicy(tmp_path).resolve_file(path)


def test_file_symlink_outside_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (root / "link.txt").symlink_to(outside)
    with pytest.raises(PathPolicyError, match="outside"):
        PathPolicy(root).resolve_file("link.txt")


def test_file_symlink_inside_root_is_allowed(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    (root / "link.txt").symlink_to("a.txt")
    assert PathPolicy(root).resolve_file("link.txt") == root / "a.txt"
