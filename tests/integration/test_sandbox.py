"""Запуск в контейнере: проверяется команда, а не сам docker.

Собрать образ в тестах нельзя — на машине для прогона обычно нет демона
docker. Но всё, чем песочница может навредить, живёт не в образе, а в
строке запуска: что смонтировано, с какими правами, как передаются ключи.
Это и проверяется.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SANDBOX_SH = REPO_ROOT / "scripts" / "sandbox.sh"


@pytest.fixture
def argv(tmp_path):
    """Команда запуска песочницы при заданном окружении."""
    from agentos.sandbox import Sandbox

    def build(*args: str, **overrides: str) -> list[str]:
        env = {
            "HOME": str(tmp_path / "home"),
            "AGENTOS_PROJECT": str(tmp_path / "project"),
            "AGENTOS_GLOBAL_HOME": str(tmp_path / "global"),
        }
        env.update(overrides)
        return Sandbox.from_env(env=env).run_argv(list(args))

    return build


def test_only_project_and_global_memory_are_mounted(argv):
    command = argv("doctor")
    mounts = [command[i + 1] for i, a in enumerate(command) if a == "-v"]
    assert len(mounts) == 2
    assert mounts[0].endswith(":/work")
    assert mounts[1].endswith(":/root/.agentos")


def test_container_gets_no_way_out(argv):
    command = argv("doctor")
    assert ["--security-opt", "no-new-privileges"] == command[
        command.index("--security-opt") : command.index("--security-opt") + 2
    ]
    # Ни привилегий, ни docker-сокета: агенту, который сам решает, что
    # запускать, через них хватило бы одной команды, чтобы выйти наружу.
    assert "--privileged" not in command
    assert not any("docker.sock" in a for a in command)


def test_keys_are_passed_by_name_not_by_value(argv):
    command = argv("doctor", ANTHROPIC_API_KEY="sk-очень-секретный")
    assert "ANTHROPIC_API_KEY" in command
    assert not any("sk-очень-секретный" in a for a in command)


def test_unset_keys_do_not_leak_into_the_command(argv):
    command = argv("doctor")
    assert "ANTHROPIC_API_KEY" not in command


def test_agent_identity_reaches_the_container(argv):
    command = argv("status", AGENTOS_AGENT_ID="release")
    assert "AGENTOS_AGENT_ID" in command
    assert command[-1] == "status"


def test_network_can_be_cut_off_completely(argv):
    assert argv("doctor", AGENTOS_NETWORK="none")[4:6] == ["--network", "none"]


def test_podman_is_a_drop_in_replacement(argv):
    assert argv("doctor", AGENTOS_DOCKER="podman")[0] == "podman"


def test_command_arguments_survive_spaces(argv):
    assert argv("goal", "почини сборку")[-2:] == ["goal", "почини сборку"]


def test_image_is_built_from_the_checkout_when_it_is_available():
    """В чекауте образ собирается из него, а не тянется из сети."""
    from agentos.sandbox import Sandbox

    box = Sandbox.from_env(env={"HOME": "/tmp"})
    context = box.repo_context()
    assert context is not None and (context / "Dockerfile").exists()
    assert box.build_argv(context)[-1] == str(context)


def test_missing_docker_says_what_to_do(tmp_path):
    from agentos.sandbox import Sandbox, SandboxError

    box = Sandbox.from_env(env={"HOME": str(tmp_path), "AGENTOS_DOCKER": "нет-такого"})
    with pytest.raises(SandboxError, match="нет-такого"):
        box.require_docker()


@pytest.mark.skipif(shutil.which("bash") is None, reason="нужен bash")
def test_shell_wrapper_delegates_to_the_same_implementation(tmp_path):
    """scripts/sandbox.sh не имеет своей логики — иначе они разъедутся."""
    env = dict(os.environ)
    # agentctl на этом PATH нет — обёртка должна уйти в ветку чекаута.
    env["PATH"] = "/usr/bin:/bin"
    env["PYTHON"] = sys.executable
    env["AGENTOS_PROJECT"] = str(tmp_path / "project")
    env["AGENTOS_GLOBAL_HOME"] = str(tmp_path / "global")
    result = subprocess.run(
        ["bash", str(SANDBOX_SH), "--print-command", "doctor"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[:2] == ["docker", "run"]
    assert result.stdout.strip().endswith("doctor")
