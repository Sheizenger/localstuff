"""Два сценария, ради которых система вообще существует.

1. Кончились лимиты токенов посреди работы — и она продолжилась сама.
2. Процесс убит посреди работы — и она продолжилась без дублей и без
   двойного учёта расхода.

Оба прогоняются на mock-провайдере: детерминированно, без ключей и сети.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from agentos.orchestrator.supervisor import Supervisor
from agentos.runtime import Runtime
from agentos.state.machine import TaskStatus

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_quota_exhaustion_blocks_then_resumes_itself(runtime, monkeypatch):
    # Четвёртый вызов модели упрётся в лимит, который сбросится через секунду.
    monkeypatch.setenv(
        "AGENTOS_MOCK_FAULTS", json.dumps([{"at": 4, "type": "quota", "reset_in": 1}])
    )  # точный номер: проверяем, что встаёт ровно одна ветка, а не вся миссия
    supervisor = Supervisor(runtime)
    mission_id, _spec, result = supervisor.start("миссия, упирающаяся в лимит")

    blocked = [
        t for t in runtime.sm.tasks_of(mission_id) if t.status is TaskStatus.BLOCKED_QUOTA
    ]
    assert blocked, "исчерпание лимита должно останавливать задачу, а не ронять миссию"
    assert blocked[0].resume_after, "должно быть известно, когда продолжать"
    assert result.wait_seconds >= 0

    # Другие ветки при этом не останавливаются.
    assert any(t.status is TaskStatus.DONE for t in runtime.sm.tasks_of(mission_id))

    # Человек ничего не делает — просто проходит время.
    monkeypatch.delenv("AGENTOS_MOCK_FAULTS", raising=False)
    time.sleep(1.2)
    code, results = supervisor.resume()

    assert code in (0, 1, 10)
    statuses = {t.status for t in runtime.sm.tasks_of(mission_id)}
    assert TaskStatus.BLOCKED_QUOTA not in statuses, "после сброса лимита работа пошла дальше"
    assert results


def test_announce_tells_when_work_will_continue(runtime, monkeypatch):
    """Одна строка на старте сессии вместо отчёта на весь контекст."""
    # "after" вместо "at": какая именно ветка DAG упрётся в лимит первой —
    # деталь планирования, а проверяем мы поведение при упоре в лимит.
    monkeypatch.setenv(
        "AGENTOS_MOCK_FAULTS", json.dumps([{"after": 3, "type": "quota", "reset_in": 3600}])
    )
    supervisor = Supervisor(runtime)
    supervisor.start("миссия с долгим ожиданием")

    announcement = supervisor.announce()

    assert announcement.count("\n") == 0, "объявление должно быть одной строкой"
    assert "продолжит через" in announcement


def _crash_script(home: Path, mock_state: Path) -> str:
    """Скрипт, который начинает миссию и жёстко умирает посреди неё."""
    return f"""
import os, signal, sys
sys.path.insert(0, {str(REPO_ROOT)!r})
os.environ["AGENTOS_HOME"] = {str(home)!r}
os.environ["AGENTOS_ALLOW_MOCK"] = "1"
os.environ["AGENTOS_MODE"] = "direct"
os.environ["AGENTOS_IN_GATE"] = "1"
os.environ["AGENTOS_MOCK_STATE"] = {str(mock_state)!r}

from agentos.runtime import Runtime
from agentos.orchestrator.intake import Intake
from agentos.orchestrator.planner import Planner
from agentos.state.machine import TaskStatus

rt = Runtime.open({str(REPO_ROOT)!r})
mission_id, _ = Intake(rt).create("миссия, прерванная крахом")
planner = Planner(rt)
planner.persist(mission_id, planner.build(mission_id))

task = rt.sm.claim_next(mission_id)                  # задача в RUNNING
rt.ledger.record(provider="mock", model="mock-small", tokens_in=100, tokens_out=50,
                 mission_id=mission_id, task_id=task.id, dedupe_key="crash-call")
rt.checkpointer.write(mission_id)
print(mission_id)
sys.stdout.flush()
os.kill(os.getpid(), signal.SIGKILL)                 # смерть без единого финализатора
"""


def test_process_killed_mid_run_resumes_without_duplicates(tmp_path):
    home = tmp_path / "var"
    mock_state = tmp_path / "mock_calls.txt"

    process = subprocess.run(
        [sys.executable, "-c", _crash_script(home, mock_state)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    mission_id = (process.stdout or "").strip().splitlines()[-1]
    assert process.returncode == -9, "процесс должен быть убит, а не завершиться штатно"
    assert mission_id.startswith("m_")

    env = dict(os.environ)
    env.update(
        {
            "AGENTOS_HOME": str(home),
            "AGENTOS_ALLOW_MOCK": "1",
            "AGENTOS_MODE": "direct",
            "AGENTOS_IN_GATE": "1",
            "AGENTOS_MOCK_STATE": str(mock_state),
        }
    )
    for key, value in env.items():
        os.environ[key] = value

    runtime = Runtime.open(REPO_ROOT)
    try:
        # База пережила SIGKILL и открывается.
        before = runtime.sm.tasks_of(mission_id)
        assert before, "план, записанный до краха, должен сохраниться"
        tokens_before = runtime.ledger.mission_spend(mission_id).tokens
        assert tokens_before == 150, "расход до краха учтён"

        # Зависшую RUNNING-задачу возвращаем в очередь и доводим миссию.
        runtime.sm.release_stale_running(older_than_s=-1)
        code, _results = Supervisor(runtime).resume()

        after = runtime.sm.tasks_of(mission_id)
        assert len(after) == len(before), "resume не должен плодить дубликаты задач"

        keys = [t.brief.get("plan_key") for t in after if t.brief]
        assert len(keys) == len(set(keys)), "идемпотентность плана нарушена"

        # Повторная запись того же вызова не удваивает расход.
        runtime.ledger.record(
            provider="mock", model="mock-small", tokens_in=100, tokens_out=50,
            mission_id=mission_id, dedupe_key="crash-call",
        )
        duplicated = runtime.store.scalar(
            "SELECT COUNT(*) AS n FROM usage WHERE dedupe_key='crash-call'", (), 0
        )
        assert duplicated == 1, "dedupe_key должен защищать счётчик после краха"
        assert code in (0, 1, 10)
    finally:
        runtime.close()
