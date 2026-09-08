"""Переносимость: пути и то, что уезжает вместе с пакетом.

AgentOS ставится один раз и подключается к чужим проектам, поэтому пути
не должны зависеть от того, где лежит сам репозиторий.
"""

from __future__ import annotations

import pytest

from agentos.config import Config, deep_merge
from agentos.paths import (
    PROJECT_DIR,
    config_layers,
    find_project_root,
    global_home,
    package_defaults,
    project_state,
)


def test_defaults_ship_with_the_package():
    """Без этих файлов установленный глобально agentctl бесполезен."""
    defaults = package_defaults()

    for name in ("agentos.yaml", "models.yaml", "policy.yaml", "mcp.json"):
        assert (defaults / name).exists(), f"нет {name} в настройках пакета"
    assert list((defaults / "agents").glob("*.yaml")), "нет описаний ролей"


def test_project_root_is_found_by_markers(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTOS_ROOT", raising=False)
    project = tmp_path / "проект"
    (project / "src" / "глубоко").mkdir(parents=True)
    (project / ".git").mkdir()

    assert find_project_root(project / "src" / "глубоко") == project.resolve()


def test_root_falls_back_to_current_directory(tmp_path, monkeypatch):
    """Без маркеров работаем здесь, а не пишем состояние куда-то выше."""
    monkeypatch.delenv("AGENTOS_ROOT", raising=False)
    plain = tmp_path / "просто-папка"
    plain.mkdir()

    assert find_project_root(plain) == plain.resolve()


def test_state_lives_inside_the_project(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTOS_HOME", raising=False)
    project = tmp_path / "проект"
    project.mkdir()

    assert project_state(project) == project / PROJECT_DIR / "var"


def test_global_home_is_separate_from_the_project(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_GLOBAL_HOME", str(tmp_path / "общее"))
    assert global_home() == (tmp_path / "общее").resolve()


def test_layers_go_from_general_to_specific(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTOS_HOME", raising=False)
    monkeypatch.setenv("AGENTOS_GLOBAL_HOME", str(tmp_path / "общее"))
    (tmp_path / "общее" / "config").mkdir(parents=True)
    project = tmp_path / "проект"
    (project / PROJECT_DIR / "config").mkdir(parents=True)

    layers = config_layers(project)

    assert layers[0] == package_defaults(), "настройки пакета — самый общий слой"
    assert layers[-1] == project / PROJECT_DIR / "config", "проект переопределяет всё"


def test_deep_merge_keeps_untouched_keys():
    base = {"budget": {"mission_tokens": 100, "mission_usd": 5}, "runtime": {"mode": "auto"}}
    override = {"budget": {"mission_tokens": 999}}

    merged = deep_merge(base, override)

    assert merged["budget"] == {"mission_tokens": 999, "mission_usd": 5}
    assert merged["runtime"] == {"mode": "auto"}


def test_deep_merge_replaces_lists_wholesale():
    """Иначе из унаследованного списка нечем было бы что-то убрать."""
    merged = deep_merge({"allow": ["git", "make", "rm"]}, {"allow": ["git"]})

    assert merged["allow"] == ["git"]


def test_project_layer_overrides_package_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTOS_HOME", raising=False)
    monkeypatch.setenv("AGENTOS_GLOBAL_HOME", str(tmp_path / "общее"))
    monkeypatch.delenv("AGENTOS_CONFIG_DIR", raising=False)
    project = tmp_path / "проект"
    config_dir = project / PROJECT_DIR / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "agentos.yaml").write_text(
        "budget:\n  mission_tokens: 12345\n", encoding="utf-8"
    )

    config = Config.load(project)

    assert config.get("budget.mission_tokens") == 12345
    # Остальное досталось от умолчаний пакета, а не потерялось.
    assert config.get("runtime.max_concurrency")
    assert config.roles


def test_role_can_be_overridden_without_copying_the_rest(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTOS_HOME", raising=False)
    monkeypatch.setenv("AGENTOS_GLOBAL_HOME", str(tmp_path / "общее"))
    monkeypatch.delenv("AGENTOS_CONFIG_DIR", raising=False)
    project = tmp_path / "проект"
    agents_dir = project / PROJECT_DIR / "config" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "coder.yaml").write_text("tier: nano\n", encoding="utf-8")

    config = Config.load(project)

    assert config.role("coder").tier == "nano", "проект переопределил тир"
    assert config.role("coder").triggers, "остальные поля роли остались от умолчаний"
    assert len(config.roles) >= 8, "прочие роли не потерялись"


@pytest.mark.parametrize("name", ["reviewer", "critic", "planner"])
def test_default_roles_are_available_anywhere(name):
    assert Config.load().role(name)


def test_contract_renderings_cannot_drift():
    """Контракт доставляется двумя каналами и обязан совпадать по существу."""
    from agentos.contract import INVARIANTS, operations, render_instructions, render_markdown

    markdown = render_markdown()
    instructions = render_instructions()

    for cli, tool in operations():
        command = cli.split()[1]  # resume, goal, task, verify, memory
        assert command in markdown, f"в файле-инструкции нет операции {command}"
        assert tool in instructions, f"в контракте MCP нет инструмента {tool}"

    for invariant in INVARIANTS:
        head = invariant.split(".")[0]
        assert head in markdown and head in instructions, "инвариант потерян в одном из текстов"
