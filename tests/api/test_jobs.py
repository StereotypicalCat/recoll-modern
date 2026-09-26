import time

from fastapi.testclient import TestClient


def test_job_reindex_enqueues_versioned_request(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    response = client.post("/jobs/reindex", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 202
    job = response.json()["job"]
    assert job["request"]["version"] == 1
    assert job["fail_on_file_error"] is False
    listed = client.get("/jobs").json()
    assert listed["total"] == 1


def test_retry_refuses_completed_job(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    response = client.post("/jobs/reindex", json={}, headers={"X-CSRF-Token": csrf})
    job_id = response.json()["job"]["id"]
    for _ in range(100):
        if client.get(f"/jobs/{job_id}").json()["job"]["state"] == "completed":
            break
        time.sleep(0.01)
    response = client.post(f"/jobs/{job_id}/retry", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_retryable"


def test_job_list_validates_pagination(authenticated: tuple[TestClient, str]) -> None:
    client, _ = authenticated
    response = client.get("/jobs", params={"limit": 201})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
