# Реализация

## Карта модулей

```
agentos/
  cli.py            agentctl — единственный интерфейс к системе
  runtime.py        сборка подсистем; выбор режима native/direct
  config.py         конфиги, каталог моделей, роли
  errors.py         нормализованные ошибки, по которым решает оркестратор
  bus.py            журнал событий: БД + JSONL, с редакцией секретов
  evals.py          прогон эталонных миссий

  providers/        base · anthropic · openai · google · mock · router · registry
  memory/           store · semantic · episodic · procedural · working · vector · artifacts
  orchestrator/     intake · planner · scheduler · dispatch · critic · improve · supervisor
  agents/           roles · brief · report
  tools/            base · fs · shell · http · mcp_client · capability
  policy/           guard · redact
  state/            machine · checkpoint
  telemetry/        ledger · quota
```

## Порядок вызовов при постановке цели

```
agentctl goal
  └ Supervisor.start
      ├ Intake.create ............ цель → миссия + критерии приёмки (DoD)
      ├ Planner.build/persist ..... DoD → DAG задач с ролями и бюджетами
      └ Supervisor.advance
          ├ Scheduler.run ........ параллельное исполнение готовых веток
          │   └ Dispatcher.execute  бриф → native-задание либо цикл tool-use
          ├ Critic.verify ........ гейты → критик → задачи на исправление
          ├ Improver.consolidate .. эпизоды → факты, уроки, черновики навыков
          └ Checkpointer.write .... снимок состояния + var/resume.json
```

## Что правится данными, а не кодом

| Что | Где |
|---|---|
| Роли субагентов, их приоритеты, тиры, триггеры, инструменты | `config/agents/*.yaml` |
| Модели, тиры, цены, порядок провайдеров | `config/models.yaml` |
| Бюджеты, параллелизм, квоты, самопроверка, консолидация | `config/agentos.yaml` |
| Что разрешено и что требует человека | `config/policy.yaml` |
| Каталог MCP-серверов | `config/mcp.json` |
| Навыки | `skills/<имя>/SKILL.md` |
| Эталонные миссии | `evals/missions/*.yaml` |

После правки ролей: `agentctl agents sync` — пересоберёт описания для
агент-хоста.

## Как добавить

**Провайдера.** Наследника `providers/base.Provider` с `available()`,
`complete()` и нормализацией ошибок в типы из `errors.py` — особенно
`QuotaExhausted`, на ней держится авто-resume. Зарегистрировать в
`providers/registry._builders()`, добавить модели в `config/models.yaml`.

**Инструмент.** `tools/base.Tool` с JSON-схемой; проверки — через
`PolicyGuard`. Зарегистрировать в `Runtime.tools`. Схема уходит любому
провайдеру в его родном формате без дополнительного кода.

**Роль.** Скопировать ближайший `config/agents/*.yaml`, задать `triggers`,
`tier`, `tools`. Проверить подбор: `agentctl role match "типичная задача"`.

**MCP-сервер.** Дописать в `config/mcp.json`. `auto: true` — агент
подключит сам; `requires_env` — список переменных, без которых он
сформирует запрос человеку.

## Решения, которые иначе выглядят произвольными

**SQLite, а не серверная БД.** Нужна транзакционность чекпоинтов (без неё
resume после краша неотличим от повторного выполнения) и FTS5 для поиска.
Сервер добавил бы установку и эксплуатацию к системе, которую должно быть
можно просто скачать и запустить.

**RRF, а не взвешенная сумма BM25 и косинуса.** Взвешивание требует
калибровки несопоставимых шкал и перекалибровки при смене эмбеддера. RRF
работает с рангами и не требует ни того, ни другого.

**Полный перебор векторов, а не ANN-индекс.** До сотен тысяч фактов
перебор быстрее по суммарной стоимости владения: ANN-индекс нужно
перестраивать и держать согласованным с БД, а выигрыш появляется на
объёмах, которых у памяти проекта не бывает.

**Mock не включается сам.** Раньше он подменял провайдера при отсутствии
ключей — и в native-режиме выдуманный план выглядел бы как настоящий.
Теперь нужен явный `AGENTOS_ALLOW_MOCK=1`, а без ключей intake и planner
уходят на детерминированные заготовки, рассуждает же агент-хост.

**Оболочек нет в allow_binaries.** `sh -c '...'` обошёл бы весь allowlist,
сделав его декоративным.

## Ловушки, на которых уже спотыкались

- В YAML голые `true`, `false`, `on`, `off`, `yes`, `no` — булевы значения.
  В `allow_binaries` имя команды `true` нужно брать в кавычки, иначе
  allowlist молча ломается. `agentctl doctor` теперь это проверяет.
- `sqlite3.Connection.executescript()` делает неявный `COMMIT` и рвёт
  внешнюю транзакцию: миграции применяются по одному оператору.
- Имена `kind`, `mission_id`, `task_id`, `actor` — параметры `EventBus.emit`;
  в payload они переименовываются, иначе получается невнятный `TypeError`.
