"""Где AgentOS ищет конфиг, состояние и знание.

Раньше всё лежало рядом с самим репозиторием AgentOS, поэтому система
работала только внутри себя. Чтобы её можно было поставить один раз и
подключать к любому проекту, пути разведены на три уровня:

  пакет      agentos/defaults/    настройки по умолчанию, едут вместе с кодом
  общий      ~/.agentos/          знание и навыки, применимые в любом проекте
  проектный  <проект>/.agentos/   состояние и факты про конкретный репозиторий

Правило разделения простое: что верно про этот репозиторий — остаётся в нём;
чему агент научился про работу вообще — переезжает с ним в следующий проект.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Каталог, который AgentOS создаёт внутри проекта.
PROJECT_DIR = ".agentos"

#: Маркеры корня проекта, в порядке убывания надёжности.
ROOT_MARKERS = (PROJECT_DIR, ".git", "pyproject.toml", "package.json", "go.mod", "Cargo.toml")


def package_defaults() -> Path:
    """Настройки по умолчанию внутри установленного пакета."""
    return Path(__file__).resolve().parent / "defaults"


def find_project_root(start: Path | str | None = None) -> Path:
    """Найти корень проекта, поднимаясь вверх до первого маркера.

    Без маркеров — текущий каталог: агент, запущенный в произвольной папке,
    должен работать в ней, а не молча писать состояние куда-то выше.
    """
    env = os.environ.get("AGENTOS_ROOT")
    if env:
        return Path(env).expanduser().resolve()

    current = Path(start).resolve() if start else Path.cwd().resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return current


def project_home(root: Path) -> Path:
    """Каталог AgentOS внутри проекта: <проект>/.agentos.

    Внутри две части с разной судьбой: config/ коммитится вместе с проектом,
    var/ — рантайм и в git не попадает.
    """
    env = os.environ.get("AGENTOS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (root / PROJECT_DIR).resolve()


def project_state(root: Path) -> Path:
    """Рантайм-состояние проекта: <проект>/.agentos/var."""
    return project_home(root) / "var"


def global_state() -> Path:
    """Рантайм общего уровня: ~/.agentos/var."""
    return global_home() / "var"


def global_home() -> Path:
    """Общий каталог: ~/.agentos.

    Здесь живёт то, что переезжает между проектами: уроки, навыки,
    предпочтения человека.
    """
    env = os.environ.get("AGENTOS_GLOBAL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / PROJECT_DIR).resolve()


def config_layers(root: Path) -> list[Path]:
    """Каталоги конфигурации от общего к частному.

    Более поздний слой переопределяет более ранний: настройки пакета,
    затем общие пользовательские, затем настройки конкретного проекта.
    """
    layers = [package_defaults()]

    # Собственный config/ репозитория AgentOS — исторический слой, чтобы
    # разработка самой системы не требовала возиться с .agentos/.
    legacy = root / "config"
    if legacy.is_dir():
        layers.append(legacy)

    layers.append(global_home() / "config")
    layers.append(project_home(root) / "config")
    return [path for path in layers if path.is_dir()]


#: Владелец миссий по умолчанию, когда мастер-агент не назвался.
DEFAULT_AGENT_ID = "default"


def agent_id() -> str:
    """Кто ведёт эти миссии.

    Мастер-агентов может быть несколько — разные чаты под разные задачи в
    одном проекте. Каждый подхватывает только свои миссии, иначе два чата
    начали бы растаскивать работу друг друга.
    """
    value = os.environ.get("AGENTOS_AGENT_ID", "").strip()
    return value or DEFAULT_AGENT_ID
