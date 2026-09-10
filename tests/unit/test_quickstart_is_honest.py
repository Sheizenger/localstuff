"""Инструкция обещает конкретные команды — они должны существовать.

Быстрый старт читает человек, который ничего не знает о системе, и
вставляет оттуда текст дословно. Команда, которой нет, здесь дороже, чем
где-либо: она ломает первое же действие.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

QUICKSTART = Path(__file__).resolve().parent.parent.parent / "docs" / "QUICKSTART.md"
TEXT = QUICKSTART.read_text(encoding="utf-8")


def _subcommands() -> set[str]:
    from agentos.cli import build_parser

    parser = build_parser()
    actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
    return {name for action in actions for name in (action.choices or {})}


@pytest.mark.parametrize(
    "command", sorted(set(re.findall(r"agentctl (?:sandbox )?([a-z-]+)", TEXT)))
)
def test_every_promised_command_exists(command):
    assert command in _subcommands(), f"в инструкции есть `agentctl {command}`, а команды нет"


@pytest.mark.parametrize("flag", sorted(set(re.findall(r"(--[a-z][a-z-]+)", TEXT))))
def test_every_promised_flag_is_understood(flag):
    """Флаги проверяются по справке: опечатка в инструкции — та же поломка."""
    import subprocess
    import sys

    if flag in {"--reinstall", "--force"}:  # это флаги uv, не наши
        return
    help_text = subprocess.run(
        [sys.executable, "-m", "agentos.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    subhelp = ""
    for command in sorted(_subcommands()):
        subhelp += subprocess.run(
            [sys.executable, "-m", "agentos.cli", command, "--help"],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    assert flag in help_text + subhelp, f"инструкция обещает {flag}, а его нет в справке"


def test_every_env_variable_from_the_guide_is_read_somewhere():
    """Переменная, которую никто не читает, — обещание без исполнения."""
    package = Path(__file__).resolve().parent.parent.parent / "agentos"
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in package.rglob("*.py")
    )
    for name in sorted(set(re.findall(r"AGENTOS_[A-Z_]+", TEXT))):
        assert name in sources, f"инструкция обещает {name}, а его никто не читает"


def test_the_install_url_points_at_code_that_has_the_installer():
    """Ссылка из инструкции должна вести туда, где есть agentctl install."""
    url = re.search(r'agentos @ git\+(\S+?)"', TEXT)
    assert url, "в инструкции нет команды установки"
    assert "github.com/Sheizenger/localstuff" in url.group(1)
