"""Login, session refresh, and logout routes."""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from recoll_modern.api.dependencies import COOKIE_NAME, auth_service, require_user
from recoll_modern.domain.errors import AppError

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, str]:
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if origin is not None and origin != expected:
        raise AppError("csrf_failed", "Origin is invalid", 403)
    credentials = auth_service(request).login(body.username, body.password)
    settings = request.app.state.settings
    response.set_cookie(
        COOKIE_NAME, credentials.cookie_token, httponly=True, samesite="lax",
        secure=not settings.development_mode,
        path=settings.root_path,
        expires=credentials.expires_at,
    )
    return {"csrf_token": credentials.csrf_token}


@router.get("/auth/session")
def session(request: Request) -> dict[str, str]:
    user = require_user(request)
    token = request.cookies[COOKIE_NAME]
    return {"username": user.username, "csrf_token": auth_service(request).rotate_csrf(token)}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    require_user(request)
    auth_service(request).logout(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path=request.app.state.settings.root_path)
