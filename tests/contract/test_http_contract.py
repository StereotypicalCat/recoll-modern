"""Requirement-to-test matrix for spec 001.

R1–R4: api/test_collections.py, storage/test_collection_repository.py
R5–R8: storage/test_documents.py, indexing/test_reconcile.py, integration/test_end_to_end.py
R9–R12: api/test_memberships.py, indexing/test_discovery.py, indexing/test_paths.py
R13–R14: helper/test_membership_helper.py, integration/test_read_only_corpus.py
R15–R18: api/test_jobs.py, indexing/test_job_handlers.py, indexing/test_worker.py
R19–R23: api/test_search.py, api/test_documents.py, domain/test_search.py
R24–R26: api/test_auth.py, domain/test_auth.py, test_unauthenticated_routes
R27–R30: api/test_health.py, api/test_files.py, api/test_root_path.py,
         security/test_proxy_headers.py, security/test_paths.py, security/test_downloads.py
R31: unit/test_config.py, integration/test_container_smoke.py, integration/test_end_to_end.py
C1: integration/test_read_only_corpus.py, helper/test_membership_helper.py
C2–C3: storage/test_documents.py, integration/test_end_to_end.py
C4: api/test_search.py, test_scoped_search_error_codes
"""

import hashlib
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recoll_modern.engine.fake import FakeRecord
from recoll_modern.indexing.discovery import ObservedFile


def test_unauthenticated_routes(app_client: TestClient) -> None:
    for path in (
        "/files", "/collections", "/jobs", "/search?q=book&collections=c0000000000",
        f"/documents/{'a' * 64}/text", f"/documents/{'a' * 64}/file",
    ):
        response = app_client.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "unauthenticated", path


def test_scoped_search_error_codes(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    collection_id = client.post(
        "/collections", json={"name": "Books"}, headers={"X-CSRF-Token": csrf}
    ).json()["id"]
    invalid_field = client.get("/search", params={
        "q": "book", "collections": collection_id, "fields": "unknown",
    })
    assert invalid_field.status_code == 422
    assert invalid_field.json()["error"]["code"] == "invalid_field"
    invalid_query = client.get("/search", params={
        "q": "book\\evil", "collections": collection_id,
    })
    assert invalid_query.status_code == 400
    assert invalid_query.json()["error"]["code"] == "invalid_query"


def test_same_directory_membership_and_same_name_identity(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, csrf = authenticated
    headers = {"X-CSRF-Token": csrf}
    first_id = client.post("/collections", json={"name": "First"}, headers=headers).json()["id"]
    second_id = client.post("/collections", json={"name": "Second"}, headers=headers).json()["id"]
    root = tmp_path / "docs"
    (root / "a").mkdir()
    (root / "b").mkdir()
    sources = [
        ("a/same.txt", b"python first", first_id),
        ("a/other.txt", b"python second", second_id),
        ("b/same.txt", b"python third", second_id),
    ]
    app = cast(FastAPI, client.app)
    engine_records = []
    for relative, content, collection_id in sources:
        path = root / relative
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        app.state.documents.observe_files([ObservedFile(relative, digest, len(content))])
        app.state.memberships.add_direct(collection_id, digest)
        engine_records.append(FakeRecord(str(path), relative, content.decode(), (collection_id,)))
    app.state.engine.records = engine_records
    first = client.get("/search", params={"q": "python", "collections": first_id}).json()
    second = client.get("/search", params={"q": "python", "collections": second_id}).json()
    assert [hit["path"] for hit in first["hits"]] == ["a/same.txt"]
    assert {hit["path"] for hit in second["hits"]} == {"a/other.txt", "b/same.txt"}
    assert first["hits"][0]["document_id"] != next(
        hit["document_id"] for hit in second["hits"] if hit["path"] == "b/same.txt"
    )
