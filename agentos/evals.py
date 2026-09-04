"""Эталонные миссии: защита самоулучшения от регрессий.

Система, которая правит собственные промпты, роли и навыки, обязана иметь
неподвижную точку отсчёта. Иначе «улучшение» может тихо сломать то, что
работало, и заметить это будет некому.

Каждая миссия прогоняется в изолированном состоянии на mock-провайдере:
детерминированно, без ключей и без сети.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CASES: list[dict[str, Any]] = [
    {
        "name": "простая миссия доходит до конца",
        "goal": "составить краткую сводку по проекту",
        "expect": {"min_done_tasks": 3, "no_failed": True},
    },
]


def load_cases(root: Path) -> list[dict[str, Any]]:
    """Прочитать evals/missions/*.yaml; без них — встроенный минимум."""
    directory = root / "evals" / "missions"
    cases: list[dict[str, Any]] = []
    if directory.exists():
        for path in sorted(directory.glob("*.yaml")):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                cases.append(
                    {"name": path.stem, "goal": "", "expect": {}, "_error": f"невалидный YAML: {exc}"}
                )
                continue
            doc.setdefault("name", path.stem)
            cases.append(doc)
    return cases or DEFAULT_CASES


def run_evals(runtime: Any, *, only: str = "") -> dict[str, Any]:
    """Прогнать эталонные миссии. Возвращает отчёт для CLI и CI."""
    from .orchestrator.supervisor import Supervisor
    from .runtime import Runtime

    root = runtime.config.root
    cases = [c for c in load_cases(root) if not only or only in str(c.get("name", ""))]
    results: list[dict[str, Any]] = []

    saved_env = {k: os.environ.get(k) for k in ("AGENTOS_HOME", "AGENTOS_ALLOW_MOCK", "AGENTOS_MODE")}
    try:
        for case in cases:
            results.append(_run_case(case, root, Runtime, Supervisor))
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    passed = sum(1 for r in results if r["passed"])
    return {"total": len(results), "passed": passed, "cases": results}


def _run_case(case: dict[str, Any], root: Path, Runtime: Any, Supervisor: Any) -> dict[str, Any]:
    name = str(case.get("name", "без имени"))
    if case.get("_error"):
        return {"name": name, "passed": False, "detail": case["_error"]}
    goal = str(case.get("goal", "")).strip()
    if not goal:
        return {"name": name, "passed": False, "detail": "в кейсе не задана goal"}

    expect = case.get("expect", {}) or {}
    with tempfile.TemporaryDirectory(prefix="agentos-eval-") as tmp:
        # Изолированное состояние и mock: кейс не должен видеть чужую память.
        os.environ["AGENTOS_HOME"] = str(Path(tmp) / "var")
        os.environ["AGENTOS_ALLOW_MOCK"] = "1"
        os.environ["AGENTOS_MODE"] = "direct"
        os.environ.pop("AGENTOS_MOCK_FAULTS", None)
        rt = Runtime.open()
        try:
            mission_id, _spec, result = Supervisor(rt).start(
                goal, budget_tokens=int(expect.get("budget_tokens", 200000))
            )
            counts = rt.sm.status_counts(mission_id)
            spend = rt.ledger.mission_spend(mission_id)
            failures = _check(expect, counts, spend, result)
            return {
                "name": name,
                "passed": not failures,
                "detail": "; ".join(failures) or f"выполнено задач: {counts.get('DONE', 0)},"
                f" токенов: {spend.tokens}",
                "counts": counts,
                "tokens": spend.tokens,
                "status": result.status,
            }
        except Exception as exc:
            return {"name": name, "passed": False, "detail": f"{type(exc).__name__}: {exc}"}
        finally:
            rt.close()


def _check(expect: dict[str, Any], counts: dict[str, int], spend: Any, result: Any) -> list[str]:
    """Сверить фактический исход с ожиданиями кейса."""
    failures: list[str] = []
    done = counts.get("DONE", 0)

    minimum = int(expect.get("min_done_tasks", 0))
    if done < minimum:
        failures.append(f"выполнено задач {done}, ожидалось не меньше {minimum}")

    if expect.get("no_failed") and counts.get("FAILED", 0):
        failures.append(f"есть проваленные задачи: {counts['FAILED']}")

    max_tokens = int(expect.get("max_tokens", 0))
    if max_tokens and spend.tokens > max_tokens:
        failures.append(f"расход {spend.tokens} токенов превысил потолок {max_tokens}")

    expected_status = str(expect.get("status", ""))
    if expected_status and result.status != expected_status:
        failures.append(f"статус миссии {result.status}, ожидался {expected_status}")

    if expect.get("verdict") and result.verdict != expect["verdict"]:
        failures.append(f"вердикт {result.verdict or '—'}, ожидался {expect['verdict']}")

    return failures
