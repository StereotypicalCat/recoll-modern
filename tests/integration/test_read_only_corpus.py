"""The service must not be able to mutate its document mount."""

import os
import subprocess
import time
from collections.abc import Callable

import httpx
import pytest


def test_document_mount_is_read_only(
    compose_exec: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> None:
    result = compose_exec(["sh", "-c", "touch /documents/must-fail"])
    assert result.returncode != 0


def test_generated_corpus_indexes_and_searches(
    compose_exec: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> None:
    corpus_file = os.environ.get("RECOLL_MODERN_TEST_CORPUS_FILE")
    if corpus_file is None:
        pytest.skip("Set RECOLL_MODERN_TEST_CORPUS_FILE for generated-corpus verification")
    assert compose_exec(["test", "-f", f"/documents/{corpus_file}"]).returncode == 0
    port = os.environ.get("RECOLL_MODERN_PUBLISH_PORT", "8000")
    username = os.environ["RECOLL_MODERN_ADMIN_USERNAME"]
    password = os.environ["RECOLL_MODERN_ADMIN_PASSWORD"]
    prefix = os.environ.get("RECOLL_MODERN_ROOT_PATH", "/").rstrip("/")
    with httpx.Client(base_url=f"http://127.0.0.1:{port}{prefix}", timeout=10) as client:
        login = client.post("/auth/login", json={"username": username, "password": password})
        assert login.status_code == 200, login.text
        csrf = login.json()["csrf_token"]
        cookie = login.cookies.get("recoll_modern_session")
        assert cookie
        headers = {"X-CSRF-Token": csrf, "Cookie": f"recoll_modern_session={cookie}"}
        created = client.post(
            "/collections", json={"name": f"Integration {time.time_ns()}"}, headers=headers
        )
        assert created.status_code == 201, created.text
        collection_id = created.json()["id"]
        queued = client.post(
            f"/collections/{collection_id}/memberships", headers=headers,
            json={"sources": [{"type": "file", "path": corpus_file}]},
        )
        assert queued.status_code == 202, queued.text
        job_id = queued.json()["job"]["id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = client.get(f"/jobs/{job_id}", headers=headers).json()["job"]
            if job["state"] not in ("queued", "running"):
                break
            time.sleep(0.1)
        assert job["state"] == "completed", job
        result = client.get(
            "/search", params={"q": "zebraplatypus", "collections": collection_id},
            headers=headers,
        )
        assert result.status_code == 200, result.text
        assert result.json()["hits"], result.json()
        document_id = result.json()["hits"][0]["document_id"]
        second = client.post(
            "/collections", json={"name": f"Integration second {time.time_ns()}"},
            headers=headers,
        )
        assert second.status_code == 201, second.text
        second_id = second.json()["id"]
        second_job = client.post(
            f"/collections/{second_id}/memberships", headers=headers,
            json={"sources": [{"type": "file", "path": corpus_file}]},
        )
        assert second_job.status_code == 202, second_job.text
        second_job_id = second_job.json()["job"]["id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = client.get(f"/jobs/{second_job_id}", headers=headers).json()["job"]
            if job["state"] not in ("queued", "running"):
                break
            time.sleep(0.1)
        assert job["state"] == "completed", job
        combined = client.get(
            "/search", params=[
                ("q", "zebraplatypus"), ("collections", collection_id),
                ("collections", second_id), ("fields", "collections"),
            ], headers=headers,
        )
        assert combined.status_code == 200, combined.text
        assert len(combined.json()["hits"]) == 1
        assert set(combined.json()["hits"][0]["collections"]) >= {collection_id, second_id}
        extracted = client.get(f"/documents/{document_id}/text", headers=headers)
        assert extracted.status_code == 200, extracted.text
        assert "zebraplatypus" in extracted.json()["text"]
