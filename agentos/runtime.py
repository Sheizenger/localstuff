"""Сборка системы: один объект, из которого доступны все подсистемы.

Без него каждый модуль тащил бы десяток зависимостей в сигнатуре. Runtime
создаётся один раз на процесс — и в CLI, и в тестах.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .bus import EventBus
from .config import Config
from .memory.artifacts import ArtifactStore
from .memory.episodic import EpisodicMemory
from .memory.procedural import SkillLibrary
from .memory.semantic import SemanticMemory
from .memory.store import Store
from .memory.vector import Embedder
from .memory.working import WorkingMemory
from .policy.guard import PolicyGuard
from .providers.registry import real_providers_configured
from .providers.router import Router
from .state.approvals import ApprovalQueue
from .state.checkpoint import Checkpointer
from .state.machine import StateMachine
from .telemetry.ledger import Ledger
from .telemetry.quota import QuotaTracker
from .tools.base import ToolRegistry
from .tools.fs import build_fs_tools
from .tools.http import build_http_tools
from .tools.shell import build_shell_tools

MODE_NATIVE = "native"
MODE_DIRECT = "direct"


@dataclass
class Runtime:
    config: Config
    store: Store

    # ------------------------------------------------------------- создание
    @classmethod
    def open(cls, root: Path | str | None = None) -> Runtime:
        config = Config.load(root)
        config.ensure_dirs()
        return cls(config=config, store=Store(config.db_path))

    def close(self) -> None:
        if "capabilities" in self.__dict__:
            self.capabilities.shutdown()
        self.store.close()

    def __enter__(self) -> Runtime:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ подсистемы
    @cached_property
    def guard(self) -> PolicyGuard:
        return PolicyGuard(self.config.policy, self.config.root)

    @cached_property
    def bus(self) -> EventBus:
        return EventBus(self.store, self.config.events_dir, self.guard.redactor)

    @cached_property
    def sm(self) -> StateMachine:
        return StateMachine(self.store)

    @cached_property
    def approvals(self) -> ApprovalQueue:
        return ApprovalQueue(self.store)

    @cached_property
    def ledger(self) -> Ledger:
        return Ledger(self.store, self.config)

    @cached_property
    def quota(self) -> QuotaTracker:
        return QuotaTracker(
            self.store, float(self.config.get("quota.default_cooldown_s", 900))
        )

    @cached_property
    def router(self) -> Router:
        return Router(self.config, self.quota)

    @cached_property
    def embedder(self) -> Embedder:
        return Embedder(self.config, self.router)

    @cached_property
    def semantic(self) -> SemanticMemory:
        return SemanticMemory(self.store, self.embedder, self.config)

    @cached_property
    def episodic(self) -> EpisodicMemory:
        return EpisodicMemory(self.store)

    @cached_property
    def skills(self) -> SkillLibrary:
        # AGENTOS_SKILLS_DIR позволяет увести навыки в отдельный каталог —
        # это нужно тестам и параллельным прогонам, чтобы они не писали
        # черновики в общий skills/ репозитория.
        override = os.environ.get("AGENTOS_SKILLS_DIR")
        path = Path(override) if override else self.config.root / "skills"
        return SkillLibrary(self.store, path)

    @cached_property
    def artifacts(self) -> ArtifactStore:
        return ArtifactStore(self.store, self.config.artifacts_dir)

    @cached_property
    def working(self) -> WorkingMemory:
        return WorkingMemory(self.config, self.semantic, self.episodic, self.skills)

    @cached_property
    def checkpointer(self) -> Checkpointer:
        return Checkpointer(self.store, self.config.runs_dir, self.config.home)

    @cached_property
    def capabilities(self):
        """Резолвер возможностей: MCP-серверы, навыки, доступы."""
        from .tools.capability import CapabilityResolver

        return CapabilityResolver(self)

    @cached_property
    def tools(self) -> ToolRegistry:
        from .tools.capability import build_capability_tools

        registry = ToolRegistry(self.bus)
        registry.register_all(build_fs_tools(self.guard, self.config.root))
        registry.register_all(build_shell_tools(self.guard, self.config.root))
        registry.register_all(build_http_tools(self.guard))
        registry.register_all(self._memory_tools())
        # MCP-серверы здесь не поднимаются: они включаются по требованию
        # через capability_request, чтобы старт не платил за весь каталог.
        registry.register_all(build_capability_tools(self.capabilities))
        return registry

    def _memory_tools(self):
        """Инструменты памяти: без них субагент не увидит знания проекта."""
        from .tools.base import Tool, ToolResult

        def memory_search(query: str, limit: int = 8) -> ToolResult:
            facts = self.semantic.search(query, limit=limit)
            if not facts:
                return ToolResult(True, output="(в памяти ничего не найдено)")
            return ToolResult(True, output="\n".join(f.as_line() for f in facts))

        def memory_write(content: str, subject: str = "", kind: str = "fact") -> ToolResult:
            fact_id = self.semantic.add(content, subject=subject, kind=kind, source="агент")
            return ToolResult(bool(fact_id), output=f"записано: {fact_id}")

        def skill_load(name: str) -> ToolResult:
            skill = self.skills.load(name)
            if skill is None:
                return ToolResult(False, error=f"нет такого навыка: {name}")
            return ToolResult(True, output=skill.body)

        # Событие пишет сам реестр инструментов (tool.call), поэтому
        # дополнительная эмиссия здесь не нужна — mark_skill_outcomes
        # читает оба источника.

        return [
            Tool(
                "memory_search",
                "Найти в памяти проекта факты, уроки и решения.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
                memory_search,
            ),
            Tool(
                "memory_write",
                "Записать факт или урок в долговременную память проекта.",
                {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "subject": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": ["fact", "lesson", "decision", "preference"],
                        },
                    },
                    "required": ["content"],
                },
                memory_write,
            ),
            Tool(
                "skill_load",
                "Подтянуть тело навыка по имени из каталога навыков.",
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                skill_load,
            ),
        ]

    # ---------------------------------------------------------------- режим
    @property
    def mode(self) -> str:
        """native — субагентов запускает агент-хост; direct — сам AgentOS."""
        override = os.environ.get("AGENTOS_MODE")
        configured = str(override or self.config.get("runtime.mode", "auto")).lower()
        if configured in (MODE_NATIVE, MODE_DIRECT):
            return configured
        if os.environ.get("AGENTOS_ALLOW_MOCK") == "1":
            return MODE_DIRECT
        return MODE_DIRECT if real_providers_configured() else MODE_NATIVE

    def sync_skills(self) -> dict[str, int]:
        return self.skills.sync()
