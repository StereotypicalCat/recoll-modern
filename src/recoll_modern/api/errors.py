"""Stable JSON error envelopes for expected and unexpected failures."""

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from recoll_modern.domain.errors import AppError

_LOG = logging.getLogger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = "path_not_found" if error.status_code == 404 else "invalid_query"
        message = "Path was not found" if error.status_code == 404 else "Request is invalid"
        return JSONResponse(
            {"error": {"code": code, "message": message, "details": {}}},
            status_code=error.status_code,
        )

    @app.exception_handler(AppError)
    async def app_error(_request: Request, error: AppError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": error.code, "message": error.message,
                       "details": dict(error.details)}},
            status_code=error.status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "validation_failed", "message": "Request validation failed",
                       "details": {}}},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        request_id = secrets.token_hex(8)
        _LOG.exception("Unhandled request error %s", request_id, exc_info=error)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "Internal server error",
                       "details": {"request_id": request_id}}},
            status_code=500,
            headers={"X-Request-ID": request_id},
        )
