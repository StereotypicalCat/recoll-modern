from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_error_envelope(authenticated: tuple[TestClient, str]) -> None:
    client, _ = authenticated
    response = client.get("/collections/cffffffffff")
    assert response.status_code == 404
    assert response.json() == {"error": {
        "code": "collection_not_found", "message": "Collection was not found", "details": {}
    }}


def test_unknown_route_uses_error_envelope(app_client: TestClient) -> None:
    response = app_client.get("/no-such-route")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "path_not_found"


def test_unexpected_error_has_request_id(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail() -> None:
        raise RuntimeError("private filesystem path")

    app = cast(FastAPI, app_client.app)
    monkeypatch.setattr(app.state.engine, "health", fail)
    with TestClient(
        app_client.app, base_url="https://testserver", raise_server_exceptions=False
    ) as client:
        response = client.get("/health")
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == response.json()["error"]["details"]["request_id"]
    assert "private" not in response.text
