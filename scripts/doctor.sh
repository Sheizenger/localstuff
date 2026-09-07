#!/usr/bin/env bash
# Healthcheck: python, зависимости, конфиги, ключи, БД, права.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$ROOT"
agentctl doctor "$@"
