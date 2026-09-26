"""Types shared by fake and Recoll-backed search engines."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    collection_ids: tuple[str, ...]
    limit: int
    offset: int
    fetch_text: bool


@dataclass(frozen=True, slots=True)
class EngineHit:
    path: str
    title: str
    author: str | None
    mime_type: str | None
    size: int | None
    date: datetime | None
    score: float
    collection_ids: tuple[str, ...]
    snippets: tuple[str, ...]
    text: str | None = None


@dataclass(frozen=True, slots=True)
class EnginePage:
    hits: tuple[EngineHit, ...]
    total: int
    total_is_approximate: bool = True


@dataclass(frozen=True, slots=True)
class EngineHealth:
    available: bool
    message: str | None = None


class EngineUnavailable(Exception):
    """Recoll cannot serve a request; details stay in server logs."""


class Engine(Protocol):
    def health(self) -> EngineHealth: ...

    def search(self, request: SearchRequest) -> EnginePage: ...

    def extracted_text(self, path: str) -> str: ...

    def force_reindex(self, paths: Sequence[str]) -> None: ...
