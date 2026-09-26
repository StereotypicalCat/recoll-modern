"""Complete extracted text and safe original-file responses."""

import mimetypes
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from recoll_modern.api.dependencies import require_user
from recoll_modern.domain.errors import AppError
from recoll_modern.engine.protocol import EngineUnavailable

router = APIRouter()
SAFE_INLINE_TYPES = frozenset({
    "text/plain", "application/pdf", "image/png", "image/jpeg", "image/gif",
    "audio/mpeg", "audio/ogg", "video/mp4",
})


def _path(request: Request, document_hash: str) -> Path:
    document = request.app.state.documents.get(document_hash)
    if document is None:
        raise AppError("document_not_found", "Document was not found", 404)
    if document.canonical_path is None:
        raise AppError("document_missing", "Document is missing", 404)
    root = request.app.state.path_policy.root
    path = (root / document.canonical_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise AppError("document_missing", "Document is missing", 404)
    return cast(Path, path)


@router.get("/documents/{document_hash}/text", name="document_text")
def document_text(document_hash: str, request: Request) -> dict[str, str]:
    require_user(request)
    path = _path(request, document_hash)
    try:
        return {"text": request.app.state.engine.extracted_text(str(path))}
    except EngineUnavailable:
        raise AppError("engine_unavailable", "Search engine is unavailable", 503) from None


@router.get("/documents/{document_hash}/file", name="document_file")
def document_file(document_hash: str, request: Request) -> FileResponse:
    require_user(request)
    path = _path(request, document_hash)
    filename = path.name.replace("\r", "_").replace("\n", "_").replace('"', "_")
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(
        path, media_type=media_type, filename=filename,
        content_disposition_type="inline" if media_type in SAFE_INLINE_TYPES else "attachment",
    )
