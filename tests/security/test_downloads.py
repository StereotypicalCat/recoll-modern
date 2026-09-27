"""Missing documents use the spec's distinct gone response."""

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recoll_modern.api.documents import open_contained_file
from recoll_modern.indexing.discovery import ObservedFile


def test_missing_document_is_gone(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, _ = authenticated
    path = tmp_path / "docs" / "gone.txt"
    path.write_text("gone")
    digest = "f" * 64
    cast(FastAPI, client.app).state.documents.observe_files([
        ObservedFile("gone.txt", digest, 4)
    ])
    path.unlink()
    response = client.get(f"/documents/{digest}/file")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "document_missing"


def test_open_descriptor_cannot_be_redirected_by_later_symlink_swap(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    file = root / "safe.txt"
    file.write_text("safe")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    opened = open_contained_file(root, "safe.txt")
    file.unlink()
    file.symlink_to(outside)
    try:
        assert opened.read() == b"safe"
    finally:
        opened.close()
