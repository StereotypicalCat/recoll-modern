"""Deterministic in-memory engine for contracts and application tests."""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from recoll_modern.engine.protocol import EngineHealth, EngineHit, EnginePage, SearchRequest


@dataclass(frozen=True, slots=True)
class FakeRecord:
    path: str
    title: str
    text: str
    collection_ids: tuple[str, ...]
    score: float = 1.0
    author: str | None = None
    mime_type: str | None = "text/plain"


class FakeEngine:
    def __init__(self, records: Sequence[FakeRecord]) -> None:
        merged: dict[str, FakeRecord] = {}
        for record in records:
            previous = merged.get(record.path)
            if previous is None:
                merged[record.path] = record
            else:
                selected = record if record.score > previous.score else previous
                merged[record.path] = replace(
                    selected,
                    collection_ids=tuple(
                        sorted(set(previous.collection_ids + record.collection_ids))
                    ),
                )
        self.records = list(merged.values())
        self.forced_paths: list[tuple[str, ...]] = []

    def health(self) -> EngineHealth:
        return EngineHealth(True)

    def search(self, request: SearchRequest) -> EnginePage:
        selected = [
            record for record in self.records
            if set(record.collection_ids) & set(request.collection_ids)
            and request.query.casefold() in (record.title + " " + record.text).casefold()
        ]
        selected.sort(key=lambda record: (-record.score, record.path))
        hits = tuple(
            EngineHit(
                path=record.path,
                title=record.title,
                author=record.author,
                mime_type=record.mime_type,
                size=len(record.text.encode()),
                date=None,
                score=record.score,
                collection_ids=record.collection_ids,
                snippets=(record.text[:160],),
                text=record.text if request.fetch_text else None,
            )
            for record in selected[request.offset:request.offset + request.limit]
        )
        return EnginePage(hits, len(selected), False)

    def extracted_text(self, path: str) -> str:
        return next((record.text for record in self.records if record.path == path), "")

    def force_reindex(self, paths: Sequence[str]) -> None:
        self.forced_paths.append(tuple(paths))
