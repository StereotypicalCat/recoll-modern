"""Read application services and enforce cookie sessions."""

from typing import cast

from fastapi import Request

from recoll_modern.domain.auth import AuthenticatedUser, AuthService

COOKIE_NAME = "recoll_modern_session"


def auth_service(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.auth)


def require_user(request: Request) -> AuthenticatedUser:
    return auth_service(request).authenticate(
        request.cookies.get(COOKIE_NAME),
        csrf_token=request.headers.get("X-CSRF-Token"),
        unsafe=request.method not in ("GET", "HEAD", "OPTIONS"),
    )
