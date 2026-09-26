"""Run integration checks only against an explicitly running Compose service."""

import os
import subprocess
from collections.abc import Callable

import pytest


@pytest.fixture
def compose_exec() -> Callable[[list[str]], subprocess.CompletedProcess[str]]:
    try:
        status = subprocess.run(
            ["docker", "compose", "ps", "-q", "app"], capture_output=True, text=True,
            check=False, timeout=5,
        )
        running = status.returncode == 0 and bool(status.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        running = False
    if not running:
        if os.environ.get("RECOLL_MODERN_REQUIRE_DOCKER") == "1":
            pytest.fail("Docker Compose service is not running")
        pytest.skip("Docker Compose service is not running")

    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "compose", "exec", "-T", "app", *command],
            capture_output=True, text=True, check=False, timeout=30,
        )

    return run
