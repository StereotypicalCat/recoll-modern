"""Atomic binary export of canonical-path collection membership."""

import os
import re
import struct
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

from recoll_modern.storage.membership import MembershipRepository

_COLLECTION_ID = re.compile(r"c[0-9a-f]{10}\Z")
_MAX_FIELD = 16 * 1024 * 1024


class MembershipRows(Protocol):
    def membership_map_rows(self) -> Iterable[tuple[str, Sequence[str]]]: ...


class MembershipMapRows:
    """Bind a repository's root-relative canonical paths to its document root."""

    def __init__(self, repository: MembershipRepository, document_root: Path) -> None:
        self._repository = repository
        self._document_root = document_root

    def membership_map_rows(self) -> Iterable[tuple[str, Sequence[str]]]:
        return self._repository.membership_map_rows(self._document_root)


def export_membership_map(repository: MembershipRows, destination: Path) -> None:
    """Replace a complete map only after its bytes have reached the filesystem."""
    rows = sorted(repository.membership_map_rows(), key=lambda row: row[0])
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(b"RCM1")
            for path, collection_ids in rows:
                if not path.startswith("/"):
                    raise ValueError("membership map paths must be absolute")
                ids = sorted(set(collection_ids))
                if any(_COLLECTION_ID.fullmatch(item) is None for item in ids):
                    raise ValueError("membership map contains an invalid collection ID")
                path_bytes = path.encode("utf-8")
                value_bytes = " ".join(ids).encode("ascii")
                if len(path_bytes) > _MAX_FIELD or len(value_bytes) > _MAX_FIELD:
                    raise ValueError("membership map field exceeds 16 MiB")
                stream.write(struct.pack(">I", len(path_bytes)))
                stream.write(path_bytes)
                stream.write(struct.pack(">I", len(value_bytes)))
                stream.write(value_bytes)
            stream.flush()
            os.fchmod(stream.fileno(), 0o640)
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
        directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
