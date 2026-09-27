"""Exercise the complete HTTP lifecycle with durable state and a deterministic engine."""

import os
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recoll_modern.app import create_app
from recoll_modern.config import Settings
from recoll_modern.engine.fake import FakeEngine, FakeRecord
from recoll_modern.storage.database import Database
from recoll_modern.storage.jobs import JobRepository


def _live_wait(
    client: httpx.Client, path: str, job_id: str, headers: dict[str, str]
) -> dict[str, object]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            response = client.get(f"{path}/jobs/{job_id}", headers=headers)
        except httpx.TransportError:
            time.sleep(0.1)
            continue
        if response.status_code == 200:
            job = cast(dict[str, object], response.json()["job"])
            if job["state"] not in ("queued", "running"):
                return job
        time.sleep(0.1)
    raise AssertionError(f"container job {job_id} did not finish")


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


def test_real_container_collection_lifecycle(
    compose_exec: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> None:
    document_root = os.environ.get("RECOLL_MODERN_DOCUMENTS")
    if document_root is None:
        pytest.fail("RECOLL_MODERN_DOCUMENTS is required for real-container acceptance")
    relative = Path(f"recoll-modern-test-{uuid.uuid4().hex}")
    corpus = Path(document_root) / relative
    (corpus / "a" / ".calibre").mkdir(parents=True)
    (corpus / "b").mkdir()
    marker = uuid.uuid4().hex
    content = {
        "a/shared.txt": f"zebraplatypus duplicate {marker}",
        "b/shared.txt": f"zebraplatypus duplicate {marker}",
        "a/other.txt": f"zebraplatypus first distinct {marker}",
        "b/other.txt": f"zebraplatypus second distinct {marker}",
        "a/special.txt": f"zebraplatypus second only {marker}",
        "a/.calibre/hidden.txt": f"zebraplatypus excluded {marker}",
    }
    for name, text in content.items():
        file = corpus / name
        file.write_text(text)
    prefix = os.environ.get("RECOLL_MODERN_ROOT_PATH", "/").rstrip("/")
    port = os.environ.get("RECOLL_MODERN_PUBLISH_PORT", "8000")
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15) as client:
        login = client.post(f"{prefix}/auth/login", json={
            "username": os.environ["RECOLL_MODERN_ADMIN_USERNAME"],
            "password": os.environ["RECOLL_MODERN_ADMIN_PASSWORD"],
        })
        assert login.status_code == 200, login.text
        cookie = login.cookies.get("recoll_modern_session")
        assert cookie
        headers = {
            "Cookie": f"recoll_modern_session={cookie}",
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        a = client.post(
            f"{prefix}/collections", headers=headers,
            json={"name": f"Real A {uuid.uuid4().hex}"},
        ).json()["id"]
        b = client.post(
            f"{prefix}/collections", headers=headers,
            json={"name": f"Real B {uuid.uuid4().hex}"},
        ).json()["id"]
        def add(collection_id: str, sources: list[dict[str, object]]) -> str:
            response = client.post(
                f"{prefix}/collections/{collection_id}/memberships", headers=headers,
                json={"sources": sources},
            )
            assert response.status_code == 202, response.text
            job_id = response.json()["job"]["id"]
            assert _live_wait(client, prefix, job_id, headers)["state"] == "completed"
            return cast(str, job_id)

        rule_job = add(a, [{
            "type": "directory", "path": (relative / "a").as_posix(),
            "mode": "persistent",
            "excluded_directories": [(relative / "a" / ".calibre").as_posix()],
        }])
        add(b, [{"type": "directory", "path": (relative / "b").as_posix(),
                 "mode": "snapshot"}])
        add(b, [{"type": "file", "path": (relative / "a" / "special.txt").as_posix()}])
        docs_a = client.get(f"{prefix}/collections/{a}/documents", headers=headers).json()["items"]
        docs_b = client.get(f"{prefix}/collections/{b}/documents", headers=headers).json()["items"]
        assert len(docs_a) == 3 and len(docs_b) == 3
        assert all(".calibre" not in item["path"] for item in docs_a)
        shared = next(
            item for item in docs_a
            if item["document_id"] in {other["document_id"] for other in docs_b}
            and item["path"].endswith("shared.txt")
        )
        assert shared["document_id"] in {item["document_id"] for item in docs_b}
        combined = client.get(f"{prefix}/search", params=[
            ("q", "zebraplatypus"), ("collections", a), ("collections", b),
            ("fields", "text"), ("text_limit", "8"),
        ], headers=headers)
        assert combined.status_code == 200, combined.text
        assert len(combined.json()["hits"]) == 4, combined.json()
        assert all(hit["text"] == "zebrapla" for hit in combined.json()["hits"])
        text_response = client.get(
            f"{prefix}/documents/{shared['document_id']}/text", headers=headers
        )
        assert text_response.status_code == 200 and "duplicate" in text_response.json()["text"]
        partial = client.get(
            f"{prefix}/documents/{shared['document_id']}/file",
            headers={**headers, "Range": "bytes=0-7"},
        )
        assert partial.status_code == 206 and partial.content == b"zebrapla"

        (corpus / "a" / "shared.txt").unlink()
        refreshed = client.post(f"{prefix}/jobs/reindex", headers=headers, json={})
        assert _live_wait(client, prefix, refreshed.json()["job"]["id"], headers)[
            "state"
        ] == "completed"
        promoted = client.get(f"{prefix}/collections/{b}/documents", headers=headers).json()[
            "items"
        ]
        assert next(item for item in promoted if item["document_id"] == shared["document_id"])[
            "path"
        ] == (relative / "b" / "shared.txt").as_posix()
        assert client.get(f"{prefix}/search", params={
            "q": "zebraplatypus", "collections": b,
        }, headers=headers).json()["hits"]

        marked = compose_exec(["python", "-c", (
            "from recoll_modern.storage.database import Database; "
            "from pathlib import Path; "
            "db=Database(Path('/var/lib/recoll-modern/recoll-modern.sqlite3')); "
            "c=db.connect(); "
            "c.execute(\"UPDATE jobs SET state='running' WHERE id=?\", "
            "(__import__('sys').argv[1],)); "
            "c.commit(); c.close()"
        ), rule_job])
        assert marked.returncode == 0, marked.stderr
        restarted = subprocess.run(
            ["docker", "compose", "restart", "app"], capture_output=True, text=True,
            check=False, timeout=40,
        )
        assert restarted.returncode == 0, restarted.stderr
        assert _live_wait(client, prefix, rule_job, headers)["state"] == "completed"
