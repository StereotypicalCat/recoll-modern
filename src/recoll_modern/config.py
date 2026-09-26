"""Configuration loaded at the application's process boundary."""

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime configuration for the service."""

    document_root: Path
    state_root: Path
    recoll_config_dir: Path
    host: str
    port: int
    root_path: str
    trusted_proxies: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    inline_text_limit: int
    inline_text_limit_max: int
    session_lifetime_hours: int

    @property
    def database_path(self) -> Path:
        """Return the SQLite database location inside the configured state root."""
        return self.state_root / "recoll-modern.sqlite3"

    @property
    def membership_map_path(self) -> Path:
        """Return the generated Recoll membership-map location."""
        return self.state_root / "membership.map"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "Settings":
        """Build settings from an environment mapping."""
        root_path = environ.get("RECOLL_MODERN_ROOT_PATH", "/")
        if not root_path.startswith("/") or (root_path != "/" and root_path.endswith("/")):
            raise ValueError("mount prefix must start with / and have no trailing slash")

        text_max = int(environ.get("RECOLL_MODERN_INLINE_TEXT_LIMIT_MAX", "100000"))
        text_default = int(environ.get("RECOLL_MODERN_INLINE_TEXT_LIMIT", "20000"))
        if not 0 < text_default <= text_max:
            raise ValueError("inline text limit must be positive and no greater than its maximum")

        session_hours = int(environ.get("RECOLL_MODERN_SESSION_HOURS", "12"))
        if session_hours <= 0:
            raise ValueError("session lifetime must be positive")

        proxy_text = environ.get("RECOLL_MODERN_TRUSTED_PROXIES", "")
        proxies = tuple(
            ipaddress.ip_network(value.strip(), strict=False)
            for value in proxy_text.split(",")
            if value.strip()
        )

        return cls(
            document_root=Path(environ.get("RECOLL_MODERN_DOCUMENT_ROOT", "/documents")).resolve(),
            state_root=Path(
                environ.get("RECOLL_MODERN_STATE_ROOT", "/var/lib/recoll-modern")
            ).resolve(),
            recoll_config_dir=Path(
                environ.get("RECOLL_MODERN_RECOLL_CONFIG_DIR", "/etc/recoll-modern")
            ).resolve(),
            host=environ.get("RECOLL_MODERN_HOST", "0.0.0.0"),
            port=int(environ.get("RECOLL_MODERN_PORT", "8000")),
            root_path=root_path,
            trusted_proxies=proxies,
            inline_text_limit=text_default,
            inline_text_limit_max=text_max,
            session_lifetime_hours=session_hours,
        )
