from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recoll_modern.app import create_app
from recoll_modern.config import Settings
from recoll_modern.engine.fake import FakeEngine


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setenv("RECOLL_MODERN_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("RECOLL_MODERN_ADMIN_PASSWORD", "secret-password")
    (tmp_path / "docs").mkdir()
    settings = Settings.from_env({
        "RECOLL_MODERN_DOCUMENT_ROOT": str(tmp_path / "docs"),
        "RECOLL_MODERN_STATE_ROOT": str(tmp_path / "state"),
        "RECOLL_MODERN_RECOLL_CONFIG_DIR": str(tmp_path / "recoll"),
    })
    with TestClient(create_app(settings, FakeEngine([])), base_url="https://testserver") as client:
        yield client


@pytest.fixture
def prefixed_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setenv("RECOLL_MODERN_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("RECOLL_MODERN_ADMIN_PASSWORD", "secret-password")
    (tmp_path / "docs").mkdir()
    settings = Settings.from_env({
        "RECOLL_MODERN_DOCUMENT_ROOT": str(tmp_path / "docs"),
        "RECOLL_MODERN_STATE_ROOT": str(tmp_path / "state"),
        "RECOLL_MODERN_RECOLL_CONFIG_DIR": str(tmp_path / "recoll"),
        "RECOLL_MODERN_ROOT_PATH": "/recoll",
    })
    with TestClient(create_app(settings, FakeEngine([])), base_url="https://testserver") as client:
        yield client


@pytest.fixture
def authenticated(app_client: TestClient) -> tuple[TestClient, str]:
    response = app_client.post(
        "/auth/login", json={"username": "admin", "password": "secret-password"}
    )
    assert response.status_code == 200
    return app_client, response.json()["csrf_token"]
