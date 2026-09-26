"""Root-relative path validation for document sources."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from unicodedata import normalize


@dataclass(frozen=True, slots=True)
class PathPolicyError(Exception):
    code: str

    def __str__(self) -> str:
        return self.code


class PathPolicy:
    """Resolve document paths without allowing a source to escape the root."""

    def __init__(self, document_root: Path) -> None:
        self.root = document_root.resolve()

    def normalize(self, path: str) -> str:
        if not path or "\x00" in path or "\\" in path:
            raise PathPolicyError("invalid_source")
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or any(part in (".", "..") for part in path.split("/")):
            raise PathPolicyError("invalid_source")
        return normalize("NFC", candidate.as_posix())

    def _resolve(self, path: str) -> Path:
        relative = self.normalize(path)
        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(self.root):
            raise PathPolicyError("file_outside_root")
        return resolved

    def resolve_file(self, path: str) -> Path:
        return self._resolve(path)

    def resolve_directory(self, path: str) -> Path:
        relative = self.normalize(path)
        current = self.root
        for part in relative.split("/"):
            current /= part
            if current.is_symlink():
                raise PathPolicyError("invalid_source")
        return self._resolve(relative)
