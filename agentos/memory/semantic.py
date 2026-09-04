"""Семантическая память: факты, уроки, решения, предпочтения.

Поиск гибридный: BM25 по FTS5 плюс косинус по векторам, слияние через
Reciprocal Rank Fusion. Причина: ключевые слова отлично находят имена
файлов, идентификаторы и точные формулировки, векторы — перефразировки.
Ни один из способов по отдельности не покрывает оба случая.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .store import Store
from .vector import BruteForceIndex, Embedder, pack

KIND_FACT = "fact"
KIND_LESSON = "lesson"
KIND_DECISION = "decision"
KIND_PREFERENCE = "preference"

_FTS_TOKEN = re.compile(r"[\w][\w\-]*", re.UNICODE)


def _fts_query(text: str) -> str:
    """Собрать безопасный MATCH-запрос.

    Пользовательский текст в MATCH нельзя подставлять как есть: кавычки и
    операторы FTS5 роняют запрос синтаксической ошибкой.
    """
    tokens = [t for t in _FTS_TOKEN.findall(text.lower()) if len(t) > 1][:24]
    return " OR ".join(f'"{t}"' for t in tokens)


@dataclass
class Fact:
    id: str
    kind: str
    subject: str
    content: str
    source: str = ""
    confidence: float = 0.5
    mission_id: str = ""
    uses: int = 0
    score: float = 0.0

    @classmethod
    def from_row(cls, row: dict[str, Any], score: float = 0.0) -> Fact:
        return cls(
            id=row["id"],
            kind=row["kind"],
            subject=row["subject"],
            content=row["content"],
            source=row["source"],
            confidence=float(row["confidence"]),
            mission_id=row["mission_id"],
            uses=int(row["uses"]),
            score=score,
        )

    def as_line(self) -> str:
        """Одна строка для вставки в контекст — компактно и со ссылкой."""
        prefix = {KIND_LESSON: "урок", KIND_DECISION: "решение", KIND_PREFERENCE: "предпочтение"}
        tag = prefix.get(self.kind, "факт")
        src = f" [{self.source}]" if self.source else ""
        subj = f"{self.subject}: " if self.subject else ""
        return f"- ({tag}) {subj}{self.content}{src}"


class SemanticMemory:
    def __init__(self, store: Store, embedder: Embedder, config: Any = None) -> None:
        self.store = store
        self.embedder = embedder
        self.config = config
        self.index = BruteForceIndex(store)

    # ------------------------------------------------------------------ write
    def add(
        self,
        content: str,
        *,
        kind: str = KIND_FACT,
        subject: str = "",
        source: str = "",
        confidence: float = 0.5,
        mission_id: str = "",
        dedupe: bool = True,
    ) -> str:
        """Записать факт. При dedupe одинаковый текст не дублируется."""
        content = content.strip()
        if not content:
            return ""
        if dedupe:
            existing = self.store.one(
                "SELECT id FROM facts WHERE content=? AND kind=?", (content, kind)
            )
            if existing:
                self.touch(existing["id"])
                return existing["id"]

        fact_id = f"f_{uuid.uuid4().hex[:12]}"
        now = time.time()
        vector = self.embedder.embed_one(f"{subject} {content}".strip())
        with self.store.tx() as conn:
            conn.execute(
                "INSERT INTO facts(id, mission_id, kind, subject, content, source, confidence,"
                " embedding, embedder, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    fact_id,
                    mission_id,
                    kind,
                    subject,
                    content,
                    source,
                    confidence,
                    pack(vector),
                    self.embedder.spec.id,
                    now,
                    now,
                ),
            )
            rowid = conn.execute("SELECT rowid FROM facts WHERE id=?", (fact_id,)).fetchone()[
                "rowid"
            ]
            conn.execute(
                "INSERT INTO facts_fts(rowid, content, subject, kind) VALUES(?,?,?,?)",
                (rowid, content, subject, kind),
            )
        return fact_id

    def add_many(self, items: list[dict[str, Any]], *, mission_id: str = "") -> list[str]:
        return [
            self.add(
                item.get("content", ""),
                kind=item.get("kind", KIND_FACT),
                subject=item.get("subject", ""),
                source=item.get("source", ""),
                confidence=float(item.get("confidence", 0.5)),
                mission_id=mission_id,
            )
            for item in items
            if item.get("content")
        ]

    def touch(self, fact_id: str) -> None:
        """Отметить использование — по этому счётчику видно, что реально нужно."""
        with self.store.tx() as conn:
            conn.execute(
                "UPDATE facts SET uses=uses+1, updated_at=? WHERE id=?", (time.time(), fact_id)
            )

    def forget(self, fact_id: str) -> None:
        with self.store.tx() as conn:
            row = conn.execute("SELECT rowid FROM facts WHERE id=?", (fact_id,)).fetchone()
            if row:
                conn.execute("DELETE FROM facts_fts WHERE rowid=?", (row["rowid"],))
            conn.execute("DELETE FROM facts WHERE id=?", (fact_id,))

    # ------------------------------------------------------------------- read
    def get(self, fact_id: str) -> Fact | None:
        row = self.store.one("SELECT * FROM facts WHERE id=?", (fact_id,))
        return Fact.from_row(row) if row else None

    def search(
        self,
        query: str,
        *,
        limit: int = 12,
        kinds: tuple[str, ...] = (),
        rrf_k: int = 60,
    ) -> list[Fact]:
        """Гибридный поиск: BM25 + косинус, слияние Reciprocal Rank Fusion.

        RRF выбран вместо взвешенной суммы, потому что не требует
        калибровать несопоставимые шкалы BM25 и косинуса.
        """
        query = query.strip()
        if not query:
            return []
        pool_size = max(limit * 4, 40)
        keyword_ids = self._keyword_ids(query, pool_size, kinds)
        vector_ids = [
            fid
            for fid, _ in self.index.search(
                self.embedder.embed_one(query), limit=pool_size, kinds=kinds
            )
        ]

        scores: dict[str, float] = {}
        for rank, fid in enumerate(keyword_ids):
            scores[fid] = scores.get(fid, 0.0) + 1.0 / (rrf_k + rank + 1)
        for rank, fid in enumerate(vector_ids):
            scores[fid] = scores.get(fid, 0.0) + 1.0 / (rrf_k + rank + 1)
        if not scores:
            return []

        top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        facts: list[Fact] = []
        for fid, score in top:
            row = self.store.one("SELECT * FROM facts WHERE id=?", (fid,))
            if row:
                facts.append(Fact.from_row(row, score))
        return facts

    def _keyword_ids(self, query: str, limit: int, kinds: tuple[str, ...]) -> list[str]:
        match = _fts_query(query)
        if not match:
            return []
        try:
            kind_filter = f" AND f.kind IN ({','.join('?' * len(kinds))})" if kinds else ""
            rows = self.store.query(
                "SELECT f.id AS id FROM facts_fts JOIN facts f ON f.rowid = facts_fts.rowid"
                f" WHERE facts_fts MATCH ?{kind_filter} ORDER BY bm25(facts_fts) LIMIT ?",
                (match, *kinds, limit),
            )
        except Exception:
            # Битый MATCH не должен ронять задачу — векторной половины хватит.
            return []
        return [r["id"] for r in rows]

    def recent(self, *, kind: str = "", limit: int = 20) -> list[Fact]:
        rows = self.store.query(
            "SELECT * FROM facts WHERE (?='' OR kind=?) ORDER BY updated_at DESC LIMIT ?",
            (kind, kind, limit),
        )
        return [Fact.from_row(r) for r in rows]

    def stats(self) -> dict[str, int]:
        rows = self.store.query("SELECT kind, COUNT(*) AS n FROM facts GROUP BY kind")
        return {r["kind"]: int(r["n"]) for r in rows}

    def reindex_vectors(self) -> int:
        """Пересчитать эмбеддинги при смене модели эмбеддера."""
        rows = self.store.query(
            "SELECT id, subject, content FROM facts WHERE embedder != ?",
            (self.embedder.spec.id,),
        )
        for row in rows:
            vector = self.embedder.embed_one(f"{row['subject']} {row['content']}".strip())
            with self.store.tx() as conn:
                conn.execute(
                    "UPDATE facts SET embedding=?, embedder=?, updated_at=? WHERE id=?",
                    (pack(vector), self.embedder.spec.id, time.time(), row["id"]),
                )
        return len(rows)
