"""Untrusted clients cannot replace the configured mount prefix."""

from fastapi.testclient import TestClient


def test_direct_client_cannot_forge_prefix(prefixed_client: TestClient) -> None:
    response = prefixed_client.get("/evil/health", headers={
        "X-Forwarded-Prefix": "/evil", "X-Forwarded-Host": "attacker.example",
        "X-Forwarded-Proto": "https",
    })
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "path_not_found"
