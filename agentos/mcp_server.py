"""MCP-сервер AgentOS: контракт, который нельзя не заметить.

Файл-инструкция (AGENTS.md) агент может не прочитать или прочитать по
диагонали. Инструмент проигнорировать труднее: он виден в списке
доступного, у него есть описание и схема аргументов, и хост сам
подсказывает модели, когда его звать.

Поэтому подключение к чужому воркспейсу держится на этом сервере: любой
хост, говорящий по MCP — Claude Code, Codex, Cursor, Gemini CLI, — получает
одни и те же инструменты и один и тот же контракт в поле instructions
рукопожатия.

Транспорт — JSON-RPC поверх stdio на стандартной библиотеке, без внешних
зависимостей: сервер должен подниматься там, где кроме python ничего нет.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import traceback
from collections.abc import Callable
from typing import Any

from . import __version__
from .contract import render_instructions

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "agentos", "version": __version__}

class ToolError(Exception):
    """Ошибка выполнения инструмента: уходит модели, а не роняет сервер."""


class AgentOSServer:
    """Сервер MCP поверх stdio."""

    def __init__(self, runtime_factory: Callable[[], Any] | None = None) -> None:
        self._runtime: Any = None
        self._runtime_factory = runtime_factory
        self._tools = _build_tools()

    # ------------------------------------------------------------- рантайм
    def runtime(self) -> Any:
        """Один Runtime на процесс, поднимается при первом вызове."""
        if self._runtime is None:
            if self._runtime_factory is not None:
                self._runtime = self._runtime_factory()
            else:
                from .runtime import Runtime

                self._runtime = Runtime.open()
        return self._runtime

    def close(self) -> None:
        if self._runtime is not None:
            with contextlib.suppress(Exception):
                self._runtime.close()
            self._runtime = None

    # --------------------------------------------------------------- цикл
    def serve(self, stdin: Any = None, stdout: Any = None) -> None:
        """Читать запросы до закрытия входа."""
        source = stdin or sys.stdin
        sink = stdout or sys.stdout
        try:
            for line in source:
                line = line.strip()
                if not line:
                    continue
                response = self.handle_line(line)
                if response is not None:
                    sink.write(json.dumps(response, ensure_ascii=False) + "\n")
                    sink.flush()
        finally:
            self.close()

    def handle_line(self, line: str) -> dict[str, Any] | None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return None  # мусор во входе игнорируем, а не падаем
        return self.handle(message)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = str(message.get("method", ""))
        request_id = message.get("id")
        if request_id is None:
            return None  # уведомление, ответа не требует

        try:
            result = self._dispatch(method, message.get("params") or {})
        except Exception as exc:  # сервер не должен умирать от одного запроса
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
                "instructions": render_instructions(),
            }
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": name,
                        "description": spec["description"],
                        "inputSchema": spec["schema"],
                    }
                    for name, spec in self._tools.items()
                ]
            }
        if method == "tools/call":
            return self._call_tool(
                str(params.get("name", "")), dict(params.get("arguments") or {})
            )
        if method == "ping":
            return {}
        return {}

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self._tools.get(name)
        if spec is None:
            return _text_result(f"нет такого инструмента: {name}", is_error=True)

        # stdout — это канал протокола. Любая посторонняя печать из библиотек
        # сломала бы JSON-RPC, поэтому она перехватывается и уходит в текст.
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                text = spec["handler"](self.runtime(), **arguments)
        except ToolError as exc:
            return _text_result(str(exc), is_error=True)
        except TypeError as exc:
            return _text_result(f"неверные аргументы: {exc}", is_error=True)
        except Exception as exc:
            detail = traceback.format_exc(limit=3)
            return _text_result(f"{type(exc).__name__}: {exc}\n{detail}", is_error=True)

        noise = buffer.getvalue().strip()
        body = "\n".join(part for part in (str(text).strip(), noise) if part)
        return _text_result(body or "(пусто)")


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


# --------------------------------------------------------------- инструменты


def _tool_resume(rt: Any, once: bool = False) -> str:
    from .orchestrator.supervisor import Supervisor

    supervisor = Supervisor(rt)
    code, results = supervisor.resume(once=once)
    lines = [supervisor.announce()]
    for result in results:
        for handoff in result.handoffs:
            lines.append(
                f"\nЗАДАНИЕ {handoff['task_id']}: {handoff['title']}\n"
                f"бриф: {handoff['brief_path']}"
            )
    lines.append(f"\n(код состояния: {code})")
    return "\n".join(lines)


def _tool_goal(
    rt: Any, goal: str, context: str = "", budget_tokens: int = 0, budget_usd: float = 0.0
) -> str:
    from .orchestrator.supervisor import Supervisor

    if not goal.strip():
        raise ToolError("пустая цель")
    supervisor = Supervisor(rt)
    mission_id, spec, result = supervisor.start(
        goal, context=context, budget_tokens=budget_tokens, budget_usd=budget_usd
    )
    lines = [f"миссия {mission_id}: {spec.goal}"]
    if spec.questions:
        lines.append("нужен ответ человека: " + "; ".join(spec.questions))
    lines.append(_render_mission(rt, mission_id))
    for handoff in result.handoffs:
        lines.append(
            f"\nЗАДАНИЕ {handoff['task_id']}: {handoff['title']}\n"
            f"бриф: {handoff['brief_path']}"
        )
    return "\n".join(lines)


def _tool_status(rt: Any, mission_id: str = "") -> str:
    from .orchestrator.supervisor import Supervisor

    digest = Supervisor(rt).digest(mission_id)
    if not digest["missions"]:
        return "активных миссий нет"
    return "\n\n".join(_render_mission(rt, m["mission_id"]) for m in digest["missions"])


def _tool_task_report(
    rt: Any, task_id: str, summary: str, findings: list[str] | None = None,
    next_steps: list[str] | None = None, tokens: int = 0,
) -> str:
    from .agents.report import Report
    from .bus import EV_TASK_FINISHED
    from .state.machine import TaskStatus

    task = rt.sm.get_task(task_id)
    if task is None:
        raise ToolError(f"нет такой задачи: {task_id}")
    if task.status is TaskStatus.DONE:
        raise ToolError(
            f"задача {task_id} уже закрыта — её результат перезаписывать нельзя"
        )

    report = Report(
        summary=summary, findings=list(findings or []), next_steps=list(next_steps or [])
    )
    limit = int(rt.config.get("budget.subagent_report_tokens", 1200))
    if task.status is TaskStatus.PENDING:
        rt.sm.transition(task.id, TaskStatus.READY)
    if rt.sm.get_task(task_id).status is not TaskStatus.RUNNING:
        rt.sm.transition(task.id, TaskStatus.RUNNING)
    rt.sm.transition(task.id, TaskStatus.DONE, result=report.render(limit))
    rt.bus.emit(
        EV_TASK_FINISHED, mission_id=task.mission_id, task_id=task.id,
        actor=task.role, summary=summary[:400], via="mcp",
    )
    if tokens:
        rt.ledger.record(
            provider="host", model="host", tokens_in=0, tokens_out=tokens,
            mission_id=task.mission_id, task_id=task.id, kind="host",
            dedupe_key=f"host:{task.id}:{task.attempts}",
        )
    rt.checkpointer.write(task.mission_id)
    return f"задача {task.id} закрыта\n\n" + _render_mission(rt, task.mission_id)


def _tool_task_block(rt: Any, task_id: str, reason: str, detail: str = "") -> str:
    import time as _time

    from .state.machine import TaskStatus

    mapping = {
        "quota": TaskStatus.BLOCKED_QUOTA,
        "capability": TaskStatus.BLOCKED_CAPABILITY,
        "approval": TaskStatus.BLOCKED_APPROVAL,
    }
    target = mapping.get(reason)
    if target is None:
        raise ToolError(f"reason должен быть одним из: {', '.join(mapping)}")
    task = rt.sm.get_task(task_id)
    if task is None:
        raise ToolError(f"нет такой задачи: {task_id}")

    resume_after = None
    if target is TaskStatus.BLOCKED_QUOTA:
        resume_after = _time.time() + float(rt.config.get("quota.assumed_window_s", 18000))
    if task.status is not TaskStatus.RUNNING:
        rt.sm.transition(task.id, TaskStatus.READY)
        rt.sm.transition(task.id, TaskStatus.RUNNING)
    rt.sm.transition(
        task.id, target, blocked_reason=detail or reason, resume_after=resume_after
    )
    if target is TaskStatus.BLOCKED_APPROVAL:
        rt.approvals.request(
            detail.split(":", 1)[0][:60] or "подтверждение", detail,
            mission_id=task.mission_id, task_id=task.id,
        )
    rt.checkpointer.write(task.mission_id)
    tail = " — продолжит сама после сброса лимитов" if resume_after else ""
    return f"задача {task.id}: {target.value}{tail}"


def _tool_verify(
    rt: Any, mission_id: str, verdict: str = "", reason: str = "", action: str = ""
) -> str:
    from .agents.report import Verdict
    from .orchestrator.critic import Critic

    host_verdict = None
    if verdict:
        if verdict not in {"accept", "reject", "needs_human"}:
            raise ToolError("verdict: accept | reject | needs_human")
        host_verdict = Verdict(
            verdict=verdict,
            reasons=[reason] if reason else [],
            next_actions=[action] if action else [],
        )
    result = Critic(rt).verify(mission_id, host_verdict=host_verdict)
    rt.checkpointer.settle_missions()
    rt.checkpointer.write(mission_id)

    lines = [f"[{'✓' if g.passed else '✗'}] {g.cmd}" for g in result.gates]
    lines.append(result.verdict.render())
    unmet = rt.checkpointer.unmet_criteria(mission_id)
    lines.append(
        "не подтверждены: " + "; ".join(unmet) if unmet else "все критерии подтверждены"
    )
    return "\n".join(lines)


def _tool_memory_search(rt: Any, query: str, limit: int = 8) -> str:
    facts = rt.semantic.search(query, limit=limit)
    if not facts:
        return "(в памяти ничего не найдено)"
    return "\n".join(fact.as_line() for fact in facts)


def _tool_memory_write(
    rt: Any, content: str, kind: str = "fact", subject: str = ""
) -> str:
    if kind not in {"fact", "lesson", "decision", "preference"}:
        raise ToolError("kind: fact | lesson | decision | preference")
    fact_id = rt.semantic.add(content, kind=kind, subject=subject, source="агент")
    scope = "общая память" if kind in ("lesson", "preference") else "память проекта"
    return f"записано в {scope}: {fact_id}"


def _tool_memory_reflect(rt: Any, query: str) -> str:
    from .memory.backend import supports_reflection

    memory = rt.semantic
    if not supports_reflection(memory):
        raise ToolError(
            "текущий бэкенд памяти не умеет синтез; включи memory.backend: hindsight"
        )
    return memory.reflect(query) or "(синтеза нет)"


def _tool_skills(rt: Any, name: str = "") -> str:
    rt.sync_skills()
    if name:
        skill = rt.skills.load(name)
        if skill is None:
            raise ToolError(f"нет такого навыка: {name}")
        return skill.body
    catalog = rt.skills.catalog()
    if not catalog:
        return "(навыков нет)"
    return "\n".join(skill.header() for skill in catalog)


def _render_mission(rt: Any, mission_id: str) -> str:
    """Карточка миссии текстом — то же, что печатает CLI."""
    from .state.machine import TaskStatus

    mission = rt.sm.get_mission(mission_id)
    if not mission:
        return f"миссия не найдена: {mission_id}"
    counts = rt.sm.status_counts(mission_id)
    spend = rt.ledger.mission_spend(mission_id)
    done = counts.get(TaskStatus.DONE.value, 0)
    lines = [
        f"[{mission['status']}] {mission_id}: {mission['goal']}",
        f"задачи: {done}/{sum(counts.values())} "
        + " ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        f"расход: {spend.tokens} токенов, ${spend.usd:.4f}",
    ]
    dod = rt.store.query(
        "SELECT criterion, status FROM dod WHERE mission_id=? ORDER BY ord", (mission_id,)
    )
    marks = {"pass": "✓", "fail": "✗", "pending": "·", "skipped": "⊘"}
    for row in dod:
        lines.append(f"  {marks.get(row['status'], '·')} {row['criterion']}")
    if mission["blocked_reason"]:
        lines.append(f"  ⚠ {mission['blocked_reason']}")
    return "\n".join(lines)


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _build_tools() -> dict[str, dict[str, Any]]:
    text = {"type": "string"}
    return {
        "agentos_resume": {
            "description": (
                "Подхватить незавершённую работу. Вызывай ПЕРВЫМ в каждой сессии:"
                " одна строка ответа скажет, что сделано, чего система ждёт и"
                " когда продолжит сама."
            ),
            "schema": _obj({"once": {"type": "boolean"}}),
            "handler": _tool_resume,
        },
        "agentos_goal": {
            "description": (
                "Поставить цель — сколь угодно абстрактную. Система зафиксирует"
                " критерии приёмки, построит план задач и выдаст задания."
            ),
            "schema": _obj(
                {
                    "goal": text,
                    "context": text,
                    "budget_tokens": {"type": "integer"},
                    "budget_usd": {"type": "number"},
                },
                ["goal"],
            ),
            "handler": _tool_goal,
        },
        "agentos_status": {
            "description": "Что сделано, что блокирует, сколько потрачено, когда продолжит.",
            "schema": _obj({"mission_id": text}),
            "handler": _tool_status,
        },
        "agentos_task_report": {
            "description": (
                "Вернуть результат выполненного задания. Отчёт, а не транскрипт:"
                " на этом держится экономия контекста. Без этого вызова работа"
                " потеряется при обрыве сессии."
            ),
            "schema": _obj(
                {
                    "task_id": text,
                    "summary": text,
                    "findings": {"type": "array", "items": text},
                    "next_steps": {"type": "array", "items": text},
                    "tokens": {"type": "integer"},
                },
                ["task_id", "summary"],
            ),
            "handler": _tool_task_report,
        },
        "agentos_task_block": {
            "description": (
                "Сообщить, что задание упёрлось в стену: quota — кончились лимиты"
                " (продолжится сама), capability — не хватает доступа или ключа,"
                " approval — нужно подтверждение человека. Остальные ветки плана"
                " продолжат идти."
            ),
            "schema": _obj(
                {
                    "task_id": text,
                    "reason": {"type": "string", "enum": ["quota", "capability", "approval"]},
                    "detail": text,
                },
                ["task_id", "reason"],
            ),
            "handler": _tool_task_block,
        },
        "agentos_verify": {
            "description": (
                "Приёмка миссии: прогнать программные гейты и вынести вердикт по"
                " смысловым критериям. Красный гейт отменяет любой вердикт."
            ),
            "schema": _obj(
                {
                    "mission_id": text,
                    "verdict": {"type": "string", "enum": ["accept", "reject", "needs_human"]},
                    "reason": text,
                    "action": text,
                },
                ["mission_id"],
            ),
            "handler": _tool_verify,
        },
        "agentos_memory_search": {
            "description": (
                "Найти в памяти факты, уроки и решения — по этому проекту и по"
                " общему опыту. Спрашивай здесь до того, как спрашивать человека."
            ),
            "schema": _obj({"query": text, "limit": {"type": "integer"}}, ["query"]),
            "handler": _tool_memory_search,
        },
        "agentos_memory_write": {
            "description": (
                "Записать знание. fact и decision остаются в этом проекте,"
                " lesson и preference переезжают с человеком в другие проекты."
            ),
            "schema": _obj(
                {
                    "content": text,
                    "kind": {
                        "type": "string",
                        "enum": ["fact", "lesson", "decision", "preference"],
                    },
                    "subject": text,
                },
                ["content"],
            ),
            "handler": _tool_memory_write,
        },
        "agentos_memory_reflect": {
            "description": (
                "Вывод из накопленного, а не список похожих записей."
                " Доступен на бэкенде памяти с синтезом."
            ),
            "schema": _obj({"query": text}, ["query"]),
            "handler": _tool_memory_reflect,
        },
        "agentos_skills": {
            "description": (
                "Каталог навыков без аргументов; с name — тело навыка."
                " В каталоге только заголовки, чтобы не жечь контекст."
            ),
            "schema": _obj({"name": text}),
            "handler": _tool_skills,
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Точка входа: agentctl mcp."""
    AgentOSServer().serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
