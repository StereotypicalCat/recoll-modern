import os
import subprocess
from pathlib import Path

import pytest

from recoll_modern.indexing.map_export import export_membership_map


class FakeRows:
    def membership_map_rows(self) -> list[tuple[str, list[str]]]:
        return [
            ("/documents/a.pdf", ["c0000000002", "c0000000001"]),
            ("/documents/odd\nname.pdf", ["c0000000003"]),
        ]


@pytest.fixture(scope="module")
def compiled_helper(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[2]
    output = tmp_path_factory.mktemp("helper") / "recoll-membership"
    subprocess.run([
        "cc", "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
        str(root / "helper" / "recoll_membership.c"), "-o", str(output),
    ], check=True)
    return output


def test_helper_returns_sorted_space_separated_ids(
    compiled_helper: Path, tmp_path: Path
) -> None:
    map_file = tmp_path / "membership.map"
    export_membership_map(FakeRows(), map_file)
    result = subprocess.run(
        [compiled_helper, "/documents/a.pdf"],
        env={**os.environ, "RECOLL_MODERN_MEMBERSHIP_MAP": str(map_file)},
        text=True, capture_output=True, check=True,
    )
    assert result.stdout == "c0000000001 c0000000002\n"


def test_helper_matches_newline_path_and_ignores_unknown(
    compiled_helper: Path, tmp_path: Path
) -> None:
    map_file = tmp_path / "membership.map"
    export_membership_map(FakeRows(), map_file)
    env = {**os.environ, "RECOLL_MODERN_MEMBERSHIP_MAP": str(map_file)}
    found = subprocess.run(
        [compiled_helper, "/documents/odd\nname.pdf"], env=env,
        text=True, capture_output=True, check=True,
    )
    missing = subprocess.run(
        [compiled_helper, "/documents/missing.pdf"], env=env,
        text=True, capture_output=True, check=True,
    )
    assert found.stdout == "c0000000003\n"
    assert missing.stdout == ""


def test_helper_rejects_corrupt_map(compiled_helper: Path, tmp_path: Path) -> None:
    map_file = tmp_path / "membership.map"
    map_file.write_bytes(b"RCM1\xff\xff\xff\xff")
    result = subprocess.run(
        [compiled_helper, "/documents/a.pdf"],
        env={**os.environ, "RECOLL_MODERN_MEMBERSHIP_MAP": str(map_file)},
        text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert "corrupt" in result.stderr.lower()
