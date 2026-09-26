"""Scoped search transport and result projection."""

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recoll_modern.engine.fake import FakeRecord
from recoll_modern.indexing.discovery import ObservedFile


def _seed(client: TestClient, csrf: str, tmp_path: Path) -> tuple[str, str]:
    path = tmp_path / "docs" / "book.txt"
    path.write_text("python documentation and examples")
    collection_id = client.post(
        "/collections", json={"name": "Books"}, headers={"X-CSRF-Token": csrf}
    ).json()["id"]
    digest = "a" * 64
    app = cast(FastAPI, client.app)
    app.state.documents.observe_files([ObservedFile("book.txt", digest, path.stat().st_size)])
    app.state.memberships.add_direct(collection_id, digest)
    app.state.engine.records = [FakeRecord(
        str(path), "Python book", "python documentation and examples", (collection_id,)
    )]
    return collection_id, digest


def test_search_requires_scope(authenticated: tuple[TestClient, str]) -> None:
    client, _ = authenticated
    response = client.get("/search", params={"q": "python"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "scope_required"


def test_projection_text_limit_and_scope(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, csrf = authenticated
    collection_id, digest = _seed(client, csrf, tmp_path)
    response = client.get("/search", params=[
        ("q", "python"), ("collections", collection_id), ("fields", "title"),
        ("fields", "text"), ("text_limit", "12"),
    ])
    assert response.status_code == 200
    hit = response.json()["hits"][0]
    assert hit == {"document_id": digest, "title": "Python book",
                   "text": "python docum", "text_truncated": True}
    assert response.json()["total"] == 1
    assert response.json()["total_is_approximate"] is False


def test_search_validates_fields_collections_and_pagination(
    authenticated: tuple[TestClient, str]
) -> None:
    client, csrf = authenticated
    collection_id = client.post(
        "/collections", json={"name": "Books"}, headers={"X-CSRF-Token": csrf}
    ).json()["id"]
    for params, status, code in [
        ({"q": " ", "collections": collection_id}, 400, "invalid_query"),
        ({"q": "a", "collections": "c0000000000"}, 404, "collection_not_found"),
        ({"q": "a", "collections": collection_id, "fields": "bad"}, 400,
         "invalid_query"),
        ({"q": "a", "collections": collection_id, "limit": 101}, 422,
         "validation_failed"),
    ]:
        response = client.get("/search", params=params)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code


def test_search_uses_sqlite_membership_and_generates_links(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, csrf = authenticated
    collection_id, digest = _seed(client, csrf, tmp_path)
    app = cast(FastAPI, client.app)
    app.state.engine.records = [FakeRecord(
        str(tmp_path / "docs" / "book.txt"), "Python", "python", (collection_id,),
    )]
    response = client.get("/search", params=[
        ("q", "python"), ("collections", collection_id), ("collections", collection_id),
        ("fields", "links"), ("fields", "collections"),
    ])
    assert response.status_code == 200
    hit = response.json()["hits"][0]
    assert hit["document_id"] == digest
    assert hit["collections"] == [collection_id]
    assert hit["links"]["file"].endswith(f"/documents/{digest}/file")


def test_default_fields_omit_text_and_links(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, csrf = authenticated
    collection_id, _ = _seed(client, csrf, tmp_path)
    hit = client.get("/search", params={"q": "python", "collections": collection_id}).json()[
        "hits"
    ][0]
    assert "snippets" in hit and "score" in hit and "collections" in hit
    assert "text" not in hit and "links" not in hit


def test_stale_engine_collections_do_not_leak_into_result(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, csrf = authenticated
    collection_id, _ = _seed(client, csrf, tmp_path)
    app = cast(FastAPI, client.app)
    app.state.engine.records = [FakeRecord(
        str(tmp_path / "docs" / "book.txt"), "Python", "python",
        (collection_id, "c0000000000"),
    )]
    response = client.get("/search", params={"q": "python", "collections": collection_id})
    assert response.json()["hits"][0]["collections"] == [collection_id]


def test_links_honor_mount_prefix(prefixed_client: TestClient, tmp_path: Path) -> None:
    client = prefixed_client
    csrf = client.post(
        "/recoll/auth/login", json={"username": "admin", "password": "secret-password"}
    ).json()["csrf_token"]
    path = tmp_path / "docs" / "book.txt"
    path.write_text("python")
    collection_id = client.post(
        "/recoll/collections", json={"name": "Books"}, headers={"X-CSRF-Token": csrf}
    ).json()["id"]
    digest = "c" * 64
    app = cast(FastAPI, client.app)
    app.state.documents.observe_files([ObservedFile("book.txt", digest, 6)])
    app.state.memberships.add_direct(collection_id, digest)
    app.state.engine.records = [FakeRecord(str(path), "Python", "python", (collection_id,))]
    response = client.get("/recoll/search", params=[
        ("q", "python"), ("collections", collection_id), ("fields", "links"),
    ])
    assert response.status_code == 200
    assert response.json()["hits"][0]["links"]["file"].endswith(
        f"/recoll/documents/{digest}/file"
    )
