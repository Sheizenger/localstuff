"""Векторный слой памяти.

Три уровня деградации, интерфейс один:
  1. sqlite-vec, если установлен — поиск на стороне SQLite;
  2. numpy — честный полный перебор, быстрый до сотен тысяч записей;
  3. чистый python — работает всегда, даже без numpy.

Эмбеддинги берутся у провайдера (OpenAI/Google) либо считаются локально
детерминированным хешированием. Локальный вариант не понимает смысла, но
даёт стабильный, воспроизводимый вектор — этого достаточно, чтобы тесты и
работа без ключей шли по тому же коду, что и боевой режим.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from typing import Any

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def hash_embed(text: str, dim: int = 512) -> list[float]:
    """Детерминированный локальный эмбеддинг (hashing trick + L2-нормировка).

    Токен попадает в фиксированную позицию по хешу, знак тоже из хеша —
    так похожие тексты дают похожие векторы без обращения к сети.
    """
    vector = [0.0] * dim
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


def pack(vector: list[float]) -> bytes:
    """Вектор -> BLOB (float32), как он лежит в SQLite."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob[: count * 4]))


def cosine(a: list[float], b: list[float]) -> float:
    """Косинус. Векторы нормированы не всегда — считаем честно."""
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = num_a = num_b = 0.0
    for i in range(size):
        dot += a[i] * b[i]
        num_a += a[i] * a[i]
        num_b += b[i] * b[i]
    if num_a == 0.0 or num_b == 0.0:
        return 0.0
    return dot / math.sqrt(num_a * num_b)


class Embedder:
    """Считает эмбеддинги: у провайдера, если можем, иначе локально."""

    def __init__(self, config: Any, router: Any = None) -> None:
        self.config = config
        self.router = router
        self.spec = config.embedder()

    @property
    def dim(self) -> int:
        return self.spec.dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.spec.provider == "local":
            return [hash_embed(t, self.dim) for t in texts]
        try:
            from ..providers.registry import get_provider

            provider = get_provider(self.spec.provider)
            if provider.available():
                return provider.embed(model=self.spec.id, texts=texts)
        except Exception:
            # Падение эмбеддера не должно ронять задачу: молча уходим в локальный.
            pass
        return [hash_embed(t, self.dim) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class BruteForceIndex:
    """Полный перебор по векторам из таблицы facts.

    numpy используется, если он есть; иначе тот же алгоритм на чистом python.
    Индексных структур намеренно нет: до сотен тысяч фактов перебор быстрее
    и на порядок проще в сопровождении, чем ANN-индекс, который надо
    перестраивать и держать согласованным с БД.
    """

    def __init__(self, store: Any) -> None:
        self.store = store
        try:
            import numpy  # noqa: F401

            self._numpy = True
        except ImportError:
            self._numpy = False

    @property
    def backend(self) -> str:
        return "numpy" if self._numpy else "python"

    def search(
        self, query_vec: list[float], *, limit: int = 20, kinds: tuple[str, ...] = ()
    ) -> list[tuple[str, float]]:
        sql = "SELECT id, embedding FROM facts WHERE embedding IS NOT NULL"
        params: list[Any] = []
        if kinds:
            sql += " AND kind IN (%s)" % ",".join("?" * len(kinds))
            params += list(kinds)
        rows = self.store.query(sql, tuple(params))
        if not rows:
            return []
        if self._numpy:
            return self._search_numpy(rows, query_vec, limit)
        scored = [(r["id"], cosine(query_vec, unpack(r["embedding"]))) for r in rows]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _search_numpy(
        self, rows: list[dict[str, Any]], query_vec: list[float], limit: int
    ) -> list[tuple[str, float]]:
        import numpy as np

        dim = len(query_vec)
        matrix = np.zeros((len(rows), dim), dtype=np.float32)
        for i, row in enumerate(rows):
            vec = unpack(row["embedding"])[:dim]
            matrix[i, : len(vec)] = vec
        query = np.asarray(query_vec, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query) or 1.0)
        norms[norms == 0] = 1.0
        scores = (matrix @ query) / norms
        order = np.argsort(-scores)[:limit]
        return [(rows[int(i)]["id"], float(scores[int(i)])) for i in order]
