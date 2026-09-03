#!/usr/bin/env bash
# Неприсмотренный режим: крутить прогоны до завершения, уважая лимиты провайдеров.
# Нужен хотя бы один API-ключ. Останавливается сам, когда работы не осталось.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$ROOT"

MAX_ITER="${AGENTOS_HEADLESS_MAX_ITER:-0}"   # 0 = без ограничения
POLL="${AGENTOS_HEADLESS_POLL:-60}"          # пауза, когда всё ждёт квоту

i=0
while :; do
  i=$((i + 1))
  if [[ "$MAX_ITER" != "0" && "$i" -gt "$MAX_ITER" ]]; then
    log "достигнут предел итераций ($MAX_ITER)"; break
  fi

  set +e
  agentctl resume --mode direct --once
  rc=$?
  set -e

  case "$rc" in
    0)  log "работы не осталось — выходим"; break ;;
    75) sleep_for="$(agentctl status --resume-in-seconds 2>/dev/null || echo "$POLL")"
        log "лимиты исчерпаны, сплю ${sleep_for}s"
        sleep "$sleep_for" ;;
    10) log "нужен ввод человека — смотри: agentctl status"; break ;;
    *)  warn "resume завершился с кодом $rc, повтор через ${POLL}s"; sleep "$POLL" ;;
  esac
done
