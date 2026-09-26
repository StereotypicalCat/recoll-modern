"""Extracted text and safe original file retrieval."""

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recoll_modern.engine.fake import FakeRecord
from recoll_modern.indexing.discovery import ObservedFile


def _document(client: TestClient, tmp_path: Path) -> str:
    path = tmp_path / "docs" / "quoted\"name.txt"
    path.write_bytes(b"abcdef")
    digest = "b" * 64
    app = cast(FastAPI, client.app)
    app.state.documents.observe_files([ObservedFile(path.name, digest, 6)])
    app.state.engine.records = [FakeRecord(str(path), "Title", "complete text", ())]
    return digest


def test_text_and_byte_range(authenticated: tuple[TestClient, str], tmp_path: Path) -> None:
    client, _ = authenticated
    digest = _document(client, tmp_path)
    text = client.get(f"/documents/{digest}/text")
    assert text.status_code == 200
    assert text.json()["text"] == "complete text"
    response = client.get(f"/documents/{digest}/file", headers={"Range": "bytes=1-3"})
    assert response.status_code == 206
    assert response.content == b"bcd"
    assert response.headers["content-range"] == "bytes 1-3/6"
    assert response.headers["content-disposition"] == 'inline; filename="quoted_name.txt"'
    assert client.get(
        f"/documents/{digest}/file", headers={"Range": "bytes=99-100"}
    ).status_code == 416


def test_unknown_and_missing_documents(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, _ = authenticated
    assert client.get(f"/documents/{'0' * 64}/text").json()["error"]["code"] == (
        "document_not_found"
    )
    digest = _document(client, tmp_path)
    (tmp_path / "docs" / 'quoted"name.txt').unlink()
    response = client.get(f"/documents/{digest}/file")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "document_missing"


def test_html_is_attachment(authenticated: tuple[TestClient, str], tmp_path: Path) -> None:
    client, _ = authenticated
    path = tmp_path / "docs" / "danger.html"
    path.write_text("<script>alert(1)</script>")
    digest = "d" * 64
    cast(FastAPI, client.app).state.documents.observe_files([
        ObservedFile("danger.html", digest, path.stat().st_size)
    ])
    response = client.get(f"/documents/{digest}/file")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["content-type"].startswith("text/html")
