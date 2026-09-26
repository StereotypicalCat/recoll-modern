from recoll_modern.engine.fake import FakeEngine, FakeRecord
from recoll_modern.engine.protocol import SearchRequest

from .engine_contract import EngineContract


class TestFakeEngine(EngineContract):
    def setup_method(self) -> None:
        self.engine = FakeEngine([
            FakeRecord("/documents/a.txt", "Python guide", "A Python guide", (
                "c0000000001",), 0.9),
            FakeRecord("/documents/b.txt", "Python recipes", "Python recipes", (
                "c0000000001", "c0000000002"), 0.8),
            FakeRecord("/documents/c.txt", "Python notes", "Python notes", (
                "c0000000002",), 0.7),
        ])


def test_fake_logs_forced_paths() -> None:
    engine = FakeEngine([])
    engine.force_reindex(("/documents/b.txt", "/documents/a.txt"))
    assert engine.forced_paths == [("/documents/b.txt", "/documents/a.txt")]


def test_fake_returns_one_hit_for_duplicate_path() -> None:
    engine = FakeEngine([
        FakeRecord("/documents/a.txt", "Python", "Python", ("c0000000001",), 0.9),
        FakeRecord("/documents/a.txt", "Python", "Python", ("c0000000002",), 0.8),
    ])
    page = engine.search(SearchRequest(
        "python", ("c0000000001", "c0000000002"), 20, 0, False
    ))
    assert page.total == 1
    assert page.hits[0].collection_ids == ("c0000000001", "c0000000002")
