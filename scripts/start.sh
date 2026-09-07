#!/usr/bin/env bash
# Точка входа для человека: поставить цель или открыть статус.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$ROOT"

if [[ $# -eq 0 ]]; then
  agentctl status
  echo
  echo "Поставить цель:  make start GOAL=\"твоя абстрактная задача\""
  exit 0
fi

# Перед новой целью всегда сначала подхватываем незавершённое.
agentctl resume --announce --quiet || true
agentctl goal "$@"
