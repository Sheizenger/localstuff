"""Подключение AgentOS к чужому воркспейсу.

Задача одна: человек ставит инструмент один раз, а дальше в любом проекте
говорит `agentctl install` — и все агенты, которых он там заводит, работают
по одному контракту, чей бы CLI ни был запущен.

Всё, что пишется, пишется идемпотентно и без затирания чужого: markdown
правится между маркерами, JSON сливается по ключам, а невалидный чужой файл
не переписывается, а становится предупреждением. Повторный запуск —
безопасная операция, ею же обновляются точки входа после апгрейда.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contract import render_markdown
from .paths import PROJECT_DIR

BEGIN = "<!-- agentos:begin -->"
END = "<!-- agentos:end -->"

#: Куда пишем точки входа. Ключ — имя платформы для --platform.
PLATFORMS = ("claude", "codex", "gemini", "cursor")

CONFIG_STUB = """# Настройки AgentOS для этого проекта.
#
# Здесь описываются только отличия от умолчаний: конфигурация собирается
# слоями (пакет -> ~/.agentos -> этот файл), поэтому копировать всё целиком
# не нужно. Полный список параметров: agentctl doctor и документация.

# runtime:
#   max_concurrency: 4        # сколько задач исполнять параллельно
#
# budget:
#   mission_tokens: 2000000   # потолок на миссию
#
# self_check:
#   programmatic_gates:       # чем проверяется результат в этом проекте
#     - name: tests
#       cmd: "make test"
"""


@dataclass
class InstallReport:
    """Что именно сделала установка — печатается человеку."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)

    def note(self, path: Path, root: Path, existed: bool, changed: bool) -> None:
        rel = _rel(path, root)
        if not existed:
            self.created.append(rel)
        elif changed:
            self.updated.append(rel)
        else:
            self.unchanged.append(rel)


def _already_full_contract(path: Path) -> bool:
    """Есть ли в файле развёрнутый контракт, написанный руками."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if BEGIN in text:
        return False  # это наш блок, его и обновляем
    return "agentctl task report" in text and "agentctl resume" in text


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def server_command() -> list[str]:
    """Чем хост будет запускать MCP-сервер.

    Имя без пути, а не результат which: .mcp.json обычно коммитится и
    уезжает команде, а абсолютный путь с машины того, кто запустил install,
    у остальных не существует. Если инструмент не установлен — честно зовём
    текущий интерпретатор, и такой файл коммитить уже не стоит.
    """
    if shutil.which("agentctl"):
        return ["agentctl", "mcp"]
    return [sys.executable, "-m", "agentos.cli", "mcp"]


# --------------------------------------------------------------- примитивы


#: Frontmatter правила Cursor. Без alwaysApply правило считается
#: «подключаемым по требованию», и агент его просто не увидит.
CURSOR_FRONTMATTER = (
    "---\n"
    "description: AgentOS — контракт работы агентов в этом проекте\n"
    "alwaysApply: true\n"
    "---\n\n"
)


def preamble_for(path: Path) -> str:
    """Что должно стоять до блока, чтобы платформа его учла."""
    return CURSOR_FRONTMATTER if path.suffix == ".mdc" else ""


def write_marked_block(
    path: Path, body: str, *, title: str = "", preamble: str = ""
) -> tuple[bool, bool]:
    """Вписать блок между маркерами. Возвращает (существовал, изменился).

    Чужой текст в файле не трогается: правится только то, что между
    маркерами, а при первой установке блок дописывается в конец.
    """
    block = f"{BEGIN}\n{body}\n{END}"
    existed = path.exists()
    if not existed:
        header = f"# {title}\n\n" if title and not preamble else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{preamble}{header}{block}\n", encoding="utf-8")
        return False, True

    text = path.read_text(encoding="utf-8")
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _old, tail = rest.split(END, 1)
        updated = f"{head}{block}{tail}"
    else:
        separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        updated = f"{text}{separator}{block}\n"

    if updated == text:
        return True, False
    path.write_text(updated, encoding="utf-8")
    return True, True


def merge_json(path: Path, patch: dict[str, Any]) -> tuple[bool, bool, str]:
    """Слить patch в JSON-файл. Возвращает (существовал, изменился, проблема)."""
    existed = path.exists()
    current: dict[str, Any] = {}
    if existed:
        try:
            raw = path.read_text(encoding="utf-8").strip()
            current = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            return True, False, f"{path.name}: невалидный JSON ({exc}) — не трогаю"
        if not isinstance(current, dict):
            return True, False, f"{path.name}: ожидался объект — не трогаю"

    merged = _deep_merge(current, patch)
    if merged == current:
        return existed, False, ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return existed, True, ""


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _deep_merge(current, value)
        elif isinstance(current, list) and isinstance(value, list):
            # Хуки и подобные списки: не дублируем то, что уже есть.
            result[key] = current + [item for item in value if item not in current]
        else:
            result[key] = value
    return result


def ensure_gitignore(root: Path, entry: str) -> tuple[bool, bool]:
    path = root / ".gitignore"
    existed = path.exists()
    lines = path.read_text(encoding="utf-8").splitlines() if existed else []
    if entry in {line.strip() for line in lines}:
        return existed, False
    block = ["", "# AgentOS: рантайм-состояние", entry] if lines else ["# AgentOS", entry]
    path.write_text("\n".join([*lines, *block]) + "\n", encoding="utf-8")
    return existed, True


# ------------------------------------------------------------------ сборка


def install(
    root: Path,
    *,
    platforms: tuple[str, ...] = PLATFORMS,
    with_mcp: bool = True,
) -> InstallReport:
    """Подключить AgentOS к проекту в root. Идемпотентно."""
    report = InstallReport()
    root = root.resolve()
    # Именно root / .agentos, а не project_home(): установка целится в
    # указанный каталог, и переменная AGENTOS_HOME (она про запуск, а не про
    # установку) не должна уводить файлы в сторону.
    home = root / PROJECT_DIR

    # 1. Каталог проекта и заготовка конфига.
    (home / "config").mkdir(parents=True, exist_ok=True)
    (home / "var").mkdir(parents=True, exist_ok=True)
    stub = home / "config" / "agentos.yaml"
    if not stub.exists():
        stub.write_text(CONFIG_STUB, encoding="utf-8")
        report.created.append(_rel(stub, root))
    else:
        report.unchanged.append(_rel(stub, root))

    existed, changed = ensure_gitignore(root, f"{PROJECT_DIR}/var/")
    report.note(root / ".gitignore", root, existed, changed)

    # 2. Точки входа. AGENTS.md пишется всегда: его читают Codex, Cursor и
    #    прочие хосты, а также сам человек.
    # AGENTS.md пишется всегда: его читают Codex, Cursor и прочие хосты.
    # Исключение — репозиторий, где AGENTS.md уже содержит полный контракт
    # вручную: краткий блок дублировал бы его и ссылался бы сам на себя.
    entrypoints: list[tuple[Path, str]] = []
    agents_md = root / "AGENTS.md"
    if not _already_full_contract(agents_md):
        entrypoints.append((agents_md, "Инструкции для агентов"))
    if "claude" in platforms:
        entrypoints.append((root / "CLAUDE.md", "CLAUDE.md"))
    if "gemini" in platforms:
        entrypoints.append((root / "GEMINI.md", "GEMINI.md"))
    if "cursor" in platforms:
        entrypoints.append((root / ".cursor" / "rules" / "agentos.mdc", "AgentOS"))
    for path, title in entrypoints:
        existed, changed = write_marked_block(
            path, render_markdown(), title=title, preamble=preamble_for(path)
        )
        report.note(path, root, existed, changed)

    # 3. Хук старта сессии для Claude Code: подхват работы без напоминания.
    if "claude" in platforms:
        hook = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "agentctl resume --announce --quiet",
                                "timeout": 60,
                            }
                        ]
                    }
                ]
            }
        }
        existed, changed, problem = merge_json(root / ".claude" / "settings.json", hook)
        if problem:
            report.warnings.append(problem)
        else:
            report.note(root / ".claude" / "settings.json", root, existed, changed)

    # 4. Регистрация MCP-сервера — главный механизм связи.
    if with_mcp:
        command, *arguments = server_command()
        entry = {"command": command, "args": arguments, "env": {}}
        targets: list[Path] = []
        if "claude" in platforms:
            targets.append(root / ".mcp.json")
        if "cursor" in platforms:
            targets.append(root / ".cursor" / "mcp.json")
        for path in targets:
            existed, changed, problem = merge_json(path, {"mcpServers": {"agentos": entry}})
            if problem:
                report.warnings.append(problem)
            else:
                report.note(path, root, existed, changed)

        if "codex" in platforms:
            # У Codex MCP-серверы живут в пользовательском config.toml, а не в
            # проекте: писать туда за человека — залезать в его глобальные
            # настройки, поэтому даём точную строку.
            args = json.dumps(arguments, ensure_ascii=False)
            report.manual.append(
                "Codex — добавь в ~/.codex/config.toml:\n"
                f'  [mcp_servers.agentos]\n  command = "{command}"\n  args = {args}'
            )

    return report


def render_report(report: InstallReport, root: Path) -> str:
    """Что показать человеку после установки."""
    lines: list[str] = []
    for title, items in (
        ("создано", report.created),
        ("обновлено", report.updated),
        ("без изменений", report.unchanged),
    ):
        if items:
            lines.append(f"{title}: {', '.join(sorted(items))}")
    for warning in report.warnings:
        lines.append(f"⚠ {warning}")
    if report.manual:
        lines.append("")
        lines.append("Требует одного ручного шага:")
        lines += [f"  {item}" for item in report.manual]
    lines.append("")
    lines.append("Проверить: agentctl doctor")
    lines.append('Начать:    agentctl goal "твоя задача"')
    return "\n".join(lines)


def default_root() -> Path:
    return Path(os.environ.get("AGENTOS_ROOT") or Path.cwd()).resolve()
