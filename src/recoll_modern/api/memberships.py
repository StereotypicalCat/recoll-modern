"""Collection membership, document provenance, and directory-rule routes."""

from dataclasses import asdict
from typing import cast

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder

from recoll_modern.api.dependencies import require_user
from recoll_modern.api.schemas import (
    DirectorySource,
    MembershipBody,
    RulePatchBody,
    validated_sources,
)
from recoll_modern.domain.errors import AppError
from recoll_modern.storage.membership import DirectoryRule

router = APIRouter()


def _rule(request: Request, collection_id: str, rule_id: str) -> DirectoryRule:
    rule = cast(DirectoryRule | None, request.app.state.memberships.get_rule(rule_id))
    if rule is None or rule.collection_id != collection_id:
        raise AppError("directory_rule_not_found", "Directory rule was not found", 404)
    return rule


@router.post("/collections/{collection_id}/memberships", status_code=202)
def add_memberships(
    collection_id: str, body: MembershipBody, request: Request
) -> dict[str, object]:
    require_user(request)
    request.app.state.collections.get(collection_id)
    if not body.sources:
        raise AppError("invalid_source", "At least one source is required", 422)
    sources = validated_sources(request.app.state.path_policy, body.sources)
    job = request.app.state.jobs.enqueue(
        "membership_add",
        {"version": 1, "collection_id": collection_id, "sources": sources},
        body.fail_on_file_error,
    )
    request.app.state.worker.notify()
    return {"job": jsonable_encoder(asdict(job))}


@router.get("/collections/{collection_id}/documents")
def list_documents(
    collection_id: str, request: Request, limit: int = 50, offset: int = 0
) -> dict[str, object]:
    require_user(request)
    request.app.state.collections.get(collection_id)
    if not 1 <= limit <= 200 or offset < 0:
        raise AppError("validation_failed", "Invalid pagination", 422)
    items, total = request.app.state.memberships.list_documents(collection_id, limit, offset)
    return {"items": items, "total": total}


@router.delete("/collections/{collection_id}/documents/{document_hash}", status_code=202)
def remove_document(
    collection_id: str, document_hash: str, request: Request
) -> dict[str, object]:
    require_user(request)
    request.app.state.collections.get(collection_id)
    if request.app.state.documents.get(document_hash) is None:
        raise AppError("document_not_found", "Document was not found", 404)
    job = request.app.state.jobs.enqueue(
        "membership_remove",
        {"version": 1, "collection_id": collection_id, "document_hash": document_hash},
        False,
    )
    request.app.state.worker.notify()
    return {"job": jsonable_encoder(asdict(job))}


@router.get("/collections/{collection_id}/directory-rules")
def list_rules(collection_id: str, request: Request) -> dict[str, object]:
    require_user(request)
    request.app.state.collections.get(collection_id)
    rules = [
        asdict(rule) for rule in request.app.state.memberships.list_rules()
        if rule.collection_id == collection_id
    ]
    return {"items": rules, "total": len(rules)}


@router.patch("/collections/{collection_id}/directory-rules/{rule_id}", status_code=202)
def patch_rule(
    collection_id: str, rule_id: str, body: RulePatchBody, request: Request
) -> dict[str, object]:
    require_user(request)
    rule = _rule(request, collection_id, rule_id)
    validated = validated_sources(request.app.state.path_policy, [DirectorySource(
        type="directory", path=rule.relative_path, mode="persistent",
        excluded_directories=body.excluded_directories,
    )])
    job = request.app.state.jobs.enqueue(
        "rule_patch",
        {"version": 1, "rule_id": rule_id,
         "excluded_directories": validated[0]["excluded_directories"]},
        False,
    )
    request.app.state.worker.notify()
    return {"job": jsonable_encoder(asdict(job))}


@router.delete("/collections/{collection_id}/directory-rules/{rule_id}", status_code=202)
def delete_rule(collection_id: str, rule_id: str, request: Request) -> dict[str, object]:
    require_user(request)
    _rule(request, collection_id, rule_id)
    job = request.app.state.jobs.enqueue(
        "rule_delete", {"version": 1, "rule_id": rule_id}, False
    )
    request.app.state.worker.notify()
    return {"job": jsonable_encoder(asdict(job))}
