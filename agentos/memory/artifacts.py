"""Хранилище артефактов — файловых результатов работы.

Артефакты адресуются по хешу содержимого: одинаковый результат, записанный
дважды (например, после resume), не порождает две копии и не ломает учёт.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .store import Store


@dataclass
class Artifact:
    id: str
    path: Path
    sha256: str
    bytes: int
    kind: str
    mission_id: str = ""
    task_id: str = ""

    def as_line(self) -> str:
        return f"- {self.path.name} ({self.kind}, {self.bytes} Б, sha {self.sha256[:8]})"


class ArtifactStore:
    def __init__(self, store: Store, artifacts_dir: Path) -> None:
        self.store = store
        self.dir = artifacts_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def put_text(
        self,
        name: str,
        text: str,
        *,
        mission_id: str = "",
        task_id: str = "",
        kind: str = "text",
    ) -> Artifact:
        data = text.encode("utf-8")
        sha = hashlib.sha256(data).hexdigest()
        target = self.dir / mission_id if mission_id else self.dir
        target.mkdir(parents=True, exist_ok=True)
        path = target / name
        path.write_bytes(data)
        return self._register(path, sha, len(data), kind, mission_id, task_id)

    def register_file(
        self, path: Path, *, mission_id: str = "", task_id: str = "", kind: str = "file"
    ) -> Artifact:
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        return self._register(path, sha, len(data), kind, mission_id, task_id)

    def _register(
        self, path: Path, sha: str, size: int, kind: str, mission_id: str, task_id: str
    ) -> Artifact:
        existing = self.store.one(
            "SELECT * FROM artifacts WHERE sha256=? AND path=?", (sha, str(path))
        )
        if existing:
            return Artifact(
                id=existing["id"],
                path=Path(existing["path"]),
                sha256=existing["sha256"],
                bytes=int(existing["bytes"]),
                kind=existing["kind"],
                mission_id=existing["mission_id"],
                task_id=existing["task_id"],
            )
        artifact_id = f"a_{uuid.uuid4().hex[:12]}"
        with self.store.tx() as conn:
            conn.execute(
                "INSERT INTO artifacts(id, mission_id, task_id, path, sha256, bytes, kind,"
                " created_at) VALUES(?,?,?,?,?,?,?,?)",
                (artifact_id, mission_id, task_id, str(path), sha, size, kind, time.time()),
            )
        return Artifact(artifact_id, path, sha, size, kind, mission_id, task_id)

    def of_mission(self, mission_id: str) -> list[Artifact]:
        rows = self.store.query(
            "SELECT * FROM artifacts WHERE mission_id=? ORDER BY created_at", (mission_id,)
        )
        return [
            Artifact(
                id=r["id"],
                path=Path(r["path"]),
                sha256=r["sha256"],
                bytes=int(r["bytes"]),
                kind=r["kind"],
                mission_id=r["mission_id"],
                task_id=r["task_id"],
            )
            for r in rows
        ]

    def read(self, artifact_id: str) -> str:
        row = self.store.one("SELECT path FROM artifacts WHERE id=?", (artifact_id,))
        if not row:
            return ""
        path = Path(row["path"])
        return path.read_text(encoding="utf-8") if path.exists() else ""
