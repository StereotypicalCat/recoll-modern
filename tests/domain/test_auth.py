from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from recoll_modern.domain.auth import AuthService
from recoll_modern.domain.errors import AppError
from recoll_modern.storage.auth import SQLiteAuthRepository
from recoll_modern.storage.database import Database

PASSWORD = "correct horse battery staple"


def _auth(tmp_path: Path, now: datetime | None = None) -> tuple[AuthService, SQLiteAuthRepository]:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    repository = SQLiteAuthRepository(database)
    def clock() -> datetime:
        return now or datetime.now(UTC)

    return AuthService(repository, now=clock), repository


def test_passwords_are_argon2_hashes(tmp_path: Path) -> None:
    auth, repository = _auth(tmp_path)
    auth.seed_initial_admin("admin", PASSWORD)
    stored = repository.get_user_by_name("admin")
    assert stored is not None
    assert stored.password_hash.startswith("$argon2id$")
    assert "correct horse" not in stored.password_hash


def test_first_boot_without_credentials_refuses_startup(tmp_path: Path) -> None:
    auth, _ = _auth(tmp_path)
    with pytest.raises(AppError, match="initial administrator"):
        auth.seed_initial_admin(None, None)


def test_seed_is_idempotent_when_user_exists(tmp_path: Path) -> None:
    auth, repository = _auth(tmp_path)
    auth.seed_initial_admin("admin", PASSWORD)
    auth.seed_initial_admin(None, None)
    assert repository.user_count() == 1


def test_login_is_case_folded_and_invalid_credentials_are_generic(tmp_path: Path) -> None:
    auth, _ = _auth(tmp_path)
    auth.seed_initial_admin("Straße", PASSWORD)
    credentials = auth.login("STRASSE", PASSWORD)
    assert auth.authenticate(credentials.cookie_token).username == "Straße"
    with pytest.raises(AppError) as caught:
        auth.login("unknown", "wrong")
    assert caught.value.code == "invalid_credentials"


def test_csrf_mismatch_and_logout(tmp_path: Path) -> None:
    auth, _ = _auth(tmp_path)
    auth.seed_initial_admin("admin", PASSWORD)
    credentials = auth.login("admin", PASSWORD)
    with pytest.raises(AppError) as caught:
        auth.authenticate(credentials.cookie_token, csrf_token="wrong", unsafe=True)
    assert caught.value.code == "csrf_failed"
    assert auth.authenticate(
        credentials.cookie_token, csrf_token=credentials.csrf_token, unsafe=True
    ).username == "admin"
    auth.logout(credentials.cookie_token)
    with pytest.raises(AppError) as caught:
        auth.authenticate(credentials.cookie_token)
    assert caught.value.code == "unauthenticated"


def test_expired_session_is_refused(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    repository = SQLiteAuthRepository(database)
    clock = [now]
    auth = AuthService(repository, now=lambda: clock[0], lifetime=timedelta(hours=1))
    auth.seed_initial_admin("admin", PASSWORD)
    credentials = auth.login("admin", PASSWORD)
    clock[0] = now + timedelta(hours=2)
    with pytest.raises(AppError) as caught:
        auth.authenticate(credentials.cookie_token)
    assert caught.value.code == "unauthenticated"
