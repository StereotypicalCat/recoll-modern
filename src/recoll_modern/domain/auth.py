"""Password, session, and CSRF behavior without HTTP dependencies."""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from unicodedata import normalize

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from recoll_modern.domain.errors import AppError


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: str
    username: str
    username_key: str
    password_hash: str
    disabled_at: datetime | None


@dataclass(frozen=True, slots=True)
class SessionRecord:
    token_hash: str
    csrf_hash: str
    user_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SessionCredentials:
    cookie_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: str
    username: str


class AuthRepository(Protocol):
    def user_count(self) -> int: ...

    def create_user(self, username: str, password_hash: str) -> AuthUser: ...

    def get_user_by_name(self, username: str) -> AuthUser | None: ...

    def get_user_by_id(self, user_id: str) -> AuthUser | None: ...

    def create_session(
        self, cookie_token: str, csrf_token: str, user_id: str,
        expires_at: datetime, now: datetime,
    ) -> None: ...

    def get_session(self, cookie_token: str) -> SessionRecord | None: ...

    def delete_session(self, cookie_token: str) -> None: ...

    def touch_session(self, cookie_token: str, now: datetime) -> None: ...

    def update_csrf(self, cookie_token: str, csrf_token: str) -> None: ...


def normalize_username(username: str) -> tuple[str, str]:
    display = normalize("NFC", username.strip())
    if not display:
        raise ValueError("username cannot be empty")
    return display, display.casefold()


class AuthService:
    def __init__(
        self,
        repository: AuthRepository,
        *,
        lifetime: timedelta = timedelta(hours=12),
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if lifetime <= timedelta(0):
            raise ValueError("session lifetime must be positive")
        self._repository = repository
        self._lifetime = lifetime
        self._now = now
        self._hasher = PasswordHasher()

    def seed_initial_admin(self, username: str | None, password: str | None) -> None:
        if self._repository.user_count() > 0:
            return
        if not username or not password:
            raise AppError(
                "validation_failed", "initial administrator credentials are required", 422
            )
        digest = self._hasher.hash(password)
        password = None
        self._repository.create_user(username, digest)

    def login(self, username: str, password: str) -> SessionCredentials:
        user = self._repository.get_user_by_name(username)
        if user is None or user.disabled_at is not None:
            raise _invalid_credentials()
        try:
            valid = self._hasher.verify(user.password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            raise _invalid_credentials() from None
        if not valid:
            raise _invalid_credentials()
        now = self._now()
        cookie_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + self._lifetime
        self._repository.create_session(cookie_token, csrf_token, user.id, expires_at, now)
        return SessionCredentials(cookie_token, csrf_token, expires_at)

    def authenticate(
        self,
        cookie_token: str | None,
        *,
        csrf_token: str | None = None,
        unsafe: bool = False,
    ) -> AuthenticatedUser:
        session = self._repository.get_session(cookie_token) if cookie_token else None
        now = self._now()
        if session is None or session.expires_at <= now:
            raise AppError("unauthenticated", "Authentication is required", 401)
        user = self._repository.get_user_by_id(session.user_id)
        if user is None or user.disabled_at is not None:
            raise AppError("unauthenticated", "Authentication is required", 401)
        if unsafe:
            supplied_hash = hashlib.sha256((csrf_token or "").encode()).hexdigest()
            if not hmac.compare_digest(supplied_hash, session.csrf_hash):
                raise AppError("csrf_failed", "CSRF token is invalid", 403)
        assert cookie_token is not None
        self._repository.touch_session(cookie_token, now)
        return AuthenticatedUser(user.id, user.username)

    def logout(self, cookie_token: str | None) -> None:
        if cookie_token:
            self._repository.delete_session(cookie_token)

    def rotate_csrf(self, cookie_token: str) -> str:
        """Issue a fresh readable CSRF token for an authenticated session."""
        self.authenticate(cookie_token)
        csrf_token = secrets.token_urlsafe(32)
        self._repository.update_csrf(cookie_token, csrf_token)
        return csrf_token


def _invalid_credentials() -> AppError:
    return AppError("invalid_credentials", "Invalid username or password", 401)
