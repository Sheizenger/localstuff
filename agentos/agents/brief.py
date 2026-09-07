"""Рендер брифа для агент-хоста (режим native).

В native-режиме субагентов запускает не AgentOS, а хост: Claude Code,
Codex CLI, Gemini CLI. Ему нужен не JSON, а понятный текст задания —
и точная команда, которой вернуть результат обратно в систему.
"""

from __future__ import annotations

from ..config import RoleSpec
from ..memory.working import Brief


def render_host_brief(
    *,
    brief: Brief,
    role: RoleSpec,
    task_id: str,
    mission_id: str,
) -> str:
    """Собрать задание для субагента агент-хоста."""
    tools = ", ".join(role.tools) if role.tools else "инструменты хоста"
    return f"""### Задание субагенту `{role.name}` ({role.title})

**Миссия:** {mission_id} · **Задача:** {task_id} · **Тир модели:** {role.tier}

{role.system}

---

{brief.render()}

---

**Инструменты:** {tools}

**Как вернуть результат** (обязательно, иначе задача не закроется):

```bash
agentctl task report {task_id} --json '<твой отчёт по схеме {brief.output_schema}>'
```

Если упёрся в лимит токенов:

```bash
agentctl task block {task_id} --reason quota
```

Если не хватает доступа, ключа или инструмента:

```bash
agentctl task block {task_id} --reason capability --detail "что именно нужно"
```
"""
