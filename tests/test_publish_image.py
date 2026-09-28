"""Exercise the publish script with an isolated Docker command stub."""

import os
import subprocess
from pathlib import Path


def _fake_docker(tmp_path: Path, *, fail_build: bool = False) -> tuple[Path, Path]:
    docker = tmp_path / "docker"
    log = tmp_path / "docker.log"
    docker.write_text(
        "#!/bin/sh\n"
        "printf '%s|%s|%s\\n' \"$1\" \"${2-}\" \"$DOCKER_CONFIG\" >> \"$DOCKER_LOG\"\n"
        "case \"$1\" in\n"
        "  login) cat >/dev/null ;;\n"
        f"  build) {'exit 42' if fail_build else 'printf sha256:built-revision'} ;;\n"
        "esac\n"
    )
    docker.chmod(0o755)
    return docker, log


def _run_publish(
    tmp_path: Path, *, fail_build: bool = False
) -> tuple[subprocess.CompletedProcess[str], Path]:
    _, log = _fake_docker(tmp_path, fail_build=fail_build)
    env = os.environ.copy()
    env.update(
        PATH=f"{tmp_path}:{env['PATH']}",
        DOCKER_LOG=str(log),
        GITHUB_REF="refs/tags/v1.2.3",
        GITHUB_REF_NAME="v1.2.3",
        GITHUB_SHA="deadbeef",
        REGISTRY_USERNAME="test-user",
        REGISTRY_TOKEN="test-token-never-print",
    )
    result = subprocess.run(
        ["bash", "scripts/publish_image.sh"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result, log


def test_publish_uses_immutable_build_id_and_removes_credentials(tmp_path: Path) -> None:
    result, log = _run_publish(tmp_path)
    assert result.returncode == 0, result.stderr
    commands = log.read_text().splitlines()
    config_dir = Path(commands[0].split("|")[2])
    assert [line.split("|")[0] for line in commands] == [
        "login", "build", "tag", "push", "tag", "push"
    ]
    assert all(line.split("|")[2] == str(config_dir) for line in commands)
    assert "sha256:built-revision" in commands[2]
    assert "sha256:built-revision" in commands[4]
    assert "recoll-modern:publish" not in log.read_text()
    assert not config_dir.exists()
    assert "test-token-never-print" not in result.stdout + result.stderr


def test_failed_build_also_removes_registry_credentials(tmp_path: Path) -> None:
    result, log = _run_publish(tmp_path, fail_build=True)
    assert result.returncode != 0
    config_dir = Path(log.read_text().splitlines()[0].split("|")[2])
    assert not config_dir.exists()
