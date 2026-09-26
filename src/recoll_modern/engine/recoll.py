"""Recoll Python binding and forced-index adapter, isolated from application code."""

import os
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from recoll_modern.engine.protocol import (
    EngineHealth,
    EngineHit,
    EnginePage,
    EngineUnavailable,
    SearchRequest,
)

_COLLECTION_ID = re.compile(r"c[0-9a-f]{10}\Z")


class RecollEngine:
    def __init__(self, config_dir: Path, index_timeout: float = 300.0) -> None:
        self.config_dir = config_dir
        self.index_timeout = index_timeout

    def _connect(self) -> Any:
        try:
            from recoll import recoll  # type: ignore[import-not-found]

            return recoll.connect(confdir=str(self.config_dir))
        except Exception as error:
            raise EngineUnavailable("Recoll index is unavailable") from error

    def health(self) -> EngineHealth:
        try:
            db = self._connect()
            try:
                query = db.query()
                query.execute("recollmodernhealthprobe")
                query.close()
            finally:
                db.close()
        except Exception:
            return EngineHealth(False, "Recoll index is unavailable")
        return EngineHealth(True)

    def search(self, request: SearchRequest) -> EnginePage:
        if not _safe_query(request.query):
            raise ValueError("query syntax cannot escape collection scope")
        if not request.collection_ids or any(
            _COLLECTION_ID.fullmatch(collection_id) is None
            for collection_id in request.collection_ids
        ):
            raise ValueError("one or more valid collection IDs are required")
        scopes = " OR ".join(
            f"collection:{collection_id}" for collection_id in request.collection_ids
        )
        query_text = f"({request.query}) AND ({scopes})"
        db = self._connect()
        try:
            query = db.query()
            try:
                query.execute(query_text, fetchtext=request.fetch_text)
                total = int(query.rowcount)
                if request.offset >= total or request.limit == 0:
                    return EnginePage((), total)
                query.scroll(request.offset, "absolute")
                docs = query.fetchmany(request.limit)
                hits = tuple(
                    _hit(doc, query, request.fetch_text, request.offset + index)
                    for index, doc in enumerate(docs)
                )
                return EnginePage(hits, total)
            finally:
                query.close()
        except Exception as error:
            raise EngineUnavailable("Recoll search is unavailable") from error
        finally:
            db.close()

    def extracted_text(self, path: str) -> str:
        try:
            from recoll import fsudi, rclextract

            db = self._connect()
            try:
                doc = db.getDoc(fsudi.fs_udi(path))
                if doc is None:
                    return ""
                extracted = rclextract.Extractor(doc).textextract(doc.ipath)
                return str(extracted.text)
            finally:
                db.close()
        except (KeyError, LookupError):
            return ""
        except Exception as error:
            raise EngineUnavailable("Recoll text is unavailable") from error

    def force_reindex(self, paths: Sequence[str]) -> None:
        if not paths:
            return
        if any(not Path(path).is_absolute() for path in paths):
            raise ValueError("index paths must be absolute")
        try:
            subprocess.run(
                ["recollindex", "-c", str(self.config_dir), "-i", "-Z", *paths],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.index_timeout,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise EngineUnavailable("Recoll indexing is unavailable") from error


def _hit(doc: Any, query: Any, fetch_text: bool, rank: int) -> EngineHit:
    raw_url = doc.getbinurl()
    if isinstance(raw_url, bytes):
        path = os.fsdecode(raw_url.removeprefix(b"file://"))
    else:
        path = str(raw_url).removeprefix("file://")
    snippets = tuple(str(fragment[2]) for fragment in query.getsnippets(doc, maxoccs=3))
    raw_date = getattr(doc, "fmtime", None)
    try:
        date = datetime.fromtimestamp(int(raw_date), UTC) if raw_date else None
    except (ValueError, TypeError, OverflowError):
        date = None
    raw_size = getattr(doc, "fbytes", None)
    try:
        size = int(raw_size) if raw_size else None
    except (ValueError, TypeError):
        size = None
    return EngineHit(
        path=path,
        title=str(getattr(doc, "title", "")),
        author=str(getattr(doc, "author", "")) or None,
        mime_type=str(getattr(doc, "mtype", "")) or None,
        size=size,
        date=date,
        score=1.0 / (rank + 1),
        collection_ids=tuple(str(getattr(doc, "collection", "")).split()),
        snippets=snippets,
        text=str(getattr(doc, "text", "")) if fetch_text else None,
    )


def _safe_query(query: str) -> bool:
    """Keep user grouping inside the enclosing scope expression."""
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
