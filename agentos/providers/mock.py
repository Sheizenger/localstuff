"""Детерминированный провайдер для тестов, E2E и работы без ключей.

Он не «заглушка ради компиляции»: на нём проходит полный сценарий миссии,
включая планирование, отчёты субагентов и вердикт критика. Плюс управляемые
сбои — без них невозможно проверить главное свойство системы: продолжение
работы после исчерпания лимитов и после краша.

Управление через окружение:
  AGENTOS_MOCK_STATE      файл-счётчик вызовов (нужен, чтобы сбой пережил краш)
  AGENTOS_MOCK_FAULTS     JSON: [{"at": 3, "type": "quota", "reset_in": 0}]
                          "at" — точный номер вызова, "after" — все вызовы
                          начиная с этого номера;
                          типы: quota | ratelimit | transient | overflow
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from ..errors import ContextOverflow, QuotaExhausted, RateLimited, TransientProviderError
from .base import Completion, Message, Provider, ToolSpec, Usage

#: Маркеры, по которым mock понимает, какой ответ от него ждут.
SCHEMA_MARKER = "ФОРМАТ ОТВЕТА:"


class MockProvider(Provider):
    name = "mock"
    env_keys = ()

    #: Счётчик общий на процесс: планировщик исполняет ветки DAG в потоках,
    #: и без блокировки два потока получали бы один и тот же номер вызова —
    #: сбой «на N-м вызове» тогда молча пропускался бы.
    _counter_lock = threading.Lock()

    def __init__(self) -> None:
        self._calls = 0

    # ------------------------------------------------------------ управление
    @property
    def _state_path(self) -> Path | None:
        raw = os.environ.get("AGENTOS_MOCK_STATE")
        return Path(raw) if raw else None

    def _bump(self) -> int:
        """Счётчик вызовов. На диске — чтобы сбой воспроизводился после краша."""
        with self._counter_lock:
            path = self._state_path
            if path is None:
                self._calls += 1
                return self._calls
            try:
                current = int(path.read_text().strip() or "0")
            except (OSError, ValueError):
                current = 0
            current += 1
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(current))
            except OSError:
                pass
            return current

    def _maybe_fail(self, call_no: int, model: str) -> None:
        raw = os.environ.get("AGENTOS_MOCK_FAULTS", "")
        if not raw:
            return
        try:
            faults = json.loads(raw)
        except json.JSONDecodeError:
            return
        for fault in faults:
            exact = int(fault.get("at", -1)) == call_no
            after = "after" in fault and call_no >= int(fault["after"])
            if not (exact or after):
                continue
            kind = fault.get("type", "transient")
            if kind == "quota":
                raise QuotaExhausted(
                    "mock: лимит токенов исчерпан",
                    reset_at=time.time() + float(fault.get("reset_in", 0)),
                    provider=self.name,
                    model=model,
                )
            if kind == "ratelimit":
                raise RateLimited(
                    "mock: rate limit",
                    retry_after_s=float(fault.get("retry_after", 1)),
                    provider=self.name,
                    model=model,
                )
            if kind == "overflow":
                raise ContextOverflow("mock: контекст переполнен", provider=self.name, model=model)
            raise TransientProviderError("mock: временный сбой", provider=self.name, model=model)

    # -------------------------------------------------------------- контракт
    def available(self) -> bool:
        return True

    def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        system: str = "",
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
        stop: list[str] | None = None,
    ) -> Completion:
        call_no = self._bump()
        self._maybe_fail(call_no, model)

        prompt = system + "\n" + "\n".join(m.as_text() for m in messages)
        schema = self._wanted_schema(prompt)
        text = self._render(schema, prompt, call_no)

        # Токены считаем грубо (4 символа ≈ токен) — леджеру нужен порядок, не точность.
        return Completion(
            text=text,
            tool_calls=[],
            usage=Usage(tokens_in=len(prompt) // 4, tokens_out=len(text) // 4),
            stop_reason="end_turn",
            model=model,
            provider=self.name,
            raw={"call_no": call_no},
        )

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        from ..memory.vector import hash_embed

        return [hash_embed(t, dim=512) for t in texts]

    # ---------------------------------------------------------------- ответы
    @staticmethod
    def _wanted_schema(prompt: str) -> str:
        if SCHEMA_MARKER not in prompt:
            return "text"
        tail = prompt.split(SCHEMA_MARKER, 1)[1].strip().splitlines()
        return tail[0].strip() if tail else "text"

    def _render(self, schema: str, prompt: str, call_no: int) -> str:
        if schema == "task_dag":
            return json.dumps(self._plan(prompt), ensure_ascii=False, indent=2)
        if schema == "verdict":
            return json.dumps(self._verdict(prompt), ensure_ascii=False, indent=2)
        if schema == "report":
            return json.dumps(self._report(prompt, call_no), ensure_ascii=False, indent=2)
        if schema == "mission_spec":
            return json.dumps(self._mission_spec(prompt), ensure_ascii=False, indent=2)
        if schema == "lessons":
            return json.dumps(self._lessons(prompt), ensure_ascii=False, indent=2)
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
        return f"mock-ответ #{call_no} ({digest})"

    @staticmethod
    def _mission_spec(prompt: str) -> dict[str, Any]:
        goal = MockProvider._goal_of(prompt)
        return {
            "restated_goal": goal,
            "assumptions": ["выполняется на mock-провайдере, без внешних вызовов"],
            "questions": [],
            "acceptance_criteria": [
                {"criterion": f"результат отвечает цели: {goal}", "kind": "semantic"},
                {"criterion": "программные гейты зелёные", "kind": "programmatic", "cmd": "true"},
            ],
        }

    @staticmethod
    def _plan(prompt: str) -> dict[str, Any]:
        """Небольшой, но настоящий DAG: две параллельные ветки и сборка."""
        goal = MockProvider._goal_of(prompt)
        return {
            "tasks": [
                {
                    "key": "research",
                    "title": f"Собрать вводные: {goal}",
                    "role": "researcher",
                    "tier": "small",
                    "priority": 1,
                    "est_tokens": 3000,
                    "depends_on": [],
                    "instructions": "Собери факты и верни выжимку.",
                },
                {
                    "key": "env",
                    "title": "Проверить окружение и гейты",
                    "role": "ops",
                    "tier": "nano",
                    "priority": 2,
                    "est_tokens": 1500,
                    "depends_on": [],
                    "instructions": "Убедись, что тесты и линт запускаются.",
                },
                {
                    "key": "build",
                    "title": f"Сделать результат: {goal}",
                    "role": "coder",
                    "tier": "large",
                    "priority": 1,
                    "est_tokens": 8000,
                    "depends_on": ["research", "env"],
                    "instructions": "Собери итоговый артефакт по выжимке.",
                },
            ]
        }

    @staticmethod
    def _report(prompt: str, call_no: int) -> dict[str, Any]:
        return {
            "summary": f"задача выполнена (mock-вызов #{call_no})",
            "findings": ["mock-провайдер не обращается к сети"],
            "artifacts": [],
            "next_steps": [],
            "confidence": 0.9,
        }

    @staticmethod
    def _verdict(prompt: str) -> dict[str, Any]:
        # Если в контексте есть красный гейт — критик обязан отклонить.
        failed = "gate:fail" in prompt or "ГЕЙТ ПРОВАЛЕН" in prompt
        return {
            "verdict": "reject" if failed else "accept",
            "criteria": [],
            "reasons": ["программный гейт красный"] if failed else [],
            "next_actions": ["починить гейт"] if failed else [],
        }

    @staticmethod
    def _lessons(prompt: str) -> dict[str, Any]:
        return {
            "facts": [{"subject": "mock", "content": "прогон выполнен на mock-провайдере"}],
            "lessons": [],
            "skill_candidates": [],
        }

    @staticmethod
    def _goal_of(prompt: str) -> str:
        for line in prompt.splitlines():
            if line.startswith("ЦЕЛЬ:"):
                return line.split(":", 1)[1].strip()
        return "цель не указана"
