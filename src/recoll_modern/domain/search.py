"""Validate scoped searches and project trusted, current document records."""

from dataclasses import dataclass
from pathlib import Path

from recoll_modern.domain.errors import AppError
from recoll_modern.engine.protocol import Engine, EngineUnavailable, SearchRequest
from recoll_modern.indexing.paths import PathPolicy
from recoll_modern.storage.documents import DocumentRepository
from recoll_modern.storage.membership import MembershipRepository

ALLOWED_FIELDS = frozenset({
    "title", "author", "path", "mime_type", "size", "date", "score", "collections",
    "snippets", "text", "links",
})
DEFAULT_FIELDS = ALLOWED_FIELDS - {"text", "links"}


def valid_query(query: str) -> bool:
    """Keep user grouping entirely inside the engine's mandatory scope clause."""
    if not query.strip() or "\\" in query:
        return False
    depth = 0
    quoted = False
    for character in query:
        if character == '"':
            quoted = not quoted
        elif not quoted and character == "(":
            depth += 1
        elif not quoted and character == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quoted


@dataclass(frozen=True, slots=True)
class SearchInput:
    query: str
    collection_ids: tuple[str, ...]
    fields: tuple[str, ...] | None = None
    limit: int = 20
    offset: int = 0
    text_limit: int = 20_000


@dataclass(frozen=True, slots=True)
class SearchResult:
    hits: list[dict[str, object]]
    total: int
    total_is_approximate: bool


class SearchService:
    def __init__(
        self, engine: Engine, documents: DocumentRepository,
        memberships: MembershipRepository, policy: PathPolicy, text_limit_max: int,
    ) -> None:
        self._engine = engine
        self._documents = documents
        self._memberships = memberships
        self._policy = policy
        self._text_limit_max = text_limit_max

    def search(self, search: SearchInput) -> SearchResult:
        if not valid_query(search.query):
            raise AppError("invalid_query", "Query must not be empty", 400)
        if not search.collection_ids:
            raise AppError("scope_required", "At least one collection is required", 400)
        if search.fields is not None and set(search.fields) - ALLOWED_FIELDS:
            raise AppError("invalid_field", "Unknown search field", 422)
        if not 1 <= search.limit <= 100 or search.offset < 0 or search.text_limit < 0:
            raise AppError("validation_failed", "Invalid search bounds", 422)
        fields = DEFAULT_FIELDS if search.fields is None else set(search.fields)
        scope = tuple(dict.fromkeys(search.collection_ids))
        try:
            page = self._engine.search(SearchRequest(
                search.query.strip(), scope, search.limit, search.offset, "text" in fields
            ))
        except EngineUnavailable:
            raise AppError("engine_unavailable", "Search engine is unavailable", 503) from None
        except ValueError:
            raise AppError("invalid_query", "Query is invalid", 400) from None
        results: list[dict[str, object]] = []
        for hit in page.hits:
            try:
                path = Path(hit.path)
                relative = path.relative_to(self._policy.root).as_posix()
                if not path.resolve().is_relative_to(self._policy.root):
                    continue
            except ValueError:
                continue
            document = self._documents.by_path(relative)
            if document is None or document.canonical_path != relative:
                continue
            current_collections = self._memberships.effective_collections(document.content_hash)
            if not set(current_collections).intersection(scope):
                continue
            values: dict[str, object] = {
                "title": hit.title, "author": hit.author, "path": relative,
                "mime_type": hit.mime_type, "size": hit.size if hit.size is not None
                else document.byte_size,
                "date": hit.date, "score": hit.score,
                "collections": current_collections, "snippets": list(hit.snippets),
            }
            item: dict[str, object] = {"document_id": document.content_hash}
            item.update({name: values[name] for name in fields if name in values})
            if "text" in fields:
                full = hit.text or ""
                bound = min(search.text_limit, self._text_limit_max)
                item["text"] = full[:bound]
                item["text_truncated"] = len(full) > bound
            results.append(item)
        return SearchResult(results, page.total, page.total_is_approximate)
