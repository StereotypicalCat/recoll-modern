import json
import os
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from recoll_modern.engine.protocol import Engine, EngineHealth, EngineHit, EnginePage, SearchRequest
from recoll_modern.engine.recoll import RecollEngine

from .engine_contract import EngineContract

_CONTAINER_SCRIPT = """
import json, sys
from dataclasses import asdict
from pathlib import Path
from recoll_modern.engine.protocol import SearchRequest
from recoll_modern.engine.recoll import RecollEngine
engine = RecollEngine(Path('/var/lib/recoll-modern/recoll-config'))
method, payload = sys.argv[1], json.loads(sys.argv[2])
if method == 'search':
    result = engine.search(SearchRequest(**payload))
elif method == 'health':
    result = engine.health()
elif method == 'extracted_text':
    result = engine.extracted_text(payload['path'])
else:
    raise ValueError(method)
print(json.dumps(asdict(result) if method != 'extracted_text' else result, default=str))
"""


class ContainerRecollEngine:
    def _call(self, method: str, payload: dict[str, object]) -> object:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "app", "python", "-c", _CONTAINER_SCRIPT,
             method, json.dumps(payload)],
            capture_output=True, text=True, check=False, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def search(self, request: SearchRequest) -> EnginePage:
        value = cast(dict[str, object], self._call("search", asdict(request)))
        hits = []
        for raw in cast(list[dict[str, object]], value["hits"]):
            date = raw["date"]
            raw["date"] = datetime.fromisoformat(date) if isinstance(date, str) else None
            raw["collection_ids"] = tuple(cast(list[str], raw["collection_ids"]))
            raw["snippets"] = tuple(cast(list[str], raw["snippets"]))
            hits.append(EngineHit(**raw))  # type: ignore[arg-type]
        return EnginePage(
            tuple(hits), int(cast(int, value["total"])), bool(value["total_is_approximate"])
        )

    def health(self) -> EngineHealth:
        value = cast(dict[str, object], self._call("health", {}))
        return EngineHealth(bool(value["available"]), cast(str | None, value["message"]))

    def extracted_text(self, path: str) -> str:
        return cast(str, self._call("extracted_text", {"path": path}))

    def force_reindex(self, paths: tuple[str, ...]) -> None:
        raise NotImplementedError


class TestRecollEngine(EngineContract):
    @pytest.fixture(autouse=True)
    def available_engine(self) -> None:
        config = os.environ.get("RECOLL_MODERN_TEST_RECOLL_CONFIG_DIR")
        if config is None:
            if os.environ.get("RECOLL_MODERN_REQUIRE_DOCKER") != "1":
                pytest.skip("Recoll test container is not running")
            corpus_file = os.environ.get("RECOLL_MODERN_TEST_CORPUS_FILE")
            if corpus_file is None:
                pytest.fail("RECOLL_MODERN_TEST_CORPUS_FILE is required for container contract")
            bootstrap = subprocess.run(
                ["docker", "compose", "exec", "-T", "app", "recollindex", "-c",
                 "/var/lib/recoll-modern/recoll-config", "-i", "-Z",
                 f"/documents/{corpus_file}"],
                capture_output=True, text=True, check=False, timeout=30,
            )
            assert bootstrap.returncode == 0, bootstrap.stderr
            self.engine = cast(Engine, ContainerRecollEngine())
            assert self.engine.health().available
            return
        engine = RecollEngine(Path(config))
        if not engine.health().available:
            pytest.skip("Recoll test container is not running")
        self.engine = engine
