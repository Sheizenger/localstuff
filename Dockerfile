# Образ для запуска AgentOS в изоляции от системы человека.
#
# Автономный агент выполняет команды. Политика в config/policy.yaml
# ограничивает их allowlist'ом, но allowlist — это про «что запускать», а не
# «где». Контейнер отвечает на второй вопрос: смонтирован только каталог
# проекта, остальная файловая система машины из него недостижима.

FROM python:3.11-slim

# git нужен агенту для работы с репозиторием проекта, curl — для диагностики.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl make ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /opt/agentos
COPY pyproject.toml README.md ./
COPY agentos ./agentos
COPY skills ./skills

RUN uv pip install --system --no-cache .

# Состояние и общее знание монтируются снаружи; здесь только точки монтирования.
VOLUME ["/work", "/root/.agentos"]
WORKDIR /work

ENTRYPOINT ["agentctl"]
CMD ["doctor"]
