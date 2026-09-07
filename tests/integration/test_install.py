"""Подключение к чужому воркспейсу.

Главное требование к установщику — не навредить: он приходит в чужой
проект, где уже есть свои настройки, и обязан их сохранить.
"""

from __future__ import annotations

import json

import pytest

from agentos.install import BEGIN, END, install, write_marked_block


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "чужой-проект"
    root.mkdir()
    (root / "README.md").write_text("# Проект\n", encoding="utf-8")
    return root


def test_fresh_project_gets_all_entrypoints(project):
    report = install(project)

    for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".mcp.json"):
        assert (project / name).exists(), f"нет точки входа {name}"
    assert (project / ".agentos" / "config" / "agentos.yaml").exists()
    assert (project / ".cursor" / "rules" / "agentos.mdc").exists()
    assert report.created
    assert not report.warnings


def test_install_is_idempotent(project):
    install(project)
    second = install(project)

    assert not second.created
    assert not second.updated
    assert second.unchanged


def test_existing_instructions_are_preserved(project):
    (project / "CLAUDE.md").write_text(
        "# CLAUDE.md\n\nНе трогай legacy/.\n", encoding="utf-8"
    )

    install(project)

    text = (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Не трогай legacy/." in text, "чужие инструкции нельзя терять"
    assert BEGIN in text and END in text


def test_existing_mcp_servers_are_preserved(project):
    (project / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"github": {"command": "npx", "args": []}}}),
        encoding="utf-8",
    )

    install(project)

    config = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    assert "github" in config["mcpServers"], "чужой сервер нельзя вытеснять"
    assert "agentos" in config["mcpServers"]


def test_broken_json_is_reported_not_clobbered(project):
    broken = "{ это не JSON"
    (project / ".mcp.json").write_text(broken, encoding="utf-8")

    report = install(project)

    assert (project / ".mcp.json").read_text(encoding="utf-8") == broken
    assert any("невалидный JSON" in w for w in report.warnings)


def test_session_hook_merges_with_existing_settings(project):
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}), encoding="utf-8"
    )

    install(project)

    settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash(ls:*)"]
    hooks = settings["hooks"]["SessionStart"]
    assert "agentctl resume" in json.dumps(hooks, ensure_ascii=False)


def test_gitignore_gets_runtime_dir_once(project):
    (project / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

    install(project)
    install(project)

    lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "node_modules/" in lines
    assert lines.count(".agentos/var/") == 1, "повторная установка не должна дублировать"


def test_marked_block_is_replaced_not_appended(tmp_path):
    path = tmp_path / "AGENTS.md"
    write_marked_block(path, "первая версия")
    write_marked_block(path, "вторая версия")

    text = path.read_text(encoding="utf-8")
    assert text.count(BEGIN) == 1
    assert "первая версия" not in text
    assert "вторая версия" in text


def test_platform_selection_limits_what_is_written(project):
    install(project, platforms=("gemini",), with_mcp=False)

    assert (project / "GEMINI.md").exists()
    assert (project / "AGENTS.md").exists(), "универсальная точка входа пишется всегда"
    assert not (project / "CLAUDE.md").exists()
    assert not (project / ".mcp.json").exists()


def test_codex_gets_a_manual_step_not_a_silent_edit(project):
    """Настройки Codex глобальные: лезть в них за человека нельзя."""
    report = install(project, platforms=("codex",))

    assert any("config.toml" in item for item in report.manual)
    assert not (project / ".codex").exists()
