#!/usr/bin/env bash
# Одноразовая установка: venv, зависимости, инициализация БД и индексов.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$ROOT"

EXTRAS="${AGENTOS_EXTRAS:-dev}"

if command -v uv >/dev/null 2>&1; then
  log "uv найден — создаю окружение"
  uv venv --python 3.11 "$VENV" >/dev/null
  uv pip install --python "$VENV/bin/python" -e ".[$EXTRAS]"
else
  warn "uv не найден — использую python -m venv (медленнее)"
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  "$VENV/bin/python" -m pip install -e ".[$EXTRAS]"
fi

log "инициализирую состояние в var/"
agentctl init

log "синхронизирую описания субагентов для агент-хостов"
agentctl agents sync || warn "agents sync пропущен"

log "готово. Дальше: make doctor, затем make start GOAL=\"...\""
