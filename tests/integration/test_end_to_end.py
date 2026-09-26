"""Exercise the complete HTTP lifecycle with durable state and a deterministic engine."""

import time
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recoll_modern.app import create_app
from recoll_modern.config import Settings
from recoll_modern.engine.fake import FakeEngine, FakeRecord
from recoll_modern.storage.database import Database
from recoll_modern.storage.jobs import JobRepository


def _wait(client: TestClient, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/recoll/jobs/{job_id}").json()["job"]
        if job["state"] not in ("queued", "running"):
            return cast(dict[str, object], job)
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


def test_complete_collection_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "docs"
    (root / "a" / ".calibre").mkdir(parents=True)
    (root / "b").mkdir()
    (root / "a" / "shared.txt").write_text("python duplicate")
    (root / "b" / "shared.txt").write_text("python duplicate")
    (root / "a" / "other.txt").write_text("python separate")
    (root / "a" / ".calibre" / "hidden.txt").write_text("python hidden")
    monkeypatch.setenv("RECOLL_MODERN_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("RECOLL_MODERN_ADMIN_PASSWORD", "secret-password")
    settings = Settings.from_env({
        "RECOLL_MODERN_DOCUMENT_ROOT": str(root),
        "RECOLL_MODERN_STATE_ROOT": str(tmp_path / "state"),
        "RECOLL_MODERN_RECOLL_CONFIG_DIR": str(tmp_path / "config"),
        "RECOLL_MODERN_ROOT_PATH": "/recoll",
        "RECOLL_MODERN_INLINE_TEXT_LIMIT": "12",
        "RECOLL_MODERN_INLINE_TEXT_LIMIT_MAX": "12",
    })
    engine = FakeEngine([])
    with TestClient(create_app(settings, engine), base_url="https://testserver") as client:
        login = client.post("/recoll/auth/login", json={
            "username": "admin", "password": "secret-password",
        })
        assert login.status_code == 200
        assert "Path=/recoll" in login.headers["set-cookie"]
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        first = client.post("/recoll/collections", json={"name": "First"}, headers=headers)
        second = client.post("/recoll/collections", json={"name": "Second"}, headers=headers)
        a, b = first.json()["id"], second.json()["id"]
        for collection_id, sources in (
            (a, [{"type": "directory", "path": "a", "mode": "persistent",
                  "excluded_directories": ["a/.calibre"]}]),
            (b, [{"type": "directory", "path": "b", "mode": "snapshot"}]),
        ):
            response = client.post(
                f"/recoll/collections/{collection_id}/memberships",
                headers=headers, json={"sources": sources},
            )
            assert _wait(client, response.json()["job"]["id"])["state"] == "completed"
        direct = client.post(
            f"/recoll/collections/{a}/memberships", headers=headers,
            json={"sources": [
                {"type": "file", "path": "a/other.txt"},
                {"type": "file", "path": "a/shared.txt"},
            ]},
        )
        assert _wait(client, direct.json()["job"]["id"])["state"] == "completed"
        members_a = client.get(f"/recoll/collections/{a}/documents").json()["items"]
        members_b = client.get(f"/recoll/collections/{b}/documents").json()["items"]
        assert len(members_a) == 2 and len(members_b) == 1
        shared = next(item for item in members_a if item["path"] == "a/shared.txt")
        assert shared["document_id"] == members_b[0]["document_id"]
        assert all(item["path"] != "a/.calibre/hidden.txt" for item in members_a)
        engine.records = [
            FakeRecord(str(root / "a" / "shared.txt"), "Shared", "python duplicate", (a, b)),
            FakeRecord(str(root / "a" / "other.txt"), "Other", "python separate", (a,)),
        ]
        result = client.get("/recoll/search", params=[
            ("q", "python"), ("collections", a), ("collections", b),
            ("fields", "text"), ("text_limit", "6"),
        ])
        assert result.status_code == 200
        assert len(result.json()["hits"]) == 2
        assert result.json()["hits"][0]["text"] == "python"
        assert client.get(
            f"/recoll/documents/{shared['document_id']}/text"
        ).json()["text"] == "python duplicate"
        partial = client.get(
            f"/recoll/documents/{shared['document_id']}/file", headers={"Range": "bytes=0-5"}
        )
        assert partial.status_code == 206 and partial.content == b"python"

        (root / "a" / "shared.txt").unlink()
        refresh = client.post("/recoll/jobs/reindex", headers=headers, json={})
        assert _wait(client, refresh.json()["job"]["id"])["state"] == "completed"
        promoted = cast(FastAPI, client.app).state.documents.get(shared["document_id"])
        assert promoted.canonical_path == "b/shared.txt"
        engine.records = [
            FakeRecord(str(root / "b" / "shared.txt"), "Shared", "python duplicate", (a, b))
        ]
        assert client.get("/recoll/search", params={
            "q": "python", "collections": a,
        }).json()["hits"][0]["document_id"] == shared["document_id"]

    jobs = JobRepository(Database(settings.database_path))
    interrupted = jobs.enqueue("reindex", {"version": 1, "paths": [], "collections": []}, False)
    with Database(settings.database_path).transaction() as connection:
        connection.execute("UPDATE jobs SET state = 'running' WHERE id = ?", (interrupted.id,))
    with TestClient(create_app(settings, engine), base_url="https://testserver") as client:
        client.post("/recoll/auth/login", json={
            "username": "admin", "password": "secret-password",
        })
        assert _wait(client, interrupted.id)["state"] == "completed"
