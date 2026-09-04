"""Сквозной прогон CLI отдельными процессами.

Именно так с системой разговаривает агент-хост, поэтому проверяются не
внутренние объекты, а коды выхода и текст, который он читает.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def cli(tmp_path):
    env = dict(os.environ)
    env.update(
        {
            "AGENTOS_HOME": str(tmp_path / "var"),
            "AGENTOS_ALLOW_MOCK": "1",
            "AGENTOS_IN_GATE": "1",
            "AGENTOS_MOCK_STATE": str(tmp_path / "calls.txt"),
            "PYTHONPATH": str(REPO_ROOT),
        }
    )

    def run(*args: str, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, "-m", "agentos.cli", *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
            timeout=180,
        )
        if expect_ok:
            assert result.returncode in (0, 1), (
                f"agentctl {' '.join(args)} -> {result.returncode}\n"
                f"{result.stdout}\n{result.stderr}"
            )
        return result

    return run


def test_init_and_doctor_report_a_working_setup(cli):
    init = cli("init")
    assert "схема БД" in init.stdout

    doctor = cli("doctor")
    assert doctor.returncode == 0, f"doctor нашёл блокирующие проблемы:\n{doctor.stdout}"
    assert "Каталог моделей" in doctor.stdout
    assert "Гейты приёмки" in doctor.stdout


def test_native_flow_hands_briefs_and_accepts_reports(cli):
    """Полный цикл общения агент-хоста с системой."""
    cli("init")
    goal = cli("--mode", "native", "goal", "навести порядок в документации")
    assert "Задания субагентам" in goal.stdout
    assert "agentctl task report" in goal.stdout

    status = cli("status", "--json")
    digest = json.loads(status.stdout)
    mission_id = digest["missions"][0]["mission_id"]

    # Достаём выданное задание из вывода, как это делает агент-хост.
    task_id = next(
        line.strip().split(":")[0]
        for line in goal.stdout.splitlines()
        if line.strip().startswith("t_")
    )

    report = cli(
        "task",
        "report",
        task_id,
        "--json",
        json.dumps({"summary": "документация разбросана", "findings": ["docs/ пуст"]}),
    )
    assert "закрыта" in report.stdout

    show = cli("task", "show", task_id)
    assert json.loads(show.stdout)["status"] == "DONE"

    resumed = cli("--mode", "native", "resume")
    assert mission_id in resumed.stdout or "Задания субагентам" in resumed.stdout


def test_resume_is_quiet_and_single_line_when_announcing(cli):
    cli("init")
    result = cli("resume", "--announce", "--quiet")
    assert result.returncode == 0
    assert result.stdout.strip().count("\n") == 0


def test_status_resume_in_seconds_is_machine_readable(cli):
    """scripts/headless.sh спит ровно столько, сколько скажет эта команда."""
    cli("init")
    result = cli("status", "--resume-in-seconds")
    assert result.stdout.strip().isdigit()


def test_broken_pipe_is_not_a_crash(cli):
    """`agentctl ... | head` не должен выглядеть как падение системы."""
    cli("init")
    process = subprocess.run(
        f"{sys.executable} -m agentos.cli doctor | head -2",
        shell=True,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=dict(os.environ, PYTHONPATH=str(REPO_ROOT), AGENTOS_ALLOW_MOCK="1"),
        timeout=120,
    )
    assert "Traceback" not in process.stderr


def test_eval_runs_golden_missions(cli):
    result = cli("eval", "run", "--json")
    report = json.loads(result.stdout)
    assert report["total"] >= 2
    assert report["passed"] == report["total"], report["cases"]
