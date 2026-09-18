"""Console entry point for recoll-modern."""

import uvicorn

from recoll_modern.app import create_app
from recoll_modern.config import Settings


def main() -> None:
    """Load process configuration and start the HTTP server."""
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
