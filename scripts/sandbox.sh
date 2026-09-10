#!/usr/bin/env bash
# Запуск agentctl в контейнере: агент не дотянется до системы человека.
#
# Тонкая обёртка над `agentctl sandbox` — вся логика там, чтобы у песочницы
# не было двух реализаций, которые разъезжаются.
#
#   scripts/sandbox.sh doctor
#   scripts/sandbox.sh goal "почини сборку"
#   scripts/sandbox.sh mcp            # MCP-сервер внутри контейнера
#
# Настройки: AGENTOS_IMAGE, AGENTOS_DOCKER, AGENTOS_NETWORK (none — полная
# изоляция), AGENTOS_PROJECT, AGENTOS_GLOBAL_HOME, AGENTOS_SOURCE.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v agentctl >/dev/null 2>&1; then
  exec agentctl sandbox "$@"
fi

# AgentOS не поставлен как инструмент — работаем прямо из чекаута.
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON:-python3}" -m agentos.cli sandbox "$@"
