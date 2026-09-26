import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from recoll_modern.engine.protocol import EngineUnavailable, SearchRequest
from recoll_modern.engine.recoll import RecollEngine


def test_force_reindex_uses_argument_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **_kwargs: object) -> None:
        calls.append(args)

    monkeypatch.setattr(subprocess, "run", run)
    engine = RecollEngine(tmp_path)
    engine.force_reindex(("/documents/odd name.txt",))
    assert calls == [[
        "recollindex", "-c", str(tmp_path), "-i", "-Z", "/documents/odd name.txt"
    ]]


def test_force_reindex_hides_process_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_args: list[str], **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "recollindex", stderr="private path")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(EngineUnavailable) as caught:
        RecollEngine(tmp_path).force_reindex(("/documents/a.txt",))
    assert "private" not in str(caught.value)


def test_empty_search_does_not_scroll(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptyQuery:
        rowcount = 0

        def execute(self, *_args: object, **_kwargs: object) -> None:
            pass

        def scroll(self, *_args: object) -> None:
            raise AssertionError("empty result must not scroll")

        def close(self) -> None:
            pass

    query = EmptyQuery()
    db = SimpleNamespace(query=lambda: query, close=lambda: None)
    monkeypatch.setattr(RecollEngine, "_connect", lambda self: db)
    page = RecollEngine(tmp_path).search(SearchRequest(
        "python", ("c0000000001",), 20, 0, False
    ))
    assert page.total == 0 and page.hits == ()


def test_query_cannot_escape_collection_scope(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="query"):
        RecollEngine(tmp_path).search(SearchRequest(
            "python) OR all OR (", ("c0000000001",), 20, 0, False
        ))


def test_search_uses_one_scoped_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[str] = []
    doc = SimpleNamespace(
        getbinurl=lambda: b"file:///documents/odd name.txt",
        title="Python guide", author="Ada", mtype="text/plain", fbytes="12",
        fmtime="", collection="c0000000001 c0000000002", text="Python guide",
    )

    class Query:
        rowcount = 1

        def execute(self, query: str, **_kwargs: object) -> None:
            executed.append(query)

        def scroll(self, offset: int, mode: str) -> None:
            assert (offset, mode) == (0, "absolute")

        def fetchmany(self, limit: int) -> list[object]:
            assert limit == 20
            return [doc]

        def getsnippets(self, _doc: object, **_kwargs: object) -> list[tuple[int, str, str]]:
            return [(0, "Python", "Python guide")]

        def close(self) -> None:
            pass

    db = SimpleNamespace(query=Query, close=lambda: None)
    monkeypatch.setattr(RecollEngine, "_connect", lambda self: db)
    page = RecollEngine(tmp_path).search(SearchRequest(
        "python", ("c0000000001", "c0000000002"), 20, 0, True
    ))
    assert executed == [
        "(python) AND (collection:c0000000001 OR collection:c0000000002)"
    ]
    assert page.hits[0].path == "/documents/odd name.txt"
    assert page.hits[0].collection_ids == ("c0000000001", "c0000000002")
    assert page.hits[0].text == "Python guide"


def test_extracted_text_uses_exact_path_udi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = '/documents/odd "name" (draft).txt'
    seen: list[str] = []
    recoll_package = ModuleType("recoll")

    def fake_udi(value: str) -> str:
        seen.append(value)
        return "udi"

    recoll_package.fsudi = SimpleNamespace(fs_udi=fake_udi)  # type: ignore[attr-defined]
    recoll_package.rclextract = SimpleNamespace(  # type: ignore[attr-defined]
        Extractor=lambda _doc: SimpleNamespace(
            textextract=lambda _ipath: SimpleNamespace(text="Complete text")
        )
    )
    monkeypatch.setitem(sys.modules, "recoll", recoll_package)
    db = SimpleNamespace(
        getDoc=lambda udi: SimpleNamespace(
            ipath="", getbinurl=lambda: path.encode()
        ) if udi == "udi" else None,
        close=lambda: None,
    )
    monkeypatch.setattr(RecollEngine, "_connect", lambda self: db)
    assert RecollEngine(tmp_path).extracted_text(path) == "Complete text"
    assert seen == [path]
