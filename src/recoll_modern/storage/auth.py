"""SQLite users and hashed session-token persistence."""

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime

from recoll_modern.domain.auth import AuthUser, SessionRecord, normalize_username
from recoll_modern.storage.database import Database


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SQLiteAuthRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def user_count(self) -> int:
        with self._database.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_user(self, username: str, password_hash: str) -> AuthUser:
        display, key = normalize_username(username)
        now = datetime.now(UTC).isoformat()
        while True:
            user_id = f"u{secrets.token_hex(16)}"
            try:
                with self._database.transaction() as connection:
                    connection.execute(
                        "INSERT INTO users "
                        "(id, username, username_key, password_hash, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (user_id, display, key, password_hash, now),
                    )
            except sqlite3.IntegrityError as error:
                if "users.id" in str(error):
                    continue
                raise
            return AuthUser(user_id, display, key, password_hash, None)

    def get_user_by_name(self, username: str) -> AuthUser | None:
        try:
            _, key = normalize_username(username)
        except ValueError:
            return None
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, username, username_key, password_hash, disabled_at "
                "FROM users WHERE username_key = ?",
                (key,),
            ).fetchone()
            return _user(row) if row is not None else None

    def get_user_by_id(self, user_id: str) -> AuthUser | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, username, username_key, password_hash, disabled_at "
                "FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            return _user(row) if row is not None else None

    def disable_user(self, user_id: str) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE users SET disabled_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), user_id),
            )

    def create_session(
        self,
        cookie_token: str,
        csrf_token: str,
        user_id: str,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO sessions "
                "(token_hash, csrf_hash, user_id, expires_at, created_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _hash_token(cookie_token), _hash_token(csrf_token), user_id,
                    expires_at.isoformat(), now.isoformat(), now.isoformat(),
                ),
            )

    def get_session(self, cookie_token: str) -> SessionRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT token_hash, csrf_hash, user_id, expires_at "
                "FROM sessions WHERE token_hash = ?",
                (_hash_token(cookie_token),),
            ).fetchone()
            if row is None:
                return None
            return SessionRecord(
                str(row["token_hash"]), str(row["csrf_hash"]), str(row["user_id"]),
                datetime.fromisoformat(str(row["expires_at"])),
            )

    def delete_session(self, cookie_token: str) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (_hash_token(cookie_token),)
            )

    def touch_session(self, cookie_token: str, now: datetime) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                (now.isoformat(), _hash_token(cookie_token)),
            )

    def update_csrf(self, cookie_token: str, csrf_token: str) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE sessions SET csrf_hash = ? WHERE token_hash = ?",
                (_hash_token(csrf_token), _hash_token(cookie_token)),
            )

    def cleanup_expired(self, now: datetime) -> int:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),)
            )
            return cursor.rowcount


def _user(row: sqlite3.Row) -> AuthUser:
    return AuthUser(
        id=str(row["id"]),
        username=str(row["username"]),
        username_key=str(row["username_key"]),
        password_hash=str(row["password_hash"]),
        disabled_at=(
            datetime.fromisoformat(str(row["disabled_at"]))
            if row["disabled_at"] is not None else None
        ),
    )
