from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recoll_modern.engine.protocol import EngineHealth


def test_health_is_public_and_ready(app_client: TestClient) -> None:
    response = app_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_untrusted_forwarded_prefix_is_ignored(app_client: TestClient) -> None:
    response = app_client.get("/health", headers={"X-Forwarded-Prefix": "/evil"})
    assert response.status_code == 200
    assert "/evil" not in response.text


def test_health_reports_engine_unavailable(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cast(FastAPI, app_client.app).state.engine, "health", lambda: EngineHealth(False)
    )
    response = app_client.get("/health")
    assert response.status_code == 503
