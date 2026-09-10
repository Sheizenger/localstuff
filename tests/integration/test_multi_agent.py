"""Несколько мастер-агентов в одном проекте.

Человек держит несколько чатов под разные задачи. Каждый чат — свой
мастер-агент, и он обязан вести только свои миссии: иначе два чата
растаскивают работу друг друга, и человек получает половину результата
в одном месте и половину в другом.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def cli(tmp_path):
    env = dict(os.environ)
    env.update(
        {
            "AGENTOS_HOME": str(tmp_path / "var"),
            "AGENTOS_ALLOW_MOCK": "1",
            "AGENTOS_IN_GATE": "1",
            "AGENTOS_MODE": "native",
            "AGENTOS_MOCK_STATE": str(tmp_path / "calls.txt"),
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    env.pop("AGENTOS_AGENT_ID", None)

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, "-m", "agentos.cli", *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
            timeout=180,
        )
        return result

    return run


def _mission_ids(status_json: str) -> set[str]:
    return {m["mission_id"] for m in json.loads(status_json)["missions"]}


def test_missions_belong_to_the_agent_that_created_them(runtime):
    """Выборка миссий ограничена своим агентом — на уровне ядра."""
    first = runtime.sm.create_mission("собрать релиз", agent_id="release")
    second = runtime.sm.create_mission("разобрать баг", agent_id="bugfix")

    assert [m["id"] for m in runtime.sm.active_missions("release")] == [first]
    assert [m["id"] for m in runtime.sm.active_missions("bugfix")] == [second]
    assert {m["id"] for m in runtime.sm.active_missions()} == {first, second}

    agents = {row["agent_id"]: row["missions"] for row in runtime.sm.agents_with_work()}
    assert agents == {"release": 1, "bugfix": 1}


def test_resume_pointers_do_not_overwrite_each_other(runtime):
    """У каждого агента свой указатель resume, а не общий файл."""
    from agentos.state.checkpoint import Checkpointer

    runtime.sm.create_mission("собрать релиз", agent_id="release")
    runtime.sm.create_mission("разобрать баг", agent_id="bugfix")

    release = Checkpointer(
        runtime.store, runtime.config.runs_dir, runtime.config.home, "release"
    )
    bugfix = Checkpointer(
        runtime.store, runtime.config.runs_dir, runtime.config.home, "bugfix"
    )
    release.refresh_resume_pointer()
    bugfix.refresh_resume_pointer()

    assert release.resume_path != bugfix.resume_path
    assert [m["goal"] for m in release.resume_pointer()["missions"]] == ["собрать релиз"]
    assert [m["goal"] for m in bugfix.resume_pointer()["missions"]] == ["разобрать баг"]


def test_agent_by_default_keeps_the_old_pointer_path(runtime):
    """Указатель агента по умолчанию лежит там же, где раньше.

    Его читают SessionStart-хук и скрипты; смена пути молча сломала бы их.
    """
    from agentos.state.checkpoint import Checkpointer

    ckpt = Checkpointer(runtime.store, runtime.config.runs_dir, runtime.config.home)
    assert ckpt.resume_path == runtime.config.home / "resume.json"


def test_two_chats_do_not_pick_up_each_others_work(cli):
    """Сквозная проверка через CLI: два агента, две миссии, ноль пересечений."""
    assert cli("init").returncode == 0
    cli("--agent", "release", "goal", "подготовить релиз")
    cli("--agent", "bugfix", "goal", "починить падение импорта")

    release = _mission_ids(cli("--agent", "release", "status", "--json").stdout)
    bugfix = _mission_ids(cli("--agent", "bugfix", "status", "--json").stdout)
    assert len(release) == 1 and len(bugfix) == 1
    assert not (release & bugfix)

    everything = _mission_ids(cli("status", "--all", "--json").stdout)
    assert everything == release | bugfix

    # Агент по умолчанию не видит чужих миссий, но и не молчит о них.
    default = cli("status")
    assert "активных миссий нет" in default.stdout
    assert "другие мастер-агенты" in default.stdout

    announce = cli("--agent", "release", "resume", "--announce").stdout
    assert "подготовить релиз" in announce
    assert "починить падение импорта" not in announce
