"""Image tag policy used by the Gitea publishing workflow."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("refs/heads/main", ["main"]),
        ("refs/tags/v1.2.3", ["v1.2.3", "latest"]),
        ("refs/tags/v1.2.3-rc1", []),
        ("refs/tags/vfoo", []),
        ("refs/heads/maintainer", []),
        ("refs/pull/42/merge", []),
    ],
)
def test_only_main_and_full_release_tags_publish(ref: str, expected: list[str]) -> None:
    from scripts.image_tags import tags_for_ref

    assert tags_for_ref(ref) == expected


def test_cli_prints_full_registry_references() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/image_tags.py", "refs/tags/v1.2.3"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == [
        "gitea.lucaswinther.info/lucasw89/recoll-modern:v1.2.3",
        "gitea.lucaswinther.info/lucasw89/recoll-modern:latest",
    ]
