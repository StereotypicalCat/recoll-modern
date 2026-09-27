"""Collection metadata HTTP routes."""

from dataclasses import asdict
from typing import cast

from fastapi import APIRouter, Request, Response
from fastapi.encoders import jsonable_encoder

from recoll_modern.api.dependencies import require_user
from recoll_modern.api.schemas import CollectionCreateBody, CollectionPatchBody, validated_sources
from recoll_modern.domain.errors import AppError
from recoll_modern.domain.models import UNSET, CollectionCreate, CollectionPatch

router = APIRouter()


@router.get("/collections")
def list_collections(request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    require_user(request)
    if not 1 <= limit <= 200 or offset < 0:
        raise AppError("validation_failed", "Invalid pagination", 422)
    collections, total = request.app.state.collections.list(limit, offset)
    return {"items": jsonable_encoder([asdict(item) for item in collections]), "total": total}


@router.get("/collections/{collection_id}")
def get_collection(request: Request, collection_id: str) -> dict[str, object]:
    require_user(request)
    return cast(
        dict[str, object],
        jsonable_encoder(asdict(request.app.state.collections.get(collection_id))),
    )


@router.post("/collections")
def create_collection(
    body: CollectionCreateBody, request: Request, response: Response
) -> dict[str, object]:
    require_user(request)
    sources = (
        validated_sources(request.app.state.path_policy, body.sources)
        if body.sources else []
    )
    collection = request.app.state.collections.create(
        CollectionCreate(body.name, body.description)
    )
    payload = jsonable_encoder(asdict(collection))
    if sources:
        job = request.app.state.jobs.enqueue(
            "membership_add",
            {"version": 1, "collection_id": collection.id, "sources": sources},
            body.fail_on_file_error,
        )
        request.app.state.worker.notify()
        response.status_code = 202
        return {"collection": payload, "job_id": job.id}
    response.status_code = 201
    return cast(dict[str, object], payload)


@router.patch("/collections/{collection_id}")
def patch_collection(
    body: CollectionPatchBody, request: Request, collection_id: str
) -> dict[str, object]:
    require_user(request)
    description = body.description if "description" in body.model_fields_set else UNSET
    changed = request.app.state.collections.patch(
        collection_id, CollectionPatch(body.name, description)
    )
    return cast(dict[str, object], jsonable_encoder(asdict(changed)))


@router.delete("/collections/{collection_id}", status_code=202)
def delete_collection(
    request: Request, collection_id: str, confirmation: str = ""
) -> dict[str, str]:
    require_user(request)
    collection = request.app.state.collections.get(collection_id)
    if confirmation != collection.name:
        raise AppError("confirmation_required", "Collection name confirmation is required", 409)
    job = request.app.state.collection_repository.delete_with_cleanup(
        collection_id, request.app.state.jobs
    )
    request.app.state.worker.notify()
    return {"job_id": job.id}
