import os
import struct
from pathlib import Path

import pytest

from recoll_modern.indexing.map_export import export_membership_map


class FakeRows:
    def __init__(self, rows: dict[str, list[str]]) -> None:
        self.rows = rows

    def membership_map_rows(self) -> list[tuple[str, list[str]]]:
        return list(self.rows.items())


def _decode(path: Path) -> dict[str, str]:
    data = path.read_bytes()
    assert data[:4] == b"RCM1"
    offset = 4
    result = {}
    while offset < len(data):
        path_length = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        name = data[offset:offset + path_length].decode()
        offset += path_length
        value_length = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        value = data[offset:offset + value_length].decode()
        offset += value_length
        result[name] = value
    return result


def test_export_is_atomic_and_handles_newlines(tmp_path: Path) -> None:
    destination = tmp_path / "membership.map"
    export_membership_map(FakeRows({"/documents/odd\nname.pdf": ["c0000000001"]}), destination)
    assert _decode(destination) == {"/documents/odd\nname.pdf": "c0000000001"}
    assert list(tmp_path.glob("*.tmp")) == []
    assert destination.stat().st_mode & 0o777 == 0o640


def test_export_sorts_paths_and_ids(tmp_path: Path) -> None:
    destination = tmp_path / "membership.map"
    export_membership_map(FakeRows({
        "/documents/z": ["c0000000002", "c0000000001"],
        "/documents/a": ["c0000000003"],
    }), destination)
    assert list(_decode(destination)) == ["/documents/a", "/documents/z"]
    assert _decode(destination)["/documents/z"] == "c0000000001 c0000000002"


def test_failed_replace_preserves_old_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "membership.map"
    export_membership_map(FakeRows({"/documents/old": ["c0000000001"]}), destination)
    old = destination.read_bytes()

    def fail_replace(source: str | Path, target: str | Path) -> None:
        raise OSError("injected failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        export_membership_map(FakeRows({"/documents/new": ["c0000000002"]}), destination)
    assert destination.read_bytes() == old
    assert list(tmp_path.glob("*.tmp")) == []
