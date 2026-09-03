"""Хранилище AgentOS: одна SQLite-база на всё состояние и всю память.

Почему SQLite: нужна транзакционность на чекпоинтах (иначе resume после краша
неотличим от повторного выполнения), FTS5 для поиска по знаниям и работа
без сервера — систему должно быть можно просто скачать и запустить.

Схема версионируется: `schema_version` в таблице kv, миграции — список
SQL-шагов, применяемых по порядку. Понижение версии не поддерживается.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# Каждый элемент — одна миграция. Индекс + 1 = номер версии схемы.
MIGRATIONS: list[str] = [
    # --- v1: базовая схема -------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS kv (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS missions (
        id            TEXT PRIMARY KEY,
        goal          TEXT NOT NULL,
        context       TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL,
        mode          TEXT NOT NULL DEFAULT 'auto',
        budget_tokens INTEGER NOT NULL DEFAULT 0,
        budget_usd    REAL    NOT NULL DEFAULT 0,
        used_tokens   INTEGER NOT NULL DEFAULT 0,
        used_usd      REAL    NOT NULL DEFAULT 0,
        blocked_reason TEXT NOT NULL DEFAULT '',
        resume_after  REAL,
        meta          TEXT NOT NULL DEFAULT '{}',
        created_at    REAL NOT NULL,
        updated_at    REAL NOT NULL
    );

    -- Критерии приёмки. Фиксируются на входе, по ним судит критик.
    CREATE TABLE IF NOT EXISTS dod (
        id          TEXT PRIMARY KEY,
        mission_id  TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
        ord         INTEGER NOT NULL DEFAULT 0,
        criterion   TEXT NOT NULL,
        kind        TEXT NOT NULL DEFAULT 'semantic',  -- semantic | programmatic
        cmd         TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'pending',   -- pending | pass | fail
        evidence    TEXT NOT NULL DEFAULT '',
        updated_at  REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id              TEXT PRIMARY KEY,
        mission_id      TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
        parent_id       TEXT,
        title           TEXT NOT NULL,
        role            TEXT NOT NULL,
        tier            TEXT NOT NULL DEFAULT 'small',
        priority        INTEGER NOT NULL DEFAULT 2,
        status          TEXT NOT NULL,
        brief           TEXT NOT NULL DEFAULT '{}',
        result          TEXT NOT NULL DEFAULT '',
        attempts        INTEGER NOT NULL DEFAULT 0,
        est_tokens      INTEGER NOT NULL DEFAULT 0,
        used_tokens     INTEGER NOT NULL DEFAULT 0,
        used_usd        REAL    NOT NULL DEFAULT 0,
        budget_tokens   INTEGER NOT NULL DEFAULT 0,
        idempotency_key TEXT UNIQUE,
        blocked_reason  TEXT NOT NULL DEFAULT '',
        resume_after    REAL,
        provider        TEXT NOT NULL DEFAULT '',
        model           TEXT NOT NULL DEFAULT '',
        created_at      REAL NOT NULL,
        updated_at      REAL NOT NULL,
        started_at      REAL,
        finished_at     REAL
    );
    CREATE INDEX IF NOT EXISTS idx_tasks_mission ON tasks(mission_id, status);
    CREATE INDEX IF NOT EXISTS idx_tasks_status  ON tasks(status, resume_after);

    CREATE TABLE IF NOT EXISTS task_deps (
        task_id    TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        depends_on TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        PRIMARY KEY (task_id, depends_on)
    );

    -- Эпизодическая память: append-only журнал всего, что произошло.
    CREATE TABLE IF NOT EXISTS events (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         REAL NOT NULL,
        mission_id TEXT NOT NULL DEFAULT '',
        task_id    TEXT NOT NULL DEFAULT '',
        actor      TEXT NOT NULL DEFAULT '',
        kind       TEXT NOT NULL,
        payload    TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_events_mission ON events(mission_id, id);
    CREATE INDEX IF NOT EXISTS idx_events_kind    ON events(kind, id);

    -- Леджер расхода: единственный источник правды по токенам и деньгам.
    CREATE TABLE IF NOT EXISTS usage (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          REAL NOT NULL,
        mission_id  TEXT NOT NULL DEFAULT '',
        task_id     TEXT NOT NULL DEFAULT '',
        provider    TEXT NOT NULL,
        model       TEXT NOT NULL,
        tokens_in   INTEGER NOT NULL DEFAULT 0,
        tokens_out  INTEGER NOT NULL DEFAULT 0,
        cached_in   INTEGER NOT NULL DEFAULT 0,
        usd         REAL NOT NULL DEFAULT 0,
        kind        TEXT NOT NULL DEFAULT 'completion',
        dedupe_key  TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_usage_mission ON usage(mission_id, ts);

    -- Состояние лимитов по провайдерам: когда снова можно пробовать.
    CREATE TABLE IF NOT EXISTS quota (
        provider   TEXT PRIMARY KEY,
        state      TEXT NOT NULL DEFAULT 'ok',   -- ok | limited | exhausted
        reset_at   REAL,
        last_error TEXT NOT NULL DEFAULT '',
        updated_at REAL NOT NULL
    );

    -- Семантическая память: факты, уроки, решения.
    CREATE TABLE IF NOT EXISTS facts (
        id         TEXT PRIMARY KEY,
        mission_id TEXT NOT NULL DEFAULT '',
        kind       TEXT NOT NULL DEFAULT 'fact',  -- fact | lesson | decision | preference
        subject    TEXT NOT NULL DEFAULT '',
        content    TEXT NOT NULL,
        source     TEXT NOT NULL DEFAULT '',
        confidence REAL NOT NULL DEFAULT 0.5,
        uses       INTEGER NOT NULL DEFAULT 0,
        embedding  BLOB,
        embedder   TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind, updated_at);

    CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
        content, subject, kind UNINDEXED,
        content='facts', content_rowid='rowid'
    );

    -- Процедурная память: навыки. Тело лежит в skills/, здесь — индекс.
    CREATE TABLE IF NOT EXISTS skills (
        name        TEXT PRIMARY KEY,
        path        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        triggers    TEXT NOT NULL DEFAULT '[]',
        status      TEXT NOT NULL DEFAULT 'active',   -- active | proposed | retired
        version     INTEGER NOT NULL DEFAULT 1,
        uses        INTEGER NOT NULL DEFAULT 0,
        wins        INTEGER NOT NULL DEFAULT 0,
        losses      INTEGER NOT NULL DEFAULT 0,
        sha256      TEXT NOT NULL DEFAULT '',
        updated_at  REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS artifacts (
        id         TEXT PRIMARY KEY,
        mission_id TEXT NOT NULL DEFAULT '',
        task_id    TEXT NOT NULL DEFAULT '',
        path       TEXT NOT NULL,
        sha256     TEXT NOT NULL DEFAULT '',
        bytes      INTEGER NOT NULL DEFAULT 0,
        kind       TEXT NOT NULL DEFAULT 'file',
        created_at REAL NOT NULL
    );

    -- Реестр возможностей: что агент подключил сам и что ещё нужно от человека.
    CREATE TABLE IF NOT EXISTS capabilities (
        name       TEXT NOT NULL,
        kind       TEXT NOT NULL,                    -- skill | mcp | tool | secret
        status     TEXT NOT NULL DEFAULT 'requested',-- requested | enabled | blocked
        detail     TEXT NOT NULL DEFAULT '',
        mission_id TEXT NOT NULL DEFAULT '',
        updated_at REAL NOT NULL,
        PRIMARY KEY (kind, name)
    );

    -- Очередь того, что требует человека. Читается `agentctl status`.
    CREATE TABLE IF NOT EXISTS approvals (
        id         TEXT PRIMARY KEY,
        mission_id TEXT NOT NULL DEFAULT '',
        task_id    TEXT NOT NULL DEFAULT '',
        action     TEXT NOT NULL,
        detail     TEXT NOT NULL DEFAULT '',
        status     TEXT NOT NULL DEFAULT 'pending',  -- pending | granted | denied
        created_at REAL NOT NULL,
        decided_at REAL
    );
    """,
]


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def _split_statements(script: str) -> list[str]:
    """Разбить SQL-скрипт на отдельные операторы.

    executescript() сам делает COMMIT, чем рвёт нашу транзакцию, поэтому
    миграции применяются по одному оператору внутри одной транзакции —
    иначе прерванная миграция оставила бы половину схемы.
    """
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            text = buffer.strip()
            if text:
                statements.append(text)
            buffer = ""
    tail = buffer.strip()
    if tail:
        statements.append(tail)
    return statements


class Store:
    """Тонкая обёртка над SQLite: соединение, миграции, помощники.

    Каждый процесс держит своё соединение. Режим WAL позволяет главному
    агенту и субагентам писать параллельно.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
        self._conn.row_factory = _dict_factory
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self.migrate()

    # ------------------------------------------------------------- lifecycle
    def migrate(self) -> int:
        """Догнать схему до SCHEMA_VERSION. Возвращает применённую версию."""
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY,"
            " value TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        current = int(self.get_kv("schema_version", "0"))
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"база новее кода: schema_version={current}, код знает {SCHEMA_VERSION}"
            )
        for version in range(current, SCHEMA_VERSION):
            with self.tx() as conn:
                for statement in _split_statements(MIGRATIONS[version]):
                    conn.execute(statement)
                self.set_kv("schema_version", str(version + 1))
        return SCHEMA_VERSION

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- basics
    @contextlib.contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Транзакция. Чекпоинт без неё — не чекпоинт."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        return list(self._conn.execute(sql, params).fetchall())

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        row = self._conn.execute(sql, params).fetchone()
        return row if row else None

    def scalar(self, sql: str, params: tuple | dict = (), default: Any = None) -> Any:
        row = self._conn.execute(sql, params).fetchone()
        if not row:
            return default
        return next(iter(row.values()), default)

    # -------------------------------------------------------------------- kv
    def get_kv(self, key: str, default: str = "") -> str:
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return row["value"] if row else default

    def set_kv(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, time.time()),
        )

    def get_json(self, key: str, default: Any = None) -> Any:
        raw = self.get_kv(key, "")
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    def set_json(self, key: str, value: Any) -> None:
        self.set_kv(key, json.dumps(value, ensure_ascii=False, sort_keys=True))


def open_store(config: Any) -> Store:
    """Открыть хранилище по конфигу, создав нужные каталоги."""
    config.ensure_dirs()
    return Store(config.db_path)
