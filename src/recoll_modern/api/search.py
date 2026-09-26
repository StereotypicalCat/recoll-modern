"""Authenticated, explicitly scoped search endpoint."""

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder

from recoll_modern.api.dependencies import require_user
from recoll_modern.domain.search import SearchInput

router = APIRouter()


@router.get("/search")
def search(request: Request, q: str = "", limit: int = 20, offset: int = 0,
           text_limit: int | None = None) -> dict[str, object]:
    require_user(request)
    collections = tuple(request.query_params.getlist("collections"))
    fields = (
        tuple(request.query_params.getlist("fields"))
        if "fields" in request.query_params else None
    )
    for collection_id in dict.fromkeys(collections):
        request.app.state.collections.get(collection_id)
    settings = request.app.state.settings
    result = request.app.state.search.search(SearchInput(
        q, collections, fields, limit, offset,
        settings.inline_text_limit if text_limit is None else text_limit,
    ))
    for hit in result.hits:
        if fields is not None and "links" in fields:
            document_id = str(hit["document_id"])
            hit["links"] = {
                "text": str(request.url_for("document_text", document_hash=document_id)),
                "file": str(request.url_for("document_file", document_hash=document_id)),
            }
    return {"hits": jsonable_encoder(result.hits), "total": result.total,
            "total_is_approximate": result.total_is_approximate}
