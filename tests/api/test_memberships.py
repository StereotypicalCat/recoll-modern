import time
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient


def _collection(client: TestClient, csrf: str) -> str:
    response = client.post(
        "/collections", json={"name": "Books"}, headers={"X-CSRF-Token": csrf}
    )
    return cast(str, response.json()["id"])


def _wait(client: TestClient, job_id: str) -> dict[str, object]:
    for _ in range(100):
        job = client.get(f"/jobs/{job_id}").json()["job"]
        if job["state"] not in ("queued", "running"):
            return cast(dict[str, object], job)
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_persistent_directory_request_enqueues_replayable_job(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, csrf = authenticated
    books = tmp_path / "docs" / "books"
    books.mkdir()
    (books / "a.txt").write_text("a")
    collection_id = _collection(client, csrf)
    response = client.post(
        f"/collections/{collection_id}/memberships",
        headers={"X-CSRF-Token": csrf},
        json={"sources": [{"type": "directory", "path": "books", "mode": "persistent",
                           "excluded_directories": []}]},
    )
    assert response.status_code == 202
    assert response.json()["job"]["state"] == "queued"
    job_id = response.json()["job"]["id"]
    assert _wait(client, job_id)["state"] == "completed"
    rules = client.get(f"/collections/{collection_id}/directory-rules").json()["items"]
    assert len(rules) == 1
    members = client.get(f"/collections/{collection_id}/documents").json()["items"]
    assert len(members) == 1
    assert members[0]["contributing_rules"] == [rules[0]["id"]]


def test_invalid_file_source_combination_is_rejected(
    authenticated: tuple[TestClient, str]
) -> None:
    client, csrf = authenticated
    collection_id = _collection(client, csrf)
    response = client.post(
        f"/collections/{collection_id}/memberships",
        headers={"X-CSRF-Token": csrf},
        json={"sources": [{"type": "file", "path": "a.txt", "mode": "persistent"}]},
    )
    assert response.status_code == 422


def test_duplicate_normalized_sources_are_rejected(
    authenticated: tuple[TestClient, str]
) -> None:
    client, csrf = authenticated
    collection_id = _collection(client, csrf)
    response = client.post(
        f"/collections/{collection_id}/memberships",
        headers={"X-CSRF-Token": csrf},
        json={"sources": [
            {"type": "file", "path": "books/a.txt"},
            {"type": "file", "path": "books//a.txt"},
        ]},
    )
    assert response.status_code == 422


def test_strict_job_keeps_membership_empty_on_file_error(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, csrf = authenticated
    (tmp_path / "docs" / "good.txt").write_text("good")
    collection_id = _collection(client, csrf)
    response = client.post(
        f"/collections/{collection_id}/memberships",
        headers={"X-CSRF-Token": csrf},
        json={"sources": [
            {"type": "file", "path": "good.txt"},
            {"type": "file", "path": "gone.txt"},
        ], "fail_on_file_error": True},
    )
    assert _wait(client, response.json()["job"]["id"])["state"] == "failed"
    assert client.get(f"/collections/{collection_id}/documents").json()["items"] == []


def test_removing_one_rule_preserves_overlapping_membership(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, csrf = authenticated
    root = tmp_path / "docs"
    for name in ("books", "other"):
        directory = root / name
        directory.mkdir()
        (directory / "a.txt").write_text("same")
    collection_id = _collection(client, csrf)
    for name in ("books", "other"):
        response = client.post(
            f"/collections/{collection_id}/memberships",
            headers={"X-CSRF-Token": csrf},
            json={"sources": [{"type": "directory", "path": name, "mode": "persistent"}]},
        )
        assert _wait(client, response.json()["job"]["id"])["state"] == "completed"
    rules = client.get(f"/collections/{collection_id}/directory-rules").json()["items"]
    response = client.delete(
        f"/collections/{collection_id}/directory-rules/{rules[0]['id']}",
        headers={"X-CSRF-Token": csrf},
    )
    assert _wait(client, response.json()["job"]["id"])["state"] == "completed"
    members = client.get(f"/collections/{collection_id}/documents").json()["items"]
    assert len(members) == 1
    assert members[0]["contributing_rules"] == [rules[1]["id"]]


def test_rule_exclusion_patch_removes_rule_membership(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, csrf = authenticated
    skipped = tmp_path / "docs" / "books" / "skip"
    skipped.mkdir(parents=True)
    (skipped / "a.txt").write_text("a")
    collection_id = _collection(client, csrf)
    response = client.post(
        f"/collections/{collection_id}/memberships",
        headers={"X-CSRF-Token": csrf},
        json={"sources": [{"type": "directory", "path": "books", "mode": "persistent"}]},
    )
    assert _wait(client, response.json()["job"]["id"])["state"] == "completed"
    rule_id = client.get(f"/collections/{collection_id}/directory-rules").json()["items"][0]["id"]
    patch = client.patch(
        f"/collections/{collection_id}/directory-rules/{rule_id}",
        headers={"X-CSRF-Token": csrf},
        json={"excluded_directories": ["books/skip"]},
    )
    assert _wait(client, patch.json()["job"]["id"])["state"] == "completed"
    assert client.get(f"/collections/{collection_id}/documents").json()["items"] == []


def test_remove_document_creates_override_then_direct_add_restores_it(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, csrf = authenticated
    books = tmp_path / "docs" / "books"
    books.mkdir()
    (books / "a.txt").write_text("a")
    collection_id = _collection(client, csrf)
    response = client.post(
        f"/collections/{collection_id}/memberships",
        headers={"X-CSRF-Token": csrf},
        json={"sources": [{"type": "directory", "path": "books", "mode": "persistent"}]},
    )
    assert _wait(client, response.json()["job"]["id"])["state"] == "completed"
    documents = client.get(f"/collections/{collection_id}/documents").json()["items"]
    document_id = documents[0]["document_id"]
    removed = client.delete(
        f"/collections/{collection_id}/documents/{document_id}",
        headers={"X-CSRF-Token": csrf},
    )
    assert _wait(client, removed.json()["job"]["id"])["state"] == "completed"
    assert client.get(f"/collections/{collection_id}/documents").json()["items"] == []
    added = client.post(
        f"/collections/{collection_id}/memberships",
        headers={"X-CSRF-Token": csrf},
        json={"sources": [{"type": "file", "path": "books/a.txt"}]},
    )
    assert _wait(client, added.json()["job"]["id"])["state"] == "completed"
    members = client.get(f"/collections/{collection_id}/documents").json()["items"]
    assert len(members) == 1
    assert members[0]["direct"] is True
    assert members[0]["override"] is False
