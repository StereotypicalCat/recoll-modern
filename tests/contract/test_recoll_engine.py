import os
from pathlib import Path

import pytest

from recoll_modern.engine.recoll import RecollEngine

from .engine_contract import EngineContract


class TestRecollEngine(EngineContract):
    @pytest.fixture(autouse=True)
    def available_engine(self) -> None:
        config = os.environ.get("RECOLL_MODERN_TEST_RECOLL_CONFIG_DIR")
        if config is None:
            pytest.skip("Recoll test container is not running")
        engine = RecollEngine(Path(config))
        if not engine.health().available:
            pytest.skip("Recoll test container is not running")
        self.engine = engine
