from fastapi.testclient import TestClient


def test_login_sets_scoped_secure_cookie(app_client: TestClient) -> None:
    response = app_client.post(
        "/auth/login", json={"username": "admin", "password": "secret-password"}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" in cookie and "Path=/" in cookie
    assert response.json()["csrf_token"]


def test_unauthenticated_request_is_refused(app_client: TestClient) -> None:
    response = app_client.get("/collections")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_csrf_required_for_unsafe_request(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    assert client.post("/collections", json={"name": "Books"}).status_code == 403
    response = client.post(
        "/collections", json={"name": "Books"}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 201


def test_session_rotates_csrf_and_logout(authenticated: tuple[TestClient, str]) -> None:
    client, old_csrf = authenticated
    session = client.get("/auth/session")
    assert session.status_code == 200
    new_csrf = session.json()["csrf_token"]
    assert new_csrf != old_csrf
    assert client.post("/auth/logout", headers={"X-CSRF-Token": old_csrf}).status_code == 403
    assert client.post("/auth/logout", headers={"X-CSRF-Token": new_csrf}).status_code == 204
    assert client.get("/auth/session").status_code == 401


def test_login_rejects_cross_origin(app_client: TestClient) -> None:
    response = app_client.post(
        "/auth/login", json={"username": "admin", "password": "secret-password"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
