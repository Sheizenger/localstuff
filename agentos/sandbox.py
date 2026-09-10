"""Запуск AgentOS в контейнере — изоляция от системы человека.

Политика (`config/policy.yaml`) ограничивает, *что* агент запускает.
Контейнер отвечает на второй вопрос — *где*: внутрь смонтированы ровно два
каталога, проект и общая память, и остальная машина недостижима.

Здесь же собирается образ, если его ещё нет. Собрать его можно двумя
способами, и оба нужны: из чекаута репозитория, когда человек работает в
нём, и из git-ссылки, когда AgentOS поставлен как инструмент и никакого
чекаута рядом нет — именно так система и ставится в чужом проекте.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

#: Переменные, которые имеет смысл пробросить внутрь. Передаются по имени, а
#: не значением: иначе ключ попал бы в историю оболочки и в вывод `ps`.
PASSTHROUGH = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "HINDSIGHT_BASE_URL",
    "HINDSIGHT_API_KEY",
    "AGENTOS_ALLOW_MOCK",
    "AGENTOS_AGENT_ID",
    "AGENTOS_MODE",
)

DEFAULT_IMAGE = "agentos:local"
DEFAULT_SOURCE = "git+https://github.com/Sheizenger/localstuff@main"

#: Dockerfile для сборки без чекаута репозитория.
REMOTE_DOCKERFILE = """\
FROM python:3.11-slim

RUN apt-get update \\
    && apt-get install -y --no-install-recommends git curl make ca-certificates \\
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ARG AGENTOS_SOURCE
RUN uv pip install --system --no-cache "agentos @ ${AGENTOS_SOURCE}"

VOLUME ["/work", "/root/.agentos"]
WORKDIR /work
ENTRYPOINT ["agentctl"]
CMD ["doctor"]
"""


class SandboxError(RuntimeError):
    """Песочницу не удалось поднять — с внятной причиной для человека."""


@dataclass
class Sandbox:
    """Параметры запуска. Всё переопределяется переменными окружения."""

    project: Path
    global_home: Path
    image: str = DEFAULT_IMAGE
    docker: str = "docker"
    network: str = "bridge"
    source: str = DEFAULT_SOURCE
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))

    @classmethod
    def from_env(
        cls, project: Path | str | None = None, env: dict[str, str] | None = None
    ) -> Sandbox:
        env = dict(env if env is not None else os.environ)
        home = env.get("HOME", str(Path.home()))
        return cls(
            project=Path(env.get("AGENTOS_PROJECT") or project or Path.cwd()).resolve(),
            global_home=Path(env.get("AGENTOS_GLOBAL_HOME") or Path(home) / ".agentos"),
            image=env.get("AGENTOS_IMAGE") or DEFAULT_IMAGE,
            docker=env.get("AGENTOS_DOCKER") or "docker",
            # none — полная изоляция; bridge нужен, только если агент ходит
            # к API моделей или к git.
            network=env.get("AGENTOS_NETWORK") or "bridge",
            source=env.get("AGENTOS_SOURCE") or DEFAULT_SOURCE,
            env=env,
        )

    # ------------------------------------------------------------- команда
    def run_argv(self, args: list[str]) -> list[str]:
        """Полная команда запуска. Вынесена отдельно, чтобы её проверяли тесты.

        Всё, чем песочница может навредить, живёт именно здесь: что
        смонтировано, с какими правами и как передаются ключи.
        """
        argv = [
            self.docker,
            "run",
            "--rm",
            "-i",
            "--network",
            self.network,
            "--security-opt",
            "no-new-privileges",
            "-v",
            f"{self.project}:/work",
            "-v",
            f"{self.global_home}:/root/.agentos",
            "-w",
            "/work",
        ]
        for name in PASSTHROUGH:
            if self.env.get(name):
                argv += ["-e", name]
        argv.append(self.image)
        argv += args
        return argv

    def build_argv(self, context: Path, *, dockerfile: Path | None = None) -> list[str]:
        argv = [self.docker, "build", "-t", self.image]
        if dockerfile is not None:
            argv += ["-f", str(dockerfile), "--build-arg", f"AGENTOS_SOURCE={self.source}"]
        argv.append(str(context))
        return argv

    # ------------------------------------------------------------- запуск
    def require_docker(self) -> None:
        if shutil.which(self.docker) is None:
            raise SandboxError(
                f"нужен {self.docker}: поставьте Docker или укажите другой движок"
                " через AGENTOS_DOCKER=podman"
            )

    def image_exists(self) -> bool:
        result = subprocess.run(
            [self.docker, "image", "inspect", self.image],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def repo_context(self) -> Path | None:
        """Чекаут репозитория рядом с пакетом, если он есть."""
        root = Path(__file__).resolve().parent.parent
        return root if (root / "Dockerfile").exists() else None

    def build(self, *, printer=print) -> None:
        """Собрать образ: из чекаута, если он есть, иначе из git-ссылки."""
        self.require_docker()
        context = self.repo_context()
        if context is not None:
            printer(f"собираю {self.image} из {context}…")
            argv = self.build_argv(context)
            code = subprocess.call(argv)
        else:
            printer(f"собираю {self.image} из {self.source}…")
            with tempfile.TemporaryDirectory() as tmp:
                dockerfile = Path(tmp) / "Dockerfile"
                dockerfile.write_text(REMOTE_DOCKERFILE, encoding="utf-8")
                argv = self.build_argv(Path(tmp), dockerfile=dockerfile)
                code = subprocess.call(argv)
        if code != 0:
            raise SandboxError(f"сборка образа не удалась (код {code})")

    def run(self, args: list[str], *, printer=print) -> int:
        self.require_docker()
        if not self.image_exists():
            self.build(printer=printer)
        self.global_home.mkdir(parents=True, exist_ok=True)
        return subprocess.call(self.run_argv(args))
