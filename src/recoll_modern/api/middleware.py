"""Mount-prefix routing and conservative proxy-header handling."""

import ipaddress

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from recoll_modern.config import Settings
from recoll_modern.domain.errors import AppError


class PrefixMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        scope = dict(scope)
        prefix = self.settings.root_path
        client = scope.get("client")
        try:
            trusted = client is not None and any(
                ipaddress.ip_address(client[0]) in network
                for network in self.settings.trusted_proxies
            )
        except ValueError:
            trusted = False
        if trusted:
            headers = {name.lower(): value for name, value in scope["headers"]}
            forwarded_prefix = headers.get(b"x-forwarded-prefix", b"").decode("ascii", "ignore")
            if (
                forwarded_prefix.startswith("/")
                and not forwarded_prefix.endswith("/")
                and ".." not in forwarded_prefix
            ):
                prefix = forwarded_prefix
            scheme = headers.get(b"x-forwarded-proto", b"").decode("ascii", "ignore")
            if scheme in ("http", "https"):
                scope["scheme"] = scheme
            host = headers.get(b"x-forwarded-host", b"")
            if host and b"/" not in host and b"\r" not in host and b"\n" not in host:
                scope["headers"] = [
                    (name, value) for name, value in scope["headers"] if name.lower() != b"host"
                ] + [(b"host", host)]
        path = scope["path"]
        if prefix != "/":
            if path != prefix and not path.startswith(prefix + "/") and not trusted:
                response = JSONResponse(
                    {"error": {"code": "path_not_found", "message": "Path was not found",
                               "details": {}}}, status_code=404
                )
                await response(scope, receive, send)
                return
            if path == prefix or path.startswith(prefix + "/"):
                scope["path"] = path[len(prefix):] or "/"
            scope["root_path"] = prefix
        if scope["type"] == "http" and scope["path"] in (
            "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"
        ):
            request = Request(scope)
            try:
                request.app.state.auth.authenticate(
                    request.cookies.get("recoll_modern_session"), unsafe=False
                )
            except AppError as error:
                response = JSONResponse(
                    {"error": {"code": error.code, "message": error.message,
                               "details": dict(error.details)}}, status_code=error.status
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
