"""Навыки должны быть в любом проекте, а не только в этом репозитории.

После `uv tool install` чекаута рядом нет. Если навыки не едут вместе с
пакетом, `doctor` в чужом проекте показывает «Навыки: (нет)» — заявленная
часть системы просто отсутствует.
"""

from __future__ import annotations

import zipfile

import pytest


def test_skills_ship_with_the_package():
    """Навыки лежат там, где их найдёт установленный пакет."""
    from agentos.paths import package_skills

    source = package_skills()
    assert source.is_dir()
    assert any((child / "SKILL.md").exists() for child in source.iterdir() if child.is_dir())


def test_wheel_contains_the_skills(tmp_path):
    """Сборка проверяется на самой сборке, а не на чекауте."""
    import shutil
    import subprocess
    from pathlib import Path

    if shutil.which("uv") is None:
        pytest.skip("нужен uv")
    repo = Path(__file__).resolve().parent.parent.parent
    result = subprocess.run(
        ["uv", "build", "--wheel", "-o", str(tmp_path)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr
    wheel = next(tmp_path.glob("*.whl"))
    names = zipfile.ZipFile(wheel).namelist()
    assert any(name.startswith("agentos/defaults/skills/") for name in names)


def test_global_skills_are_seeded_once(tmp_path, monkeypatch):
    from agentos.config import Config

    monkeypatch.setenv("AGENTOS_GLOBAL_HOME", str(tmp_path / "global"))
    monkeypatch.setenv("AGENTOS_HOME", str(tmp_path / "var"))
    config = Config.load(tmp_path / "project")
    config.ensure_dirs()

    seeded = sorted(p.name for p in config.global_skills_dir.iterdir() if p.is_dir())
    assert seeded

    # Человек удалил навык — повторный запуск не возвращает его силой.
    import shutil

    shutil.rmtree(config.global_skills_dir / seeded[0])
    config.ensure_dirs()
    assert not (config.global_skills_dir / seeded[0]).exists()


def test_seeding_does_not_overwrite_edits(tmp_path, monkeypatch):
    from agentos.config import Config

    monkeypatch.setenv("AGENTOS_GLOBAL_HOME", str(tmp_path / "global"))
    monkeypatch.setenv("AGENTOS_HOME", str(tmp_path / "var"))
    config = Config.load(tmp_path / "project")
    config.ensure_dirs()

    skill = next(p for p in config.global_skills_dir.iterdir() if p.is_dir())
    body = skill / "SKILL.md"
    body.write_text("моя правка", encoding="utf-8")
    config.ensure_dirs()
    assert body.read_text(encoding="utf-8") == "моя правка"
