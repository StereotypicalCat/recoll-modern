"""Complete extracted text and safe original-file responses."""

import mimetypes
import os
import re
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, cast
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from recoll_modern.api.dependencies import require_user
from recoll_modern.domain.errors import AppError
from recoll_modern.engine.protocol import EngineUnavailable

router = APIRouter()
SAFE_INLINE_TYPES = frozenset({
    "text/plain", "application/pdf", "image/png", "image/jpeg", "image/gif",
    "audio/mpeg", "audio/ogg", "video/mp4",
})
_RANGE = re.compile(r"bytes=(\d*)-(\d*)\Z")


def _path(request: Request, document_hash: str) -> Path:
    document = request.app.state.documents.get(document_hash)
    if document is None:
        raise AppError("document_not_found", "Document was not found", 404)
    if document.canonical_path is None:
        raise AppError("document_missing", "Document is missing", 410)
    root = request.app.state.path_policy.root
    path = (root / document.canonical_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise AppError("document_missing", "Document is missing", 410)
    return cast(Path, path)


def open_contained_file(root: Path, relative_path: str) -> BinaryIO:
    """Open beneath root before constructing a response; pin the checked inode."""
    root = root.resolve()
    resolved = (root / relative_path).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("file is outside document root")
    parts = resolved.relative_to(root).parts
    if not parts:
        raise ValueError("document path is not a file")
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd
            )
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            os.close(file_fd)
            raise ValueError("document path is not a regular file")
        return os.fdopen(file_fd, "rb")
    finally:
        os.close(directory_fd)


def _byte_range(header: str | None, size: int) -> tuple[int, int, bool] | None:
    if header is None:
        return (0, size - 1, False)
    match = _RANGE.fullmatch(header.strip())
    if match is None or size == 0:
        return None
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if not start_text:
        suffix = int(end_text)
        if suffix <= 0:
            return None
        return (max(size - suffix, 0), size - 1, True)
    start = int(start_text)
    end = min(int(end_text), size - 1) if end_text else size - 1
    if start >= size or end < start:
        return None
    return (start, end, True)


def _chunks(stream: BinaryIO, start: int, length: int) -> Iterator[bytes]:
    try:
        stream.seek(start)
        remaining = length
        while remaining:
            data = stream.read(min(64 * 1024, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data
    finally:
        stream.close()


@router.get("/documents/{document_hash}/text", name="document_text")
def document_text(document_hash: str, request: Request) -> dict[str, str]:
    require_user(request)
    path = _path(request, document_hash)
    try:
        return {"text": request.app.state.engine.extracted_text(str(path))}
    except EngineUnavailable:
        raise AppError("engine_unavailable", "Search engine is unavailable", 503) from None


@router.get("/documents/{document_hash}/file", name="document_file")
def document_file(document_hash: str, request: Request) -> Response:
    require_user(request)
    document = request.app.state.documents.get(document_hash)
    if document is None:
        raise AppError("document_not_found", "Document was not found", 404)
    if document.canonical_path is None:
        raise AppError("document_missing", "Document is missing", 410)
    try:
        stream = open_contained_file(
            request.app.state.path_policy.root, document.canonical_path
        )
    except (OSError, ValueError):
        raise AppError("document_missing", "Document is missing", 410) from None
    filename = Path(document.canonical_path).name
    filename = filename.replace("\r", "_").replace("\n", "_").replace('"', "_")
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    disposition = "inline" if media_type in SAFE_INLINE_TYPES else "attachment"
    quoted = quote(filename)
    content_disposition = (
        f'{disposition}; filename="{filename}"'
        if quoted == filename else f"{disposition}; filename*=utf-8''{quoted}"
    )
    size = os.fstat(stream.fileno()).st_size
    selected = _byte_range(request.headers.get("range"), size)
    if selected is None:
        stream.close()
        return Response(status_code=416, headers={
            "Accept-Ranges": "bytes", "Content-Range": f"bytes */{size}",
        })
    start, end, partial = selected
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Disposition": content_disposition,
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _chunks(stream, start, end - start + 1),
        status_code=206 if partial else 200, media_type=media_type, headers=headers,
    )
