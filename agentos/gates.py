"""Определение программных гейтов чужого проекта.

Умолчания AgentOS — `make test` и `make lint`: они верны для этого
репозитория и неверны для всех остальных. В проекте без Makefile такой
гейт падает не потому, что работа плохая, а потому, что команды не
существует, — и миссия не закрывается никогда, потому что красный гейт
переспорить нельзя. Поэтому при установке гейты определяются по проекту.

Если ничего не нашлось, гейтов нет вовсе: пустой список честнее команды,
которой нет. Приёмка тогда держится на критериях и вердикте — а человек
видит в конфиге место, куда вписать свои команды.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

#: Гейт запускается, только когда задача трогала код.
WHEN_CODE = "artifacts_touch_code"


@dataclass(frozen=True)
class Gate:
    name: str
    cmd: str
    applies_when: str = WHEN_CODE

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "cmd": self.cmd, "applies_when": self.applies_when}


def _make_targets(makefile: Path) -> set[str]:
    """Цели Makefile — только объявленные, без содержимого рецептов."""
    targets: set[str] = set()
    for line in makefile.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(("\t", " ", "#")):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-/ ]+):(?!=)", line)
        if match:
            targets.update(part for part in match.group(1).split() if part)
    return targets


def _json_scripts(package_json: Path) -> dict[str, str]:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = data.get("scripts")
    return {str(k): str(v) for k, v in scripts.items()} if isinstance(scripts, dict) else {}


def detect(root: Path) -> list[Gate]:
    """Чем в этом проекте проверяют результат. Порядок — от точного к общему."""
    root = Path(root)
    gates: list[Gate] = []

    makefile = next(
        (root / name for name in ("Makefile", "makefile") if (root / name).exists()), None
    )
    if makefile is not None:
        targets = _make_targets(makefile)
        if "test" in targets:
            gates.append(Gate("tests", "make test"))
        if "lint" in targets:
            gates.append(Gate("lint", "make lint"))
        if "check" in targets and not gates:
            gates.append(Gate("check", "make check"))
        if gates:
            return gates

    package_json = root / "package.json"
    if package_json.exists():
        scripts = _json_scripts(package_json)
        runner = "npm run"
        if (root / "pnpm-lock.yaml").exists():
            runner = "pnpm run"
        elif (root / "yarn.lock").exists():
            runner = "yarn"
        if "test" in scripts:
            gates.append(Gate("tests", "npm test" if runner == "npm run" else f"{runner} test"))
        if "lint" in scripts:
            gates.append(Gate("lint", f"{runner} lint"))
        if gates:
            return gates

    if (root / "Cargo.toml").exists():
        return [Gate("tests", "cargo test"), Gate("lint", "cargo clippy -- -D warnings")]

    if (root / "go.mod").exists():
        return [Gate("tests", "go test ./..."), Gate("lint", "go vet ./...")]

    if (root / "pyproject.toml").exists() or (root / "setup.cfg").exists():
        if (root / "tests").is_dir() or list(root.glob("test_*.py")):
            gates.append(Gate("tests", "pytest -q"))
        if (root / "pyproject.toml").exists():
            text = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
            if "[tool.ruff" in text:
                gates.append(Gate("lint", "ruff check ."))
        return gates

    return gates


def render_config(gates: list[Gate]) -> str:
    """Кусок YAML для .agentos/config/agentos.yaml."""
    if not gates:
        return (
            "# Программные гейты не определились: в проекте не нашлось ни Makefile\n"
            "# с целью test, ни package.json со скриптом test, ни Cargo/go/pytest.\n"
            "# Пустой список — сознательный выбор: команда, которой нет, красит\n"
            "# приёмку в красный навсегда. Впишите сюда свои команды, когда они\n"
            "# появятся, — и приёмка снова станет доказательством, а не мнением.\n"
            "self_check:\n"
            "  programmatic_gates: []\n"
        )
    lines = [
        "# Чем проверяется результат в этом проекте — определено при установке.",
        "# Красный гейт отменяет любой вердикт, включая вердикт модели.",
        "self_check:",
        "  programmatic_gates:",
    ]
    for gate in gates:
        lines += [
            f"    - name: {gate.name}",
            f'      cmd: "{gate.cmd}"',
            f"      applies_when: {gate.applies_when}",
        ]
    return "\n".join(lines) + "\n"
