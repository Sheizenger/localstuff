#!/usr/bin/env bash
# Общие функции для скриптов запуска AgentOS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"

log()  { printf '\033[36m[agentos]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[33m[agentos]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m[agentos]\033[0m %s\n' "$*" >&2; exit 1; }

# Загрузить .env, если он есть (значения не перетирают уже заданное окружение).
load_env() {
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
  fi
}

# Найти рабочий python: venv -> uv -> системный.
agentos_python() {
  if [[ -x "$VENV/bin/python" ]]; then
    echo "$VENV/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    echo "python3"
  else
    die "python3 не найден"
  fi
}

# Запустить agentctl любым доступным способом.
agentctl() {
  load_env
  local py; py="$(agentos_python)"
  PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$py" -m agentos.cli "$@"
}
