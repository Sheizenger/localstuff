"""agentctl — единственная точка входа в AgentOS.

Через неё работают и человек (`make start`, `make status`), и агент-хост:
в native-режиме хост получает бриф и возвращает результат командой
`agentctl task report`. Поэтому вывод команд рассчитан на чтение и
человеком, и моделью: коротко, без украшений, с конкретными следующими шагами.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__

# --------------------------------------------------------------------- вывод


def out(text: str = "") -> None:
    try:
        print(text)
    except BrokenPipeError:
        # Вывод оборвали пайпом (`| head`) — это не ошибка системы.
        _silence_broken_pipe()


def as_json(payload: Any) -> None:
    out(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _silence_broken_pipe() -> None:
    """Закрыть stdout и выйти тихо, как это делают обычные утилиты."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except OSError:
        pass
    raise SystemExit(0)


def human_seconds(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}с"
    if seconds < 3600:
        return f"{seconds // 60}м"
    return f"{seconds // 3600}ч{(seconds % 3600) // 60:02d}м"


def _runtime(args: argparse.Namespace):
    """Открыть Runtime, применив режим из аргументов."""
    from .runtime import Runtime

    if getattr(args, "mode", ""):
        os.environ["AGENTOS_MODE"] = args.mode
    return Runtime.open()


# ------------------------------------------------------------------ команды


def cmd_init(args: argparse.Namespace) -> int:
    rt = _runtime(args)
    try:
        rt.config.ensure_dirs()
        stats = rt.sync_skills()
        rt.checkpointer.refresh_resume_pointer()
        out(f"состояние: {rt.config.home}")
        out(f"схема БД:  v{rt.store.get_kv('schema_version')}")
        out(f"навыки:    {stats['total']} (добавлено {stats['added']})")
        out(f"режим:     {rt.mode}")
        return 0
    finally:
        rt.close()


def cmd_doctor(args: argparse.Namespace) -> int:
    """Проверка окружения. Возвращает 1, если есть блокирующие проблемы."""
    from .providers.registry import availability

    rt = _runtime(args)
    problems: list[str] = []
    warnings: list[str] = []
    try:
        out(f"AgentOS {__version__}")
        out(f"python:  {sys.version.split()[0]}")
        out(f"корень:  {rt.config.root}")
        out(f"состояние: {rt.config.home}  (схема v{rt.store.get_kv('schema_version')})")
        out(f"режим:   {rt.mode}")
        out("")

        out("Провайдеры:")
        avail = availability()
        for name, ok in sorted(avail.items()):
            if name == "mock":
                continue
            from .providers.registry import get_provider

            reason = "" if ok else f" — {get_provider(name).missing_reason()}"
            out(f"  [{'✓' if ok else ' '}] {name}{reason}")
        if not any(ok for n, ok in avail.items() if n != "mock"):
            warnings.append(
                "ни один реальный провайдер не настроен: работа пойдёт в native-режиме"
                " (субагентов запускает агент-хост) либо на mock в тестах"
            )

        out("")
        out("Каталог моделей:")
        unverified = [m for m in rt.config.models if not m.pricing_verified and m.provider != "mock"]
        for tier in ("reasoning", "large", "small", "nano"):
            chain = [f"{m.provider}/{m.id}" for m in rt.config.models_for_tier(tier)]
            out(f"  {tier:9s} {' -> '.join(chain) or '(пусто)'}")
            if not chain:
                problems.append(f"в каталоге нет ни одной модели тира '{tier}'")
        if unverified:
            warnings.append(
                f"цены не сверены у {len(unverified)} моделей "
                f"({', '.join(sorted({m.provider for m in unverified}))}):"
                " учёт расхода будет приблизительным"
            )

        out("")
        out("Политика:")
        binaries = rt.config.policy.get("shell", {}).get("allow_binaries", [])
        bad = [b for b in binaries if not isinstance(b, str)]
        if bad:
            problems.append(
                f"в allow_binaries есть не-строки: {bad}."
                " В YAML имена вроде true/false/on нужно брать в кавычки"
            )
        out(f"  разрешено бинарей: {len(binaries)}")
        out(f"  требуют человека:  {', '.join(sorted(rt.guard.approval_rules()[0])) or '—'}")

        out("")
        out("Гейты приёмки:")
        for gate in rt.config.get("self_check.programmatic_gates", []) or []:
            cmd = str(gate.get("cmd", ""))
            verdict = rt.guard.check_shell(cmd)
            mark = "✓" if verdict.allowed else "✗"
            out(f"  [{mark}] {gate.get('name')}: {cmd}")
            if not verdict.allowed:
                problems.append(f"гейт '{gate.get('name')}' запрещён политикой: {verdict.reason}")
        if not (rt.config.root / ".venv").exists():
            warnings.append(
                "нет .venv — гейты 'make test'/'make lint' будут падать."
                " Запусти: make bootstrap"
            )

        out("")
        out(f"Навыки: {rt.skills.stats() or '(нет)'}")
        out(f"Память: {rt.semantic.stats() or '(пусто)'}")
        pending = rt.capabilities.pending()
        if pending:
            out("")
            out("Ждёт человека:")
            for item in pending:
                out(f"  {item.as_line()}")

        out("")
        for w in warnings:
            out(f"⚠ {w}")
        for p in problems:
            out(f"✗ {p}")
        if not problems and not warnings:
            out("✓ всё в порядке")
        elif not problems:
            out("✓ блокирующих проблем нет")
        return 1 if problems else 0
    finally:
        rt.close()


def cmd_goal(args: argparse.Namespace) -> int:
    from .orchestrator.supervisor import Supervisor

    rt = _runtime(args)
    try:
        sup = Supervisor(rt)
        mission_id, spec, result = sup.start(
            args.goal,
            context=args.context or "",
            budget_tokens=args.budget_tokens or 0,
            budget_usd=args.budget_usd or 0.0,
        )
        out(f"миссия {mission_id}: {spec.goal}")
        if spec.assumptions:
            out("допущения: " + "; ".join(spec.assumptions))
        if spec.questions:
            out("")
            out("нужен ответ, чтобы не уйти не туда:")
            for question in spec.questions:
                out(f"  - {question}")
        out("")
        _print_mission(rt, mission_id)
        _print_handoffs(result.handoffs)
        return 0
    finally:
        rt.close()


def cmd_resume(args: argparse.Namespace) -> int:
    from .orchestrator.supervisor import EXIT_NOTHING_TO_DO, Supervisor

    rt = _runtime(args)
    try:
        sup = Supervisor(rt)
        if args.announce:
            # Одна строка: старт сессии не должен съедать контекст отчётом.
            announcement = sup.announce()
            code, results = sup.resume(once=args.once)
            if code == EXIT_NOTHING_TO_DO and not results:
                if not args.quiet:
                    out(announcement)
                return code
            out(sup.announce())
            _print_handoffs([h for r in results for h in r.handoffs])
            return code

        code, results = sup.resume(once=args.once)
        if not results:
            out("незавершённых миссий нет")
            return code
        for result in results:
            _print_mission(rt, result.mission_id)
            _print_handoffs(result.handoffs)
        return code
    finally:
        rt.close()


def cmd_status(args: argparse.Namespace) -> int:
    from .orchestrator.supervisor import Supervisor

    rt = _runtime(args)
    try:
        sup = Supervisor(rt)
        digest = sup.digest(args.mission or "")

        if args.resume_in_seconds:
            waits = [m["wait_seconds"] for m in digest["missions"] if m["wait_seconds"]]
            out(str(min(waits) if waits else 60))
            return 0
        if args.json:
            as_json(digest)
            return 0

        if not digest["missions"]:
            out("активных миссий нет")
            totals = rt.ledger.totals()
            out(f"всего израсходовано: {totals['tokens']} токенов, ${totals['usd']:.4f}")
            return 0
        for mission in digest["missions"]:
            _print_mission(rt, mission["mission_id"])
            out("")
        return 0
    finally:
        rt.close()


def _print_mission(rt: Any, mission_id: str) -> None:
    """Компактная карточка миссии — то, что человек читает вместо лога."""
    from .state.machine import TaskStatus

    mission = rt.sm.get_mission(mission_id)
    if not mission:
        out(f"миссия не найдена: {mission_id}")
        return
    counts = rt.sm.status_counts(mission_id)
    spend = rt.ledger.mission_spend(mission_id)
    total = sum(counts.values())
    done = counts.get(TaskStatus.DONE.value, 0)

    out(f"[{mission['status']}] {mission_id}: {mission['goal']}")
    out(f"  задачи: {done}/{total} " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    budget = f" из {spend.budget_tokens}" if spend.budget_tokens else ""
    out(f"  расход: {spend.tokens}{budget} токенов, ${spend.usd:.4f}")

    dod = rt.store.query(
        "SELECT criterion, status FROM dod WHERE mission_id=? ORDER BY ord", (mission_id,)
    )
    if dod:
        marks = {"pass": "✓", "fail": "✗", "pending": "·"}
        out("  критерии приёмки:")
        for row in dod:
            out(f"    {marks.get(row['status'], '·')} {row['criterion']}")

    blocked = rt.store.query(
        "SELECT title, status, blocked_reason, resume_after FROM tasks"
        " WHERE mission_id=? AND status LIKE 'BLOCKED%'",
        (mission_id,),
    )
    for row in blocked:
        tail = ""
        if row["resume_after"]:
            tail = f", продолжит через {human_seconds(row['resume_after'] - time.time())}"
        out(f"  ⏸ {row['title']}: {row['blocked_reason']}{tail}")

    if mission["blocked_reason"]:
        out(f"  ⚠ {mission['blocked_reason']}")


def _print_handoffs(handoffs: list[dict[str, str]]) -> None:
    """Задания, которые должен выполнить агент-хост (native-режим)."""
    if not handoffs:
        return
    out("")
    out("Задания субагентам (выполни каждое и верни результат):")
    for handoff in handoffs:
        out(f"  {handoff['task_id']}: {handoff['title']}")
        out(f"    бриф: {handoff['brief_path']}")
    out("")
    out("Как вернуть результат: agentctl task report <task_id> --json '<отчёт>'")


# ------------------------------------------------------------------- задачи


def cmd_task_report(args: argparse.Namespace) -> int:
    """Так агент-хост закрывает задачу, выполненную его субагентом."""
    from .agents.report import Report
    from .bus import EV_TASK_FINISHED
    from .state.machine import TaskStatus

    rt = _runtime(args)
    try:
        task = rt.sm.get_task(args.task_id)
        if task is None:
            out(f"нет такой задачи: {args.task_id}")
            return 2
        payload: Any = None
        if args.json:
            try:
                payload = json.loads(args.json)
            except json.JSONDecodeError as exc:
                out(f"невалидный JSON: {exc}")
                return 2
        report = Report.parse(payload, args.text or "")
        limit = int(rt.config.get("budget.subagent_report_tokens", 1200))

        if task.status is TaskStatus.PENDING:
            rt.sm.transition(task.id, TaskStatus.READY)
            task = rt.sm.get_task(args.task_id)
        if task.status in (TaskStatus.READY, TaskStatus.BLOCKED_QUOTA):
            rt.sm.transition(task.id, TaskStatus.READY)
            rt.sm.transition(task.id, TaskStatus.RUNNING)
        rt.sm.transition(task.id, TaskStatus.DONE, result=report.render(limit))
        rt.bus.emit(
            EV_TASK_FINISHED,
            mission_id=task.mission_id,
            task_id=task.id,
            actor=task.role,
            summary=report.summary[:400],
            via="host",
        )
        if args.tokens:
            rt.ledger.record(
                provider=args.provider or "host",
                model=args.model or "host",
                tokens_in=0,
                tokens_out=args.tokens,
                mission_id=task.mission_id,
                task_id=task.id,
                kind="host",
                dedupe_key=f"host:{task.id}:{task.attempts}",
            )
        rt.checkpointer.write(task.mission_id)
        out(f"задача {task.id} закрыта")
        _print_mission(rt, task.mission_id)
        return 0
    finally:
        rt.close()


def cmd_task_block(args: argparse.Namespace) -> int:
    """Хост сообщает, что задача упёрлась в лимит, доступ или подтверждение."""
    from .state.machine import TaskStatus

    mapping = {
        "quota": TaskStatus.BLOCKED_QUOTA,
        "capability": TaskStatus.BLOCKED_CAPABILITY,
        "approval": TaskStatus.BLOCKED_APPROVAL,
    }
    rt = _runtime(args)
    try:
        task = rt.sm.get_task(args.task_id)
        if task is None:
            out(f"нет такой задачи: {args.task_id}")
            return 2
        target = mapping[args.reason]
        resume_after = None
        if target is TaskStatus.BLOCKED_QUOTA:
            wait = args.wait_seconds or float(rt.config.get("quota.assumed_window_s", 18000))
            resume_after = time.time() + wait
        if task.status is not TaskStatus.RUNNING:
            rt.sm.transition(task.id, TaskStatus.READY)
            rt.sm.transition(task.id, TaskStatus.RUNNING)
        rt.sm.transition(
            task.id, target, blocked_reason=args.detail or args.reason, resume_after=resume_after
        )
        rt.checkpointer.write(task.mission_id)
        if resume_after:
            out(f"задача {task.id} ждёт до {human_seconds(resume_after - time.time())} и продолжит сама")
        else:
            out(f"задача {task.id}: {target.value} — {args.detail}")
        return 0
    finally:
        rt.close()


def cmd_task_show(args: argparse.Namespace) -> int:
    rt = _runtime(args)
    try:
        task = rt.sm.get_task(args.task_id)
        if task is None:
            out(f"нет такой задачи: {args.task_id}")
            return 2
        as_json(
            {
                "id": task.id,
                "mission_id": task.mission_id,
                "title": task.title,
                "role": task.role,
                "tier": task.tier,
                "status": task.status.value,
                "attempts": task.attempts,
                "brief": task.brief,
                "result": task.result,
                "blocked_reason": task.blocked_reason,
                "used_tokens": task.used_tokens,
            }
        )
        return 0
    finally:
        rt.close()


# ------------------------------------------------------------------ миссии


def cmd_mission_list(args: argparse.Namespace) -> int:
    rt = _runtime(args)
    try:
        rows = rt.store.query("SELECT * FROM missions ORDER BY created_at DESC LIMIT ?", (args.limit,))
        if not rows:
            out("миссий нет")
            return 0
        for row in rows:
            counts = rt.sm.status_counts(row["id"])
            done = counts.get("DONE", 0)
            out(f"{row['id']}  [{row['status']:9s}] {done}/{sum(counts.values())}  {row['goal'][:60]}")
        return 0
    finally:
        rt.close()


def cmd_mission_show(args: argparse.Namespace) -> int:
    rt = _runtime(args)
    try:
        _print_mission(rt, args.mission_id)
        out("")
        out("Задачи:")
        for task in rt.sm.tasks_of(args.mission_id):
            out(f"  [{task.status.value:18s}] {task.role:11s} {task.title[:56]}")
        if args.events:
            out("")
            out("Ход работы:")
            out(rt.episodic.digest(args.mission_id))
        return 0
    finally:
        rt.close()


def cmd_mission_dod(args: argparse.Namespace) -> int:
    from .orchestrator.intake import Intake

    rt = _runtime(args)
    try:
        if args.add:
            dod_id = Intake(rt).add_criterion(
                args.mission_id, args.add, kind="programmatic" if args.cmd else "semantic",
                cmd=args.cmd or "",
            )
            out(f"добавлен критерий {dod_id}")
        rows = rt.store.query(
            "SELECT criterion, kind, cmd, status FROM dod WHERE mission_id=? ORDER BY ord",
            (args.mission_id,),
        )
        marks = {"pass": "✓", "fail": "✗", "pending": "·"}
        for row in rows:
            cmd = f"  ({row['cmd']})" if row["cmd"] else ""
            out(f"  {marks.get(row['status'], '·')} [{row['kind']}] {row['criterion']}{cmd}")
        return 0
    finally:
        rt.close()


def cmd_verify(args: argparse.Namespace) -> int:
    """Прогнать гейты и критика по требованию."""
    from .orchestrator.critic import Critic

    rt = _runtime(args)
    try:
        result = Critic(rt).verify(args.mission_id)
        for gate in result.gates:
            out(f"  [{'✓' if gate.passed else '✗'}] {gate.cmd}")
        out("")
        out(result.verdict.render())
        if result.fix_tasks:
            out(f"заведено задач на исправление: {len(result.fix_tasks)}")
        rt.checkpointer.write(args.mission_id)
        return 0 if result.accepted else 1
    finally:
        rt.close()


# ------------------------------------------------------- роли, навыки, память


def cmd_agents_sync(args: argparse.Namespace) -> int:
    """Сгенерировать описания субагентов для агент-хоста из config/agents/."""
    rt = _runtime(args)
    try:
        target = rt.config.root / ".claude" / "agents"
        target.mkdir(parents=True, exist_ok=True)
        written = []
        for role in rt.config.roles.values():
            if not role.selectable:
                continue
            tools = ", ".join(role.tools) if role.tools else "все доступные"
            body = f"""---
name: agentos-{role.name}
description: {role.goal} Тир {role.tier}, приоритет {role.priority}.{
    (' Триггеры: ' + ', '.join(role.triggers) + '.') if role.triggers else ''}
---

{role.system}

## Инструменты

{tools}

## Как вернуть результат

Ты работаешь внутри AgentOS. Результат возвращается не текстом в чат, а командой:

```bash
agentctl task report <task_id> --json '{{"summary": "...", "findings": [], "next_steps": []}}'
```

Уложись в {role.max_output_tokens} токенов вывода.
Файл сгенерирован из config/agents/{role.name}.yaml — правь YAML, не этот файл.
"""
            path = target / f"agentos-{role.name}.md"
            path.write_text(body, encoding="utf-8")
            written.append(path.name)
        out(f"сгенерировано описаний: {len(written)} в {target}")
        for name in written:
            out(f"  {name}")
        return 0
    finally:
        rt.close()


def cmd_role_match(args: argparse.Namespace) -> int:
    from .agents.roles import RoleRouter

    rt = _runtime(args)
    try:
        matches = RoleRouter(rt.config).match(args.text, limit=5)
        if not matches:
            out("подходящих ролей нет, будет использована роль по умолчанию")
            return 0
        for match in matches:
            out(f"  {match.role.name:12s} {match.score:5.2f}  {match.why}")
        return 0
    finally:
        rt.close()


def cmd_skill(args: argparse.Namespace) -> int:
    from .orchestrator.improve import Improver

    rt = _runtime(args)
    try:
        rt.sync_skills()
        if args.skill_action == "list":
            for skill in rt.skills.catalog():
                out(f"  {skill.header()}")
            proposed = Improver(rt).proposed()
            if proposed:
                out("")
                out("черновики (не активны): " + ", ".join(proposed))
            return 0
        if args.skill_action == "show":
            skill = rt.skills.load(args.name)
            if skill is None:
                out(f"нет такого навыка: {args.name}")
                return 2
            out(skill.body)
            return 0
        if args.skill_action == "promote":
            ok = Improver(rt).promote_skill(args.name)
            out(f"навык {args.name} активирован" if ok else f"черновика нет: {args.name}")
            return 0 if ok else 2
        return 2
    finally:
        rt.close()


def cmd_memory(args: argparse.Namespace) -> int:
    rt = _runtime(args)
    try:
        if args.memory_action == "search":
            facts = rt.semantic.search(args.query, limit=args.limit)
            if not facts:
                out("ничего не найдено")
                return 0
            for fact in facts:
                out(f"  {fact.score:.4f} {fact.as_line()}")
            return 0
        if args.memory_action == "add":
            fact_id = rt.semantic.add(
                args.content, subject=args.subject or "", kind=args.kind, source="человек"
            )
            out(f"записано: {fact_id}")
            return 0
        stats = rt.semantic.stats()
        out(f"фактов и уроков: {stats or '(пусто)'}")
        out(f"навыки: {rt.skills.stats() or '(нет)'}")
        out(f"векторный поиск: {rt.semantic.index.backend}, эмбеддер {rt.embedder.spec.id}")
        return 0
    finally:
        rt.close()


def cmd_capability(args: argparse.Namespace) -> int:
    rt = _runtime(args)
    try:
        if args.capability_action == "request":
            status = rt.capabilities.request(args.kind, args.name, reason=args.reason or "")
            out(status.as_line())
            return 0 if status.ok else 1
        items = rt.capabilities.list_all()
        if not items:
            out("ничего не подключалось")
        for item in items:
            out(item.as_line())
        out("")
        out("Каталог MCP из config/mcp.json:")
        for name, spec in rt.capabilities.catalog().items():
            auto = "auto" if spec.auto else "нужно подтверждение"
            missing = f", не хватает: {', '.join(spec.missing_env())}" if spec.missing_env() else ""
            out(f"  {name:12s} [{auto}{missing}] {spec.description}")
        return 0
    finally:
        rt.close()


def cmd_events(args: argparse.Namespace) -> int:
    rt = _runtime(args)
    try:
        for event in rt.bus.tail(args.mission or "", limit=args.limit):
            stamp = time.strftime("%H:%M:%S", time.localtime(event["ts"]))
            payload = json.dumps(event["payload"], ensure_ascii=False)[:160]
            out(f"{stamp} {event['kind']:22s} {payload}")
        return 0
    finally:
        rt.close()


def cmd_eval(args: argparse.Namespace) -> int:
    from .evals import run_evals

    rt = _runtime(args)
    try:
        report = run_evals(rt, only=args.only or "")
        as_json(report) if args.json else _print_eval(report)
        return 0 if report["passed"] == report["total"] else 1
    finally:
        rt.close()


def _print_eval(report: dict[str, Any]) -> None:
    for case in report["cases"]:
        mark = "✓" if case["passed"] else "✗"
        out(f"  [{mark}] {case['name']}: {case['detail']}")
    out("")
    out(f"пройдено {report['passed']} из {report['total']}")


# ------------------------------------------------------------------ парсер


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentctl",
        description="AgentOS — автономные агенты поверх любого провайдера.",
    )
    parser.add_argument("--version", action="version", version=f"AgentOS {__version__}")
    parser.add_argument(
        "--mode",
        choices=["native", "direct"],
        default="",
        help="native — субагентов запускает агент-хост; direct — сам AgentOS",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="создать состояние и проиндексировать навыки").set_defaults(
        func=cmd_init
    )
    sub.add_parser("doctor", help="проверить окружение, ключи, политику, гейты").set_defaults(
        func=cmd_doctor
    )

    goal = sub.add_parser("goal", help="поставить цель и начать работу")
    goal.add_argument("goal", help="формулировка цели, можно абстрактную")
    goal.add_argument("--context", default="", help="дополнительный контекст")
    goal.add_argument("--budget-tokens", type=int, default=0)
    goal.add_argument("--budget-usd", type=float, default=0.0)
    goal.set_defaults(func=cmd_goal)

    resume = sub.add_parser("resume", help="продолжить незавершённое")
    resume.add_argument("--announce", action="store_true", help="одна строка вместо отчёта")
    resume.add_argument("--once", action="store_true", help="один проход планировщика")
    resume.add_argument("--quiet", action="store_true", help="молчать, если работы нет")
    resume.set_defaults(func=cmd_resume)

    status = sub.add_parser("status", help="короткий дайджест состояния")
    status.add_argument("--json", action="store_true")
    status.add_argument("--mission", default="")
    status.add_argument(
        "--resume-in-seconds",
        action="store_true",
        help="напечатать только число секунд до продолжения (для скриптов)",
    )
    status.set_defaults(func=cmd_status)

    task = sub.add_parser("task", help="работа с задачами (используется агент-хостом)")
    task_sub = task.add_subparsers(dest="task_action", required=True)

    report = task_sub.add_parser("report", help="вернуть результат субагента")
    report.add_argument("task_id")
    report.add_argument("--json", default="", help="отчёт в JSON по схеме report")
    report.add_argument("--text", default="", help="или просто текст")
    report.add_argument("--tokens", type=int, default=0, help="сколько токенов потрачено хостом")
    report.add_argument("--provider", default="")
    report.add_argument("--model", default="")
    report.set_defaults(func=cmd_task_report)

    block = task_sub.add_parser("block", help="сообщить о блокировке задачи")
    block.add_argument("task_id")
    block.add_argument("--reason", choices=["quota", "capability", "approval"], required=True)
    block.add_argument("--detail", default="")
    block.add_argument("--wait-seconds", type=float, default=0.0)
    block.set_defaults(func=cmd_task_block)

    show = task_sub.add_parser("show", help="показать задачу целиком")
    show.add_argument("task_id")
    show.set_defaults(func=cmd_task_show)

    mission = sub.add_parser("mission", help="миссии")
    mission_sub = mission.add_subparsers(dest="mission_action", required=True)
    mlist = mission_sub.add_parser("list")
    mlist.add_argument("--limit", type=int, default=20)
    mlist.set_defaults(func=cmd_mission_list)
    mshow = mission_sub.add_parser("show")
    mshow.add_argument("mission_id")
    mshow.add_argument("--events", action="store_true", help="добавить ход работы")
    mshow.set_defaults(func=cmd_mission_show)
    mdod = mission_sub.add_parser("dod", help="посмотреть или дополнить критерии приёмки")
    mdod.add_argument("mission_id")
    mdod.add_argument("--add", default="", help="текст нового критерия")
    mdod.add_argument("--cmd", default="", help="команда — делает критерий программным гейтом")
    mdod.set_defaults(func=cmd_mission_dod)

    verify = sub.add_parser("verify", help="прогнать гейты и критика по требованию")
    verify.add_argument("mission_id")
    verify.set_defaults(func=cmd_verify)

    agents = sub.add_parser("agents", help="описания субагентов для агент-хоста")
    agents_sub = agents.add_subparsers(dest="agents_action", required=True)
    agents_sub.add_parser("sync").set_defaults(func=cmd_agents_sync)

    role = sub.add_parser("role", help="подбор роли")
    role_sub = role.add_subparsers(dest="role_action", required=True)
    rmatch = role_sub.add_parser("match")
    rmatch.add_argument("text")
    rmatch.set_defaults(func=cmd_role_match)

    skill = sub.add_parser("skill", help="навыки")
    skill_sub = skill.add_subparsers(dest="skill_action", required=True)
    skill_sub.add_parser("list").set_defaults(func=cmd_skill)
    sshow = skill_sub.add_parser("show")
    sshow.add_argument("name")
    sshow.set_defaults(func=cmd_skill)
    spromote = skill_sub.add_parser("promote", help="активировать черновик навыка")
    spromote.add_argument("name")
    spromote.set_defaults(func=cmd_skill)

    memory = sub.add_parser("memory", help="долговременная память")
    memory_sub = memory.add_subparsers(dest="memory_action", required=True)
    msearch = memory_sub.add_parser("search")
    msearch.add_argument("query")
    msearch.add_argument("--limit", type=int, default=10)
    msearch.set_defaults(func=cmd_memory)
    madd = memory_sub.add_parser("add")
    madd.add_argument("content")
    madd.add_argument("--subject", default="")
    madd.add_argument("--kind", default="fact", choices=["fact", "lesson", "decision", "preference"])
    madd.set_defaults(func=cmd_memory)
    memory_sub.add_parser("stats").set_defaults(func=cmd_memory)

    capability = sub.add_parser("capability", help="подключённые возможности и каталог MCP")
    cap_sub = capability.add_subparsers(dest="capability_action", required=True)
    cap_sub.add_parser("list").set_defaults(func=cmd_capability)
    crequest = cap_sub.add_parser("request")
    crequest.add_argument("kind", choices=["mcp", "skill", "tool", "secret"])
    crequest.add_argument("name")
    crequest.add_argument("--reason", default="")
    crequest.set_defaults(func=cmd_capability)

    events = sub.add_parser("events", help="журнал событий")
    events.add_argument("--mission", default="")
    events.add_argument("--limit", type=int, default=40)
    events.set_defaults(func=cmd_events)

    evaluate = sub.add_parser("eval", help="эталонные миссии")
    eval_sub = evaluate.add_subparsers(dest="eval_action", required=True)
    erun = eval_sub.add_parser("run")
    erun.add_argument("--only", default="")
    erun.add_argument("--json", action="store_true")
    erun.set_defaults(func=cmd_eval)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Стандартное поведение утилит при обрыве пайпа вместо трассировки.
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        out("прервано")
        return 130
    except Exception as exc:
        # Ошибка CLI не должна выглядеть как падение системы: агент-хост
        # читает этот вывод и должен понять, что делать дальше.
        out(f"ошибка: {type(exc).__name__}: {exc}")
        if os.environ.get("AGENTOS_DEBUG") == "1":
            raise
        return 2


if __name__ == "__main__":
    sys.exit(main())
