from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recoll_modern.app import create_app
from recoll_modern.config import Settings
from recoll_modern.engine.fake import FakeEngine


def test_cookie_and_openapi_honor_root_path(prefixed_client: TestClient) -> None:
    anonymous = prefixed_client.get("/recoll/openapi.json")
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "unauthenticated"
    response = prefixed_client.post(
        "/recoll/auth/login", json={"username": "admin", "password": "secret-password"}
    )
    assert response.status_code == 200
    assert "Path=/recoll" in response.headers["set-cookie"]
    assert prefixed_client.get("/recoll/openapi.json").status_code == 200
    assert prefixed_client.get("/auth/login").status_code == 404


@pytest.mark.parametrize(
    "path", ["/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"]
)
def test_api_documentation_requires_session(app_client: TestClient, path: str) -> None:
    response = app_client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_trusted_forwarded_prefix_routes_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RECOLL_MODERN_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("RECOLL_MODERN_ADMIN_PASSWORD", "secret-password")
    (tmp_path / "docs").mkdir()
    settings = Settings.from_env({
        "RECOLL_MODERN_DOCUMENT_ROOT": str(tmp_path / "docs"),
        "RECOLL_MODERN_STATE_ROOT": str(tmp_path / "state"),
        "RECOLL_MODERN_TRUSTED_PROXIES": "127.0.0.1/32",
    })
    with TestClient(
        create_app(settings, FakeEngine([])), base_url="https://testserver",
        client=("127.0.0.1", 50000),
    ) as client:
        response = client.get("/recoll/health", headers={"X-Forwarded-Prefix": "/recoll"})
    assert response.status_code == 200
