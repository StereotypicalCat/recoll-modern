"""Collection domain data structures."""

from dataclasses import dataclass
from datetime import datetime


class _Unset:
    """Distinguish an omitted patch field from an explicit null value."""


UNSET = _Unset()


@dataclass(frozen=True, slots=True)
class Collection:
    """A persisted collection with a server-generated immutable identity."""

    id: str
    name: str
    description: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CollectionCreate:
    """Values accepted when creating a collection."""

    name: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionPatch:
    """Values accepted when changing collection metadata."""

    name: str | None = None
    description: str | None | _Unset = UNSET
