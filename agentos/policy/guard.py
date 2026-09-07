"""Проверка действий по политике из config/policy.yaml.

Автономность без границ — это не автономность, а неуправляемый процесс.
Guard отвечает на три вопроса перед каждым действием:
  * разрешено ли оно вообще (иначе PolicyDenied);
  * не требует ли оно человека (иначе ApprovalRequired — и задача уходит
    в BLOCKED_APPROVAL, а остальные ветки DAG продолжают идти);
  * не утечёт ли секрет в лог (за это отвечает Redactor).
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import ApprovalRequired, PolicyDenied
from .redact import Redactor


@dataclass(frozen=True)
class ShellVerdict:
    allowed: bool
    reason: str = ""
    timeout_s: int = 300


class PolicyGuard:
    def __init__(self, policy: dict[str, Any], root: Path) -> None:
        self.policy = policy or {}
        self.root = root.resolve()
        self.redactor = Redactor.from_policy(self.policy)

    # ----------------------------------------------------------- файлы
    def _rel(self, path: Path) -> str:
        resolved = Path(path).expanduser().resolve()
        try:
            return str(resolved.relative_to(self.root))
        except ValueError:
            return str(resolved)  # вне репозитория — сравнится с deny как абсолютный

    @staticmethod
    def _matches(rel: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatch(rel, p) for p in patterns)

    def check_read(self, path: Path) -> Path:
        fs = self.policy.get("filesystem", {})
        rel = self._rel(path)
        if self._matches(rel, fs.get("write_deny", [])):
            raise PolicyDenied(f"чтение запрещено политикой: {rel}")
        allow = fs.get("read_allow", ["**"])
        if allow and not self._matches(rel, allow):
            raise PolicyDenied(f"путь вне разрешённых для чтения: {rel}")
        return Path(path)

    def check_write(self, path: Path) -> Path:
        """Запись разрешена только в явно перечисленные места.

        Всё, что вне write_allow, — это изменение проекта, за которое
        отвечает человек: такое действие уходит на подтверждение.
        """
        fs = self.policy.get("filesystem", {})
        rel = self._rel(path)
        if self._matches(rel, fs.get("write_deny", [])):
            raise PolicyDenied(f"запись запрещена политикой: {rel}")
        allow = fs.get("write_allow", [])
        if allow and not self._matches(rel, allow):
            self.require_approval("write_outside_allowlist", f"запись вне разрешённых путей: {rel}")
        return Path(path)

    def max_file_bytes(self) -> int:
        return int(self.policy.get("filesystem", {}).get("max_file_bytes", 5_242_880))

    # ----------------------------------------------------------- команды
    def check_shell(self, command: str) -> ShellVerdict:
        shell = self.policy.get("shell", {})
        if not shell.get("enabled", True):
            return ShellVerdict(False, "выполнение команд отключено политикой")
        for pattern in shell.get("deny_patterns", []):
            if re.search(pattern, command):
                return ShellVerdict(False, f"команда попадает под запрет: {pattern}")
        allow = shell.get("allow_binaries", [])
        if allow:
            for segment in _split_pipeline(command):
                try:
                    binary = (shlex.split(segment) or [""])[0]
                except ValueError:
                    return ShellVerdict(False, "не удалось разобрать команду")
                name = Path(binary).name
                if name and name not in allow:
                    return ShellVerdict(
                        False, f"бинарь '{name}' не в allow_binaries политики"
                    )
        return ShellVerdict(True, timeout_s=int(shell.get("timeout_s", 300)))

    # ------------------------------------------------------------- сеть
    def check_host(self, host: str) -> None:
        network = self.policy.get("network", {})
        if not network.get("enabled", True):
            raise PolicyDenied("сетевые вызовы отключены политикой")
        for denied in network.get("deny_hosts", []):
            if fnmatch.fnmatch(host, denied):
                raise PolicyDenied(f"хост запрещён политикой: {host}")
        allow = network.get("allow_hosts", [])
        if allow and not any(fnmatch.fnmatch(host, a) for a in allow):
            raise PolicyDenied(f"хост вне allow_hosts: {host}")

    # -------------------------------------------------------- подтверждения
    def approval_rules(self) -> tuple[set[str], float]:
        """Список действий, требующих человека, и денежный порог."""
        raw = (self.policy.get("approval", {}) or {}).get("require_human", []) or []
        actions: set[str] = set()
        spend_limit = float("inf")
        for item in raw:
            if isinstance(item, str):
                actions.add(item)
            elif isinstance(item, dict):
                for key, value in item.items():
                    if key == "spend_over_usd":
                        spend_limit = float(value)
                    else:
                        actions.add(key)
        return actions, spend_limit

    def needs_approval(self, action: str) -> bool:
        actions, _ = self.approval_rules()
        return action in actions

    def require_approval(self, action: str, detail: str = "") -> None:
        """Бросить ApprovalRequired, если действие в списке требующих человека."""
        if self.needs_approval(action):
            raise ApprovalRequired(action, detail)

    def check_spend(self, usd: float) -> None:
        _actions, limit = self.approval_rules()
        if usd > limit:
            raise ApprovalRequired(
                "spend_over_usd", f"планируемый расход ${usd:.2f} выше порога ${limit:.2f}"
            )

    # ------------------------------------------------------------- секреты
    def redact(self, value: Any) -> Any:
        return self.redactor.apply(value)


def _split_pipeline(command: str) -> list[str]:
    """Разбить строку на команды по |, &&, ||, ; — проверяем каждую."""
    parts = re.split(r"\|\||&&|[|;]", command)
    return [p.strip() for p in parts if p.strip()]
