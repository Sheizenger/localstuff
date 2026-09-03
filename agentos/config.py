"""Загрузка конфигурации AgentOS.

Один объект `Config` собирает agentos.yaml, models.yaml, policy.yaml, mcp.json
и роли из config/agents/. Код никогда не пишет в config/ — только читает.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

DEFAULT_CONFIG_DIR = "config"


def _repo_root() -> Path:
    """Корень проекта: там, где лежит config/ рядом с пакетом agentos/."""
    env = os.environ.get("AGENTOS_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"нет файла конфигурации: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"невалидный YAML в {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: ожидался объект на верхнем уровне")
    return data


@dataclass(frozen=True)
class ModelSpec:
    """Одна строка каталога моделей."""

    id: str
    provider: str
    tier: str
    context: int
    max_output: int
    price_in: float
    price_out: float
    supports: tuple[str, ...] = ()
    pricing_verified: bool = False

    def cost_usd(self, tokens_in: int, tokens_out: int) -> float:
        """Стоимость вызова в долларах по каталожным ценам."""
        return (tokens_in * self.price_in + tokens_out * self.price_out) / 1_000_000


@dataclass(frozen=True)
class EmbedderSpec:
    id: str
    provider: str
    dim: int
    price_in: float = 0.0
    pricing_verified: bool = False


@dataclass(frozen=True)
class RoleSpec:
    """Описание роли субагента из config/agents/<name>.yaml."""

    name: str
    title: str
    priority: str
    tier: str
    goal: str
    system: str
    selectable: bool = True
    triggers: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    memory_read: tuple[str, ...] = ()
    memory_write: tuple[str, ...] = ()
    max_output_tokens: int = 4000
    cross_provider: bool = False
    output_schema: str = ""

    @property
    def priority_rank(self) -> int:
        """P0 -> 0. Меньше — важнее. Неизвестное значение уходит в конец."""
        try:
            return int(self.priority.lstrip("Pp"))
        except ValueError:
            return 9


@dataclass
class Config:
    """Собранная конфигурация. Создаётся через Config.load()."""

    root: Path
    main: dict[str, Any]
    models: tuple[ModelSpec, ...]
    embedders: tuple[EmbedderSpec, ...]
    provider_order: tuple[str, ...]
    policy: dict[str, Any]
    mcp: dict[str, Any]
    roles: dict[str, RoleSpec] = field(default_factory=dict)

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, root: Path | str | None = None) -> Config:
        root_path = Path(root).resolve() if root else _repo_root()
        cfg_dir = root_path / os.environ.get("AGENTOS_CONFIG_DIR", DEFAULT_CONFIG_DIR)

        main = _load_yaml(cfg_dir / "agentos.yaml")
        models_doc = _load_yaml(cfg_dir / "models.yaml")
        policy = _load_yaml(cfg_dir / "policy.yaml")

        mcp_path = cfg_dir / "mcp.json"
        try:
            mcp = json.loads(mcp_path.read_text(encoding="utf-8")) if mcp_path.exists() else {}
        except json.JSONDecodeError as exc:
            raise ConfigError(f"невалидный JSON в {mcp_path}: {exc}") from exc

        models = tuple(
            ModelSpec(
                id=m["id"],
                provider=m["provider"],
                tier=m["tier"],
                context=int(m.get("context", 128000)),
                max_output=int(m.get("max_output", 4096)),
                price_in=float(m.get("price_in", 0.0)),
                price_out=float(m.get("price_out", 0.0)),
                supports=tuple(m.get("supports", ())),
                pricing_verified=bool(m.get("pricing_verified", False)),
            )
            for m in models_doc.get("models", [])
        )
        embedders = tuple(
            EmbedderSpec(
                id=e["id"],
                provider=e["provider"],
                dim=int(e.get("dim", 512)),
                price_in=float(e.get("price_in", 0.0)),
                pricing_verified=bool(e.get("pricing_verified", False)),
            )
            for e in models_doc.get("embeddings", [])
        )
        order = tuple(models_doc.get("defaults", {}).get("provider_order", ["mock"]))

        roles: dict[str, RoleSpec] = {}
        for path in sorted((cfg_dir / "agents").glob("*.yaml")):
            doc = _load_yaml(path)
            mem = doc.get("memory") or {}
            role = RoleSpec(
                name=doc["name"],
                title=doc.get("title", doc["name"]),
                priority=str(doc.get("priority", "P2")),
                tier=str(doc.get("tier", "small")),
                goal=str(doc.get("goal", "")).strip(),
                system=str(doc.get("system", "")).strip(),
                selectable=bool(doc.get("selectable", True)),
                triggers=tuple(doc.get("triggers", ())),
                tools=tuple(doc.get("tools", ())),
                memory_read=tuple(mem.get("read", ())),
                memory_write=tuple(mem.get("write", ())),
                max_output_tokens=int(doc.get("max_output_tokens", 4000)),
                cross_provider=bool(doc.get("cross_provider", False)),
                output_schema=str(doc.get("output_schema", "")),
            )
            if role.name in roles:
                raise ConfigError(f"дублирующаяся роль: {role.name} ({path})")
            roles[role.name] = role

        if not roles:
            raise ConfigError(f"не найдено ни одной роли в {cfg_dir / 'agents'}")

        return cls(
            root=root_path,
            main=main,
            models=models,
            embedders=embedders,
            provider_order=order,
            policy=policy,
            mcp=mcp,
            roles=roles,
        )

    # ------------------------------------------------------------- accessors
    def get(self, dotted: str, default: Any = None) -> Any:
        """Достать значение по пути вида 'budget.mission_tokens'."""
        node: Any = self.main
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def home(self) -> Path:
        """Каталог рантайм-состояния (var/). Создаётся при init."""
        env = os.environ.get("AGENTOS_HOME")
        raw = env or str(self.get("home", "./var"))
        path = Path(raw)
        return path.resolve() if path.is_absolute() else (self.root / path).resolve()

    @property
    def db_path(self) -> Path:
        return self.home / str(self.get("memory.db", "agentos.db"))

    @property
    def events_dir(self) -> Path:
        return self.home / str(self.get("memory.events_dir", "events"))

    @property
    def artifacts_dir(self) -> Path:
        return self.home / str(self.get("memory.artifacts_dir", "artifacts"))

    @property
    def runs_dir(self) -> Path:
        return self.home / "runs"

    def models_for_tier(self, tier: str) -> list[ModelSpec]:
        """Модели тира в порядке предпочтения провайдеров."""
        rank = {p: i for i, p in enumerate(self.provider_order)}
        found = [m for m in self.models if m.tier == tier]
        return sorted(found, key=lambda m: rank.get(m.provider, len(rank)))

    def embedder(self, embedder_id: str | None = None) -> EmbedderSpec:
        wanted = embedder_id or str(self.get("memory.vector.embedder", "hashing-local"))
        for e in self.embedders:
            if e.id == wanted:
                return e
        raise ConfigError(f"эмбеддер не найден в каталоге: {wanted}")

    def role(self, name: str) -> RoleSpec:
        try:
            return self.roles[name]
        except KeyError:
            known = ", ".join(sorted(self.roles))
            raise ConfigError(f"роль не найдена: {name}. Известные: {known}") from None

    def selectable_roles(self) -> list[RoleSpec]:
        """Роли, которые планировщик вправе назначать задачам."""
        return sorted(
            (r for r in self.roles.values() if r.selectable),
            key=lambda r: (r.priority_rank, r.name),
        )

    def ensure_dirs(self) -> None:
        """Создать рантайм-каталоги. Идемпотентно."""
        for path in (self.home, self.events_dir, self.artifacts_dir, self.runs_dir):
            path.mkdir(parents=True, exist_ok=True)
