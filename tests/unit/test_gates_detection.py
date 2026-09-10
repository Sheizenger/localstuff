"""Гейты определяются по проекту, а не наследуются из умолчаний.

`make test` — правда про этот репозиторий и неправда про любой другой.
Гейт, команды которого не существует, красит приёмку в красный навсегда,
а красный гейт переспорить нельзя — миссия не закроется никогда.
"""

from __future__ import annotations

import json

import pytest

from agentos.gates import detect, render_config


def test_makefile_targets_win(tmp_path):
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n\nlint:\n\truff check .\n")
    assert [g.cmd for g in detect(tmp_path)] == ["make test", "make lint"]


def test_makefile_without_test_target_is_not_used(tmp_path):
    (tmp_path / "Makefile").write_text("build:\n\tgcc main.c\n")
    assert detect(tmp_path) == []


def test_variable_assignment_is_not_a_target(tmp_path):
    """`PYTHON := python3` — не цель, и гейтом стать не должна."""
    (tmp_path / "Makefile").write_text("PYTHON := python3\ntest:\n\t$(PYTHON) -m pytest\n")
    assert [g.cmd for g in detect(tmp_path)] == ["make test"]


def test_npm_scripts(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest", "lint": "eslint ."}})
    )
    assert [g.cmd for g in detect(tmp_path)] == ["npm test", "npm run lint"]


@pytest.mark.parametrize(
    "lockfile,expected",
    [("pnpm-lock.yaml", "pnpm run test"), ("yarn.lock", "yarn test")],
)
def test_package_manager_follows_the_lockfile(tmp_path, lockfile, expected):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    (tmp_path / lockfile).write_text("")
    assert [g.cmd for g in detect(tmp_path)] == [expected]


def test_cargo_and_go(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    assert detect(tmp_path)[0].cmd == "cargo test"

    other = tmp_path / "go"
    other.mkdir()
    (other / "go.mod").write_text("module x\n")
    assert detect(other)[0].cmd == "go test ./..."


def test_python_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    (tmp_path / "tests").mkdir()
    assert [g.cmd for g in detect(tmp_path)] == ["pytest -q", "ruff check ."]


def test_empty_project_gets_no_gates_at_all(tmp_path):
    """Пустой список честнее команды, которой нет."""
    assert detect(tmp_path) == []
    config = render_config([])
    assert "programmatic_gates: []" in config


def test_rendered_config_is_valid_yaml_with_the_right_keys(tmp_path):
    import yaml

    (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
    data = yaml.safe_load(render_config(detect(tmp_path)))
    assert data["self_check"]["programmatic_gates"] == [
        {"name": "tests", "cmd": "make test", "applies_when": "artifacts_touch_code"}
    ]


def test_detected_binaries_are_allowed_by_policy():
    """Гейт, запрещённый политикой, — тот же тупик, что и несуществующий."""
    from agentos.config import Config
    from agentos.paths import package_defaults

    policy = Config.load(package_defaults()).policy
    allowed = set(policy["shell"]["allow_binaries"])
    for binary in ("make", "npm", "pnpm", "yarn", "cargo", "go", "pytest", "ruff"):
        assert binary in allowed, binary
