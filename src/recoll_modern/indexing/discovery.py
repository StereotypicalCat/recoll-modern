"""Read-only source discovery and stable content hashing."""

import hashlib
import os
import stat
from dataclasses import dataclass
from os import stat_result
from pathlib import Path
from typing import Literal

from recoll_modern.indexing.paths import PathPolicy, PathPolicyError


@dataclass(frozen=True, slots=True)
class Source:
    type: Literal["file", "directory"]
    path: str
    mode: Literal["snapshot", "persistent"] | None = None
    excluded_directories: tuple[str, ...] = ()

    @classmethod
    def file(cls, path: str) -> "Source":
        return cls("file", path)

    @classmethod
    def directory(
        cls,
        path: str,
        mode: Literal["snapshot", "persistent"],
        excluded_directories: tuple[str, ...] = (),
    ) -> "Source":
        return cls("directory", path, mode, excluded_directories)


@dataclass(frozen=True, slots=True)
class FileError:
    relative_path: str
    code: str


@dataclass(frozen=True, slots=True)
class ObservedFile:
    relative_path: str
    content_hash: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class HashResult:
    content_hash: str | None = None
    byte_size: int | None = None
    code: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    files: tuple[ObservedFile, ...]
    errors: tuple[FileError, ...]

    @property
    def relative_paths(self) -> tuple[str, ...]:
        return tuple(file.relative_path for file in self.files)


def hash_file_stable(path: Path) -> HashResult:
    """Hash a file and reject a concurrent metadata change."""
    try:
        with open(
            path, "rb",
            opener=lambda name, flags: os.open(
                name, flags | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
            ),
        ) as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                return HashResult(code="file_hash_failed")
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            current = path.stat()
        def stamp(stat: stat_result) -> tuple[int, int, int, int]:
            return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

        if stamp(before) != stamp(after) or stamp(before) != stamp(current):
            return HashResult(code="file_changed_during_scan")
        return HashResult(digest.hexdigest(), before.st_size)
    except FileNotFoundError:
        return HashResult(code="file_vanished")
    except PermissionError:
        return HashResult(code="file_unreadable")
    except OSError:
        return HashResult(code="file_hash_failed")


def discover_sources(policy: PathPolicy, sources: list[Source]) -> DiscoveryReport:
    """Discover distinct root-relative files in stable order."""
    candidates: set[str] = set()
    errors: list[FileError] = []
    for source in sources:
        try:
            relative = policy.normalize(source.path)
            if source.type == "file":
                candidates.add(relative)
                continue
            if source.type != "directory" or source.mode not in ("snapshot", "persistent"):
                raise PathPolicyError("invalid_source")
            excluded = {policy.normalize(path) for path in source.excluded_directories}
            if any(not path.startswith(relative + "/") for path in excluded):
                raise PathPolicyError("invalid_source")
            directory = policy.resolve_directory(relative)
            if not directory.is_dir():
                raise FileNotFoundError
            _walk(policy, directory, relative, excluded, candidates, errors)
        except PathPolicyError as error:
            errors.append(FileError(source.path, error.code))
        except FileNotFoundError:
            errors.append(FileError(source.path, "file_vanished"))
        except PermissionError:
            errors.append(FileError(source.path, "file_unreadable"))
        except OSError:
            errors.append(FileError(source.path, "file_hash_failed"))
    files: list[ObservedFile] = []
    for relative in sorted(candidates):
        try:
            path = policy.resolve_file(relative)
        except PathPolicyError as error:
            errors.append(FileError(relative, error.code))
            continue
        result = hash_file_stable(path)
        if result.code is not None:
            errors.append(FileError(relative, result.code))
        elif result.content_hash is not None and result.byte_size is not None:
            files.append(ObservedFile(relative, result.content_hash, result.byte_size))
    return DiscoveryReport(tuple(files), tuple(errors))


def _walk(
    policy: PathPolicy,
    directory: Path,
    relative: str,
    excluded: set[str],
    candidates: set[str],
    errors: list[FileError],
) -> None:
    try:
        with os.scandir(directory) as entries:
            children = sorted(
                entries, key=lambda entry: policy.normalize(f"{relative}/{entry.name}")
            )
        for entry in children:
            child = policy.normalize(f"{relative}/{entry.name}")
            try:
                if entry.is_dir(follow_symlinks=False):
                    if child not in excluded:
                        _walk(policy, Path(entry.path), child, excluded, candidates, errors)
                elif entry.is_file(follow_symlinks=False) or (
                    entry.is_symlink() and not entry.is_dir(follow_symlinks=True)
                ):
                    candidates.add(child)
            except OSError:
                errors.append(FileError(child, "file_unreadable"))
    except FileNotFoundError:
        errors.append(FileError(relative, "file_vanished"))
    except PermissionError:
        errors.append(FileError(relative, "file_unreadable"))
