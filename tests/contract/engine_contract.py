from recoll_modern.engine.protocol import Engine, SearchRequest


class EngineContract:
    engine: Engine

    def test_search_returns_one_ranked_page(self) -> None:
        page = self.engine.search(SearchRequest(
            query="python", collection_ids=("c0000000001", "c0000000002"),
            limit=20, offset=0, fetch_text=False,
        ))
        assert page.total >= len(page.hits)
        assert [hit.score for hit in page.hits] == sorted(
            [hit.score for hit in page.hits], reverse=True
        )
        assert len({hit.path for hit in page.hits}) == len(page.hits)

    def test_search_scopes_collection_and_paginates(self) -> None:
        first = self.engine.search(SearchRequest(
            "python", ("c0000000001",), 1, 0, False
        ))
        second = self.engine.search(SearchRequest(
            "python", ("c0000000001",), 1, 1, False
        ))
        assert all("c0000000001" in hit.collection_ids for hit in first.hits + second.hits)
        assert not first.hits or not second.hits or first.hits[0].path != second.hits[0].path

    def test_optional_text_and_health(self) -> None:
        page = self.engine.search(SearchRequest("python", ("c0000000001",), 20, 0, True))
        assert self.engine.health().available
        assert all(hit.text is not None for hit in page.hits)

    def test_missing_extracted_text_is_empty(self) -> None:
        assert self.engine.extracted_text("/documents/does-not-exist.txt") == ""
