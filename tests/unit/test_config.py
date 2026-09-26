from pathlib import Path

import pytest

from recoll_modern.config import Settings


def test_settings_are_rooted_in_configured_state(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "RECOLL_MODERN_DOCUMENT_ROOT": str(tmp_path / "docs"),
            "RECOLL_MODERN_STATE_ROOT": str(tmp_path / "state"),
            "RECOLL_MODERN_HOST": "127.0.0.1",
            "RECOLL_MODERN_PORT": "9123",
            "RECOLL_MODERN_ROOT_PATH": "/recoll",
        }
    )

    assert settings.database_path == tmp_path / "state" / "recoll-modern.sqlite3"
    assert settings.membership_map_path == tmp_path / "state" / "membership.map"
    assert (settings.host, settings.port, settings.root_path) == ("127.0.0.1", 9123, "/recoll")


def test_root_path_rejects_trailing_slash() -> None:
    with pytest.raises(ValueError, match="mount prefix"):
        Settings.from_env({"RECOLL_MODERN_ROOT_PATH": "/recoll/"})


def test_session_lifetime_is_configurable() -> None:
    settings = Settings.from_env({"RECOLL_MODERN_SESSION_HOURS": "6"})
    assert settings.session_lifetime_hours == 6
    with pytest.raises(ValueError, match="session lifetime"):
        Settings.from_env({"RECOLL_MODERN_SESSION_HOURS": "0"})
