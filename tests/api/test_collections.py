from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_collection_crud_and_confirmation(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    headers = {"X-CSRF-Token": csrf}
    created = client.post("/collections", json={"name": "Books"}, headers=headers)
    assert created.status_code == 201
    collection_id = created.json()["id"]
    assert client.get(f"/collections/{collection_id}").json()["name"] == "Books"
    assert client.get("/collections").json()["total"] == 1
    renamed = client.patch(
        f"/collections/{collection_id}", json={"name": "Reading"}, headers=headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Reading"
    denied = client.delete(
        f"/collections/{collection_id}", params={"confirmation": "Books"}, headers=headers
    )
    assert denied.status_code == 409
    deleted = client.delete(
        f"/collections/{collection_id}", params={"confirmation": "Reading"}, headers=headers
    )
    assert deleted.status_code == 202
    assert client.get(f"/collections/{collection_id}").status_code == 404


def test_collection_list_validates_pagination(authenticated: tuple[TestClient, str]) -> None:
    client, _ = authenticated
    response = client.get("/collections", params={"limit": 201})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_empty_create_and_rename_do_not_enqueue_jobs(
    authenticated: tuple[TestClient, str]
) -> None:
    client, csrf = authenticated
    headers = {"X-CSRF-Token": csrf}
    created = client.post("/collections", json={"name": "Books"}, headers=headers)
    collection_id = created.json()["id"]
    client.patch(f"/collections/{collection_id}", json={"name": "Reading"}, headers=headers)
    with cast(FastAPI, client.app).state.database.connect() as connection:
        total = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert total == 0
