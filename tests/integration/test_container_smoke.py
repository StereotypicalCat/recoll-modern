"""Image runtime and Recoll binding contracts."""

import subprocess
from collections.abc import Callable


def test_recoll_binding_and_helper_are_present(
    compose_exec: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> None:
    binding = compose_exec(["python", "-c", "from recoll import recoll"])
    assert binding.returncode == 0, binding.stderr
    helper = compose_exec(["recoll-membership", "/documents/none"])
    assert helper.returncode == 0, helper.stderr
