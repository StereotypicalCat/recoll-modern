"""Read-only single-directory browsing beneath the configured document root."""

import os
from pathlib import Path

from fastapi import APIRouter, Request

from recoll_modern.api.dependencies import require_user
from recoll_modern.domain.errors import AppError
from recoll_modern.indexing.paths import PathPolicyError

router = APIRouter()


@router.get("/files")
def list_files(request: Request, path: str = "") -> dict[str, object]:
    require_user(request)
    policy = request.app.state.path_policy
    try:
        directory = policy.root if path == "" else policy.resolve_directory(path)
    except PathPolicyError:
        raise AppError("path_outside_root", "Path is outside document root", 422) from None
    if not directory.is_dir():
        raise AppError("path_not_found", "Path was not found", 404)
    items: list[dict[str, object]] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                candidate = Path(entry.path)
                if entry.is_symlink() and not candidate.resolve().is_relative_to(policy.root):
                    continue
                stat = entry.stat(follow_symlinks=False)
                relative = candidate.relative_to(policy.root).as_posix()
                items.append({
                    "name": entry.name,
                    "path": relative,
                    "kind": "directory" if entry.is_dir(follow_symlinks=False) else "file",
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                })
    except OSError:
        raise AppError("path_not_found", "Path was not found", 404) from None
    return {"path": path, "items": sorted(items, key=lambda item: str(item["name"]))}
