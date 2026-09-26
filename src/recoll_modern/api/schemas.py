"""Small HTTP request bodies for collection metadata."""

from pydantic import BaseModel


class CollectionCreateBody(BaseModel):
    name: str
    description: str | None = None
    sources: list[dict[str, object]] | None = None
    fail_on_file_error: bool = False


class CollectionPatchBody(BaseModel):
    name: str | None = None
    description: str | None = None
