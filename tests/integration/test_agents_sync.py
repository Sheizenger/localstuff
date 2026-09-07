"""Генерация описаний субагентов для агент-хоста из config/agents/*.yaml.

Роли правятся данными, а не кодом; проверяем, что данные действительно
доезжают до файлов, которые читает хост.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_every_selectable_role_gets_a_description(runtime):
    result = subprocess.run(
        [sys.executable, "-m", "agentos.cli", "agents", "sync"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO_ROOT), "AGENTOS_ALLOW_MOCK": "1"},
        timeout=120,
    )
    assert result.returncode == 0, result.stderr

    target = REPO_ROOT / ".claude" / "agents"
    selectable = [r for r in runtime.config.roles.values() if r.selectable]
    assert selectable

    for role in selectable:
        path = target / f"agentos-{role.name}.md"
        assert path.exists(), f"нет описания для роли {role.name}"
        body = path.read_text(encoding="utf-8")
        assert role.goal.split(".")[0] in body
        assert role.tier in body
        assert "agentctl task report" in body, "хост должен знать, как вернуть результат"


def test_non_selectable_roles_are_not_exposed(runtime):
    """Оркестратор и критик вызываются системой, а не выбираются планировщиком."""
    target = REPO_ROOT / ".claude" / "agents"
    for role in runtime.config.roles.values():
        if not role.selectable:
            assert not (target / f"agentos-{role.name}.md").exists()
