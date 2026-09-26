import hashlib
from pathlib import Path

import pytest

from recoll_modern.domain.auth import AuthService
from recoll_modern.domain.errors import AppError
from recoll_modern.storage.auth import SQLiteAuthRepository
from recoll_modern.storage.database import Database


def test_database_stores_only_token_hashes(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    repository = SQLiteAuthRepository(database)
    auth = AuthService(repository)
    auth.seed_initial_admin("admin", "correct horse battery staple")
    credentials = auth.login("admin", "correct horse battery staple")
    assert repository.get_session(credentials.cookie_token) is not None
    with database.connect() as connection:
        row = connection.execute("SELECT token_hash, csrf_hash FROM sessions").fetchone()
    assert row is not None
    assert row["token_hash"] == hashlib.sha256(credentials.cookie_token.encode()).hexdigest()
    assert row["csrf_hash"] == hashlib.sha256(credentials.csrf_token.encode()).hexdigest()
    database_bytes = database.path.read_bytes()
    assert credentials.cookie_token.encode() not in database_bytes
    assert credentials.csrf_token.encode() not in database_bytes


def test_disabled_user_session_is_rejected(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    repository = SQLiteAuthRepository(database)
    auth = AuthService(repository)
    auth.seed_initial_admin("admin", "correct horse battery staple")
    credentials = auth.login("admin", "correct horse battery staple")
    user = repository.get_user_by_name("admin")
    assert user is not None
    repository.disable_user(user.id)
    with pytest.raises(AppError) as caught:
        auth.authenticate(credentials.cookie_token)
    assert caught.value.code == "unauthenticated"


def test_cleanup_removes_expired_sessions(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    database.migrate()
    repository = SQLiteAuthRepository(database)
    auth = AuthService(repository)
    auth.seed_initial_admin("admin", "correct horse battery staple")
    credentials = auth.login("admin", "correct horse battery staple")
    assert repository.cleanup_expired(credentials.expires_at) == 1
    assert repository.get_session(credentials.cookie_token) is None
