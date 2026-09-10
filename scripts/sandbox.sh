#!/usr/bin/env bash
# Запуск agentctl в контейнере: агент не дотянется до системы человека.
#
# Монтируется ровно два каталога — проект и общая память AgentOS. Всё
# остальное на машине из контейнера не видно. Ни --privileged, ни доступа к
# docker-сокету: агенту, который сам решает, что запускать, нельзя давать
# возможность выйти наружу.
#
#   scripts/sandbox.sh doctor
#   scripts/sandbox.sh goal "почини сборку"
#   scripts/sandbox.sh mcp          # MCP-сервер внутри контейнера
set -euo pipefail

IMAGE="${AGENTOS_IMAGE:-agentos:local}"
PROJECT="${AGENTOS_PROJECT:-$PWD}"
GLOBAL="${AGENTOS_GLOBAL_HOME:-$HOME/.agentos}"
DOCKER="${AGENTOS_DOCKER:-docker}"
# none — полная изоляция; bridge нужен, только если агент ходит к API моделей.
NETWORK="${AGENTOS_NETWORK:-bridge}"

if ! command -v "$DOCKER" >/dev/null 2>&1; then
  echo "нужен docker (или podman через AGENTOS_DOCKER=podman)" >&2
  exit 1
fi

if ! "$DOCKER" image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "собираю образ $IMAGE…" >&2
  "$DOCKER" build -t "$IMAGE" "$(dirname "${BASH_SOURCE[0]}")/.."
fi

mkdir -p "$GLOBAL"

# Ключи передаются по именам, а не значениями в командной строке: иначе они
# попали бы в историю оболочки и в вывод ps.
env_flags=()
for name in ANTHROPIC_API_KEY OPENAI_API_KEY GOOGLE_API_KEY GEMINI_API_KEY \
            HINDSIGHT_BASE_URL HINDSIGHT_API_KEY AGENTOS_ALLOW_MOCK; do
  [[ -n "${!name:-}" ]] && env_flags+=(-e "$name")
done

exec "$DOCKER" run --rm -i \
  --network "$NETWORK" \
  --security-opt no-new-privileges \
  -v "$PROJECT:/work" \
  -v "$GLOBAL:/root/.agentos" \
  -w /work \
  "${env_flags[@]}" \
  "$IMAGE" "$@"
