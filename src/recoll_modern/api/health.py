"""Public readiness probe."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
def health(request: Request) -> JSONResponse:
    status = request.app.state.engine.health()
    if not status.available:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})
