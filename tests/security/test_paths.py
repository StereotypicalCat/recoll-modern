"""Containment is rechecked when serving a document."""

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recoll_modern.indexing.discovery import ObservedFile


def test_swapped_symlink_cannot_escape_document_root(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, _ = authenticated
    root = tmp_path / "docs"
    path = root / "file.txt"
    path.write_text("safe")
    digest = "a" * 64
    cast(FastAPI, client.app).state.documents.observe_files([
        ObservedFile("file.txt", digest, 4)
    ])
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    path.unlink()
    path.symlink_to(outside)
    response = client.get(f"/documents/{digest}/file")
    assert response.status_code == 410
    assert b"secret" not in response.content
