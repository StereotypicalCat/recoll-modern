"""Small HTTP request bodies for collection metadata."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from recoll_modern.domain.errors import AppError
from recoll_modern.indexing.paths import PathPolicy, PathPolicyError


class FileSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["file"]
    path: str


class DirectorySource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["directory"]
    path: str
    mode: Literal["snapshot", "persistent"]
    excluded_directories: list[str] = Field(default_factory=list)


type SourceBody = Annotated[FileSource | DirectorySource, Field(discriminator="type")]


class MembershipBody(BaseModel):
    sources: list[SourceBody]
    fail_on_file_error: bool = False


class RulePatchBody(BaseModel):
    excluded_directories: list[str]


class ReindexBody(BaseModel):
    paths: list[str] | None = None
    collections: list[str] | None = None
    fail_on_file_error: bool = False


class CollectionCreateBody(BaseModel):
    name: str
    description: str | None = None
    sources: list[SourceBody] | None = None
    fail_on_file_error: bool = False


class CollectionPatchBody(BaseModel):
    name: str | None = None
    description: str | None = None


def validated_sources(
    policy: PathPolicy, sources: list[FileSource | DirectorySource]
) -> list[dict[str, object]]:
    """Normalize sources and reject invalid or repeated root-relative selections."""
    result: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        try:
            path = policy.normalize(source.path)
            if source.type == "file":
                policy.resolve_file(path)
                item: dict[str, object] = {"type": "file", "path": path}
            else:
                policy.resolve_directory(path)
                excluded = [policy.normalize(value) for value in source.excluded_directories]
                if any(not value.startswith(path + "/") for value in excluded):
                    raise PathPolicyError("invalid_source")
                item = {
                    "type": "directory", "path": path, "mode": source.mode,
                    "excluded_directories": excluded,
                }
        except PathPolicyError:
            raise AppError("invalid_source", "Membership source is invalid", 422) from None
        key = (source.type, path)
        if key in seen:
            raise AppError("invalid_source", "Membership source is duplicated", 422)
        seen.add(key)
        result.append(item)
    return result
