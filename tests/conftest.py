"""Общие фикстуры.

Каждый тест получает изолированное состояние и детерминированный
mock-провайдер: тесты не должны видеть ни чужую память, ни сеть, ни ключи.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Изолировать состояние и включить mock до создания любого Runtime."""
    import shutil

    # Навыки — копия репозиторных: тесты предлагают и активируют черновики,
    # и не должны для этого править рабочее дерево.
    skills_copy = tmp_path / "skills"
    shutil.copytree(REPO_ROOT / "skills", skills_copy)
    monkeypatch.setenv("AGENTOS_SKILLS_DIR", str(skills_copy))
    monkeypatch.setenv("AGENTOS_HOME", str(tmp_path / "var"))
    monkeypatch.setenv("AGENTOS_ALLOW_MOCK", "1")
    monkeypatch.setenv("AGENTOS_MODE", "direct")
    monkeypatch.setenv("AGENTOS_MOCK_STATE", str(tmp_path / "mock_calls.txt"))
    # Тесты сами запускаются гейтом `make test`; без этой метки миссия внутри
    # теста снова позвала бы make test и ушла в бесконечную рекурсию.
    monkeypatch.setenv("AGENTOS_IN_GATE", "1")
    monkeypatch.delenv("AGENTOS_MOCK_FAULTS", raising=False)
    # Ключи реальных провайдеров не должны просачиваться в тесты.
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    from agentos.providers.registry import reset_cache

    reset_cache()
    yield


@pytest.fixture
def config():
    from agentos.config import Config

    return Config.load(REPO_ROOT)


@pytest.fixture
def store(tmp_path):
    from agentos.memory.store import Store

    db = Store(tmp_path / "test.db")
    yield db
    db.close()


@pytest.fixture
def runtime():
    from agentos.runtime import Runtime

    rt = Runtime.open(REPO_ROOT)
    yield rt
    rt.close()


@pytest.fixture
def sm(store):
    from agentos.state.machine import StateMachine

    return StateMachine(store)
