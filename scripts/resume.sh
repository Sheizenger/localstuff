#!/usr/bin/env bash
# Продолжить незавершённые прогоны. Вызывается SessionStart-хуком и вручную.
# --announce печатает ОДНУ строку статуса, чтобы не жечь контекст сессии.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$ROOT"

# Хук не должен ронять сессию, если окружение ещё не собрано.
if [[ ! -d "$ROOT/var" ]]; then
  exit 0
fi

agentctl resume "$@" || true
