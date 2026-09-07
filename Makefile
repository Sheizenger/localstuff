# AgentOS — команды верхнего уровня.
# Всё работает без API-ключей: по умолчанию используется mock-провайдер.

SHELL := /bin/bash
PY ?= python3
VENV := .venv
BIN := $(VENV)/bin

.DEFAULT_GOAL := help

.PHONY: help bootstrap doctor start resume status test lint fmt typecheck eval clean agents

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Создать venv, поставить зависимости, инициализировать БД
	@bash scripts/bootstrap.sh

doctor: ## Проверить окружение, конфиги, ключи, БД
	@bash scripts/doctor.sh

start: ## Поставить цель агенту: make start GOAL="..."
	@bash scripts/start.sh $(if $(GOAL),--goal "$(GOAL)",)

resume: ## Продолжить незавершённые прогоны
	@bash scripts/resume.sh

status: ## Короткий дайджест: что сделано, что блокирует
	@$(BIN)/agentctl status

agents: ## Пересобрать .claude/agents из config/agents/*.yaml
	@$(BIN)/agentctl agents sync

test: ## Прогнать все тесты (без ключей)
	@$(BIN)/python -m pytest

lint: ## ruff
	@$(BIN)/ruff check agentos tests

fmt: ## ruff format
	@$(BIN)/ruff format agentos tests

typecheck: ## mypy
	@$(BIN)/mypy

eval: ## Прогнать эталонные миссии из evals/
	@$(BIN)/agentctl eval run

clean: ## Удалить рантайм-состояние (НЕОБРАТИМО)
	@rm -rf var
	@echo "var/ удалён"
