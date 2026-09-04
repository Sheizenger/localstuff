"""Выполнение одной задачи.

Два режима с одним и тем же брифом:

  native — AgentOS готовит задание и отдаёт его агент-хосту (Claude Code,
           Codex CLI, Gemini CLI). Ключи провайдеров не нужны: субагентов
           запускает хост своим механизмом, а результат возвращает командой
           `agentctl task report`.

  direct — AgentOS сам крутит цикл tool-use через адаптер провайдера.
           Нужен ключ; используется в headless-режиме.

Любой сбой приводится к состоянию задачи, а не к исключению наверх:
кончилась квота — BLOCKED_QUOTA с временем сброса, не хватило доступа —
BLOCKED_CAPABILITY, нужно подтверждение — BLOCKED_APPROVAL. Остальные
ветки DAG при этом продолжают идти.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from ..agents.brief import render_host_brief
from ..agents.report import Report
from ..bus import (
    EV_APPROVAL_REQUEST,
    EV_CAPABILITY_REQUEST,
    EV_PROVIDER_CALL,
    EV_PROVIDER_ERROR,
    EV_QUOTA_HIT,
    EV_TASK_STARTED,
)
from ..errors import (
    ApprovalRequired,
    BudgetExceeded,
    CapabilityMissing,
    ContextOverflow,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    TransientProviderError,
)
from ..memory.working import Brief
from ..providers.base import ContentBlock, Message
from ..runtime import MODE_NATIVE, Runtime
from ..state.machine import Task

#: Потолок витков цикла инструментов на одну задачу.
MAX_TOOL_ITERATIONS = 12

STATUS_DONE = "done"
STATUS_HANDOFF = "handoff"
STATUS_BLOCKED_QUOTA = "blocked_quota"
STATUS_BLOCKED_CAPABILITY = "blocked_capability"
STATUS_BLOCKED_APPROVAL = "blocked_approval"
STATUS_FAILED = "failed"


@dataclass
class DispatchOutcome:
    status: str
    report: Report | None = None
    detail: str = ""
    resume_after: float | None = None
    provider: str = ""
    model: str = ""
    tokens: int = 0
    usd: float = 0.0
    brief_path: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_DONE


class Dispatcher:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # ------------------------------------------------------------------ вход
    def execute(self, task: Task, mission: dict[str, Any]) -> DispatchOutcome:
        role = self.rt.config.roles.get(task.role) or self.rt.config.role("researcher")
        brief = self._build_brief(task, mission, role)

        self.rt.bus.emit(
            EV_TASK_STARTED,
            mission_id=task.mission_id,
            task_id=task.id,
            actor=role.name,
            title=task.title,
            tier=role.tier,
            mode=self.rt.mode,
            brief_tokens=brief.tokens(),
        )

        if self.rt.mode == MODE_NATIVE:
            return self._handoff(task, role, brief)
        return self._run_direct(task, mission, role, brief)

    # --------------------------------------------------------------- подготовка
    def _build_brief(self, task: Task, mission: dict[str, Any], role: Any) -> Brief:
        payload = task.brief or {}
        acceptance = payload.get("acceptance") or self._mission_dod(task.mission_id)
        brief = self.rt.working.build_brief(
            mission_goal=mission.get("goal", ""),
            task_title=task.title,
            instructions=payload.get("instructions", ""),
            acceptance=acceptance,
            inputs=payload.get("inputs", []),
            constraints=payload.get("constraints", []),
            output_schema=role.output_schema or payload.get("output_schema", "report"),
        )
        # Бриф не должен съедать бюджет самой задачи: половина — потолок.
        budget = task.budget_tokens or int(self.rt.config.get("budget.mission_tokens", 0)) // 20
        if budget:
            brief = self.rt.working.fit_brief(brief, max(400, budget // 2))
        return brief

    def _mission_dod(self, mission_id: str) -> list[str]:
        rows = self.rt.store.query(
            "SELECT criterion FROM dod WHERE mission_id=? ORDER BY ord", (mission_id,)
        )
        return [r["criterion"] for r in rows]

    # ------------------------------------------------------------- native-режим
    def _handoff(self, task: Task, role: Any, brief: Brief) -> DispatchOutcome:
        """Отдать задание агент-хосту и ждать `agentctl task report`."""
        text = render_host_brief(
            brief=brief, role=role, task_id=task.id, mission_id=task.mission_id
        )
        briefs_dir = self.rt.config.runs_dir / task.mission_id / "briefs"
        briefs_dir.mkdir(parents=True, exist_ok=True)
        path = briefs_dir / f"{task.id}.md"
        path.write_text(text, encoding="utf-8")
        return DispatchOutcome(
            status=STATUS_HANDOFF,
            detail=text,
            brief_path=str(path),
            meta={"role": role.name},
        )

    # ------------------------------------------------------------- direct-режим
    def _run_direct(
        self, task: Task, mission: dict[str, Any], role: Any, brief: Brief
    ) -> DispatchOutcome:
        try:
            route = self.rt.router.pick(role.tier)
        except QuotaExhausted as exc:
            return self._on_quota(task, exc, provider="")
        except ProviderUnavailable as exc:
            return DispatchOutcome(
                status=STATUS_BLOCKED_CAPABILITY, detail=str(exc), meta={"kind": "provider"}
            )

        tools = self.rt.tools.subset(role.tools) if role.tools else self.rt.tools
        specs = tools.specs()
        messages: list[Message] = [Message.user(brief.render())]
        spent_tokens = 0
        spent_usd = 0.0
        budget = task.budget_tokens or 0

        for iteration in range(MAX_TOOL_ITERATIONS):
            if budget and spent_tokens >= budget:
                return DispatchOutcome(
                    status=STATUS_FAILED,
                    detail=f"исчерпан бюджет задачи: {spent_tokens} из {budget} токенов",
                    provider=route.spec.provider,
                    model=route.spec.id,
                    tokens=spent_tokens,
                    usd=spent_usd,
                )
            try:
                completion = route.provider.complete(
                    model=route.spec.id,
                    messages=messages,
                    system=role.system,
                    tools=specs,
                    max_tokens=min(role.max_output_tokens, route.spec.max_output),
                )
            except QuotaExhausted as exc:
                return self._on_quota(task, exc, provider=route.spec.provider)
            except RateLimited as exc:
                self.rt.quota.mark_rate_limited(
                    route.spec.provider, exc.retry_after_s, error=str(exc)
                )
                return DispatchOutcome(
                    status=STATUS_BLOCKED_QUOTA,
                    detail=f"rate limit {route.spec.provider}: {exc}",
                    resume_after=time.time() + exc.retry_after_s,
                    provider=route.spec.provider,
                    model=route.spec.id,
                    tokens=spent_tokens,
                    usd=spent_usd,
                )
            except ContextOverflow:
                # Контекст не влез — сжимаем историю и пробуем ещё раз.
                messages = self.rt.working.compact_history(messages)
                continue
            except (TransientProviderError, ProviderUnavailable) as exc:
                self.rt.bus.emit(
                    EV_PROVIDER_ERROR,
                    mission_id=task.mission_id,
                    task_id=task.id,
                    provider=route.spec.provider,
                    error=str(exc),
                )
                return DispatchOutcome(
                    status=STATUS_FAILED,
                    detail=f"сбой провайдера {route.spec.provider}: {exc}",
                    provider=route.spec.provider,
                    model=route.spec.id,
                    tokens=spent_tokens,
                    usd=spent_usd,
                )

            usage = completion.usage
            spent_tokens += usage.total
            # dedupe_key делает повторную запись после краша безопасной.
            cost = self.rt.ledger.record(
                provider=route.spec.provider,
                model=route.spec.id,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                cached_in=usage.cached_in,
                mission_id=task.mission_id,
                task_id=task.id,
                dedupe_key=f"{task.id}:{task.attempts}:{iteration}",
            )
            spent_usd += cost
            self.rt.bus.emit(
                EV_PROVIDER_CALL,
                mission_id=task.mission_id,
                task_id=task.id,
                actor=role.name,
                provider=route.spec.provider,
                model=route.spec.id,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                cached_in=usage.cached_in,
                usd=round(cost, 6),
                iteration=iteration,
            )

            try:
                self.rt.ledger.check_budget(task.mission_id)
            except BudgetExceeded as exc:
                return DispatchOutcome(
                    status=STATUS_BLOCKED_APPROVAL,
                    detail=str(exc),
                    provider=route.spec.provider,
                    model=route.spec.id,
                    tokens=spent_tokens,
                    usd=spent_usd,
                )

            if not completion.wants_tools:
                report = Report.parse(completion.json(), completion.text)
                return DispatchOutcome(
                    status=STATUS_DONE,
                    report=report,
                    provider=route.spec.provider,
                    model=route.spec.id,
                    tokens=spent_tokens,
                    usd=spent_usd,
                )

            # Модель просит инструменты: выполняем и продолжаем виток.
            messages.append(
                Message(
                    role="assistant",
                    content=[
                        ContentBlock(
                            type="tool_use",
                            tool_call_id=call.id,
                            tool_name=call.name,
                            arguments=call.arguments,
                        )
                        for call in completion.tool_calls
                    ],
                )
            )
            results: list[ContentBlock] = []
            for call in completion.tool_calls:
                try:
                    result = tools.call(
                        call.name,
                        call.arguments,
                        mission_id=task.mission_id,
                        task_id=task.id,
                        actor=role.name,
                    )
                except ApprovalRequired as exc:
                    self.rt.bus.emit(
                        EV_APPROVAL_REQUEST,
                        mission_id=task.mission_id,
                        task_id=task.id,
                        action=exc.action,
                        detail=exc.detail,
                    )
                    return DispatchOutcome(
                        status=STATUS_BLOCKED_APPROVAL,
                        detail=f"{exc.action}: {exc.detail}",
                        provider=route.spec.provider,
                        model=route.spec.id,
                        tokens=spent_tokens,
                        usd=spent_usd,
                    )
                except CapabilityMissing as exc:
                    self.rt.bus.emit(
                        EV_CAPABILITY_REQUEST,
                        mission_id=task.mission_id,
                        task_id=task.id,
                        cap_kind=exc.kind,
                        name=exc.name,
                        how_to_fix=exc.how_to_fix,
                    )
                    return DispatchOutcome(
                        status=STATUS_BLOCKED_CAPABILITY,
                        detail=f"{exc.kind}/{exc.name}: {exc.how_to_fix}",
                        provider=route.spec.provider,
                        model=route.spec.id,
                        tokens=spent_tokens,
                        usd=spent_usd,
                    )
                results.append(
                    ContentBlock.of_tool_result(call.id, result.as_text(), not result.ok)
                )
            messages.append(Message(role="user", content=results))

        return DispatchOutcome(
            status=STATUS_FAILED,
            detail=f"превышен предел витков инструментов ({MAX_TOOL_ITERATIONS})",
            provider=route.spec.provider,
            model=route.spec.id,
            tokens=spent_tokens,
            usd=spent_usd,
        )

    # ------------------------------------------------------------- обработчики
    def _on_quota(self, task: Task, exc: QuotaExhausted, provider: str) -> DispatchOutcome:
        """Квота исчерпана — это не ошибка, а пауза с известным концом."""
        window = float(self.rt.config.get("quota.assumed_window_s", 18000))
        reset_at = exc.reset_at or (time.time() + window)
        if provider:
            self.rt.quota.mark_exhausted(provider, reset_at=reset_at, error=str(exc))
        self.rt.bus.emit(
            EV_QUOTA_HIT,
            mission_id=task.mission_id,
            task_id=task.id,
            provider=provider,
            reset_at=reset_at,
            reason=str(exc),
        )
        return DispatchOutcome(
            status=STATUS_BLOCKED_QUOTA,
            detail=str(exc),
            resume_after=reset_at,
            provider=provider,
        )


def outcome_to_result_text(outcome: DispatchOutcome, max_tokens: int) -> str:
    """Что записать в поле result задачи — компактно и без транскрипта."""
    if outcome.report is not None:
        return outcome.report.render(max_tokens)
    return json.dumps(
        {"status": outcome.status, "detail": outcome.detail}, ensure_ascii=False
    )
