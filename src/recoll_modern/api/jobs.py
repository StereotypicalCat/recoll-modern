"""Durable indexing-job HTTP resources."""

from dataclasses import asdict
from typing import cast

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder

from recoll_modern.api.dependencies import require_user
from recoll_modern.api.schemas import ReindexBody
from recoll_modern.domain.errors import AppError
from recoll_modern.domain.jobs import Job
from recoll_modern.indexing.paths import PathPolicyError

router = APIRouter()


def _job_payload(job: Job) -> dict[str, object]:
    return cast(dict[str, object], jsonable_encoder(asdict(job)))


@router.get("/jobs")
def list_jobs(request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    require_user(request)
    if not 1 <= limit <= 200 or offset < 0:
        raise AppError("validation_failed", "Invalid pagination", 422)
    jobs, total = request.app.state.jobs.list_jobs(limit, offset)
    return {"items": [_job_payload(job) for job in jobs], "total": total}


@router.post("/jobs/reindex", status_code=202)
def reindex(body: ReindexBody, request: Request) -> dict[str, object]:
    require_user(request)
    policy = request.app.state.path_policy
    paths: list[str] = []
    for path in body.paths or []:
        try:
            normalized = policy.normalize(path)
            policy.resolve_file(normalized)
        except PathPolicyError:
            raise AppError("invalid_source", "Reindex path is invalid", 422) from None
        paths.append(normalized)
    for collection_id in body.collections or []:
        request.app.state.collections.get(collection_id)
    job = request.app.state.jobs.enqueue(
        "reindex",
        {"version": 1, "paths": sorted(set(paths)),
         "collections": sorted(set(body.collections or []))},
        body.fail_on_file_error,
    )
    request.app.state.worker.notify()
    return {"job": _job_payload(job)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, object]:
    require_user(request)
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise AppError("job_not_found", "Job was not found", 404)
    errors = request.app.state.jobs.file_errors(job_id)
    return {"job": _job_payload(job), "file_errors": jsonable_encoder(errors)}


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, request: Request) -> dict[str, object]:
    require_user(request)
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise AppError("job_not_found", "Job was not found", 404)
    try:
        request.app.state.jobs.retry(job_id)
    except ValueError:
        raise AppError("job_not_retryable", "Job cannot be retried", 409) from None
    request.app.state.worker.notify()
    retried = request.app.state.jobs.get(job_id)
    assert retried is not None
    return {"job": _job_payload(retried)}
