"""FastAPI application factory."""

from fastapi import FastAPI

from recoll_modern.config import Settings


def create_app(settings: Settings) -> FastAPI:
    """Create the HTTP application with its configured mount prefix."""
    app = FastAPI(root_path=settings.root_path)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "starting"}

    return app
