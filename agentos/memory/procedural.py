"""Процедурная память — навыки.

Навык = каталог skills/<name>/ с файлом SKILL.md, у которого есть
YAML-фронтматтер (name, description, triggers). Тело навыка в контекст
не грузится: агент видит только имя и описание и подтягивает тело по
необходимости. Это и есть постепенное раскрытие — иначе десяток навыков
съел бы контекст раньше самой задачи.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .store import Store

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)

STATUS_ACTIVE = "active"
STATUS_PROPOSED = "proposed"
STATUS_RETIRED = "retired"


@dataclass
class Skill:
    name: str
    path: Path
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    status: str = STATUS_ACTIVE
    version: int = 1
    uses: int = 0
    wins: int = 0
    losses: int = 0
    body: str = ""

    def header(self) -> str:
        """Одна строка для каталога навыков в контексте."""
        trig = f" (триггеры: {', '.join(self.triggers)})" if self.triggers else ""
        return f"- {self.name}: {self.description}{trig}"

    @property
    def score(self) -> float:
        """Полезность навыка по истории применения. Нейтраль — 0.5."""
        total = self.wins + self.losses
        return 0.5 if total == 0 else self.wins / total


def parse_skill_file(path: Path) -> tuple[dict[str, Any], str]:
    """Разобрать SKILL.md на фронтматтер и тело."""
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), match.group(2)


class SkillLibrary:
    """Индекс навыков в БД + чтение тел с диска."""

    def __init__(self, store: Store, skills_dir: Path) -> None:
        self.store = store
        self.skills_dir = skills_dir

    # ------------------------------------------------------------------ sync
    def sync(self) -> dict[str, int]:
        """Пересобрать индекс из файлов. Идемпотентно.

        Навыки, чьи файлы исчезли, помечаются retired, а не удаляются:
        статистика применения переживает переименования и откаты.
        """
        seen: set[str] = set()
        added = updated = 0
        if self.skills_dir.exists():
            # Активные навыки — skills/<имя>/SKILL.md, черновики на уровень
            # глубже — skills/_proposed/<имя>/SKILL.md.
            found = sorted(
                [*self.skills_dir.glob("*/SKILL.md"), *self.skills_dir.glob("_proposed/*/SKILL.md")]
            )
            for skill_md in found:
                meta, _body = parse_skill_file(skill_md)
                name = str(meta.get("name") or skill_md.parent.name)
                status = (
                    STATUS_PROPOSED
                    if skill_md.parent.parent.name == "_proposed"
                    else str(meta.get("status", STATUS_ACTIVE))
                )
                sha = hashlib.sha256(skill_md.read_bytes()).hexdigest()[:16]
                rel = str(skill_md.relative_to(self.skills_dir.parent))
                triggers = json.dumps(list(meta.get("triggers") or []), ensure_ascii=False)
                existing = self.store.one("SELECT sha256 FROM skills WHERE name=?", (name,))
                with self.store.tx() as conn:
                    conn.execute(
                        "INSERT INTO skills(name, path, description, triggers, status, version,"
                        " sha256, updated_at) VALUES(?,?,?,?,?,?,?,?)"
                        " ON CONFLICT(name) DO UPDATE SET path=excluded.path,"
                        " description=excluded.description, triggers=excluded.triggers,"
                        " status=excluded.status, sha256=excluded.sha256,"
                        " version=CASE WHEN skills.sha256 != excluded.sha256"
                        " THEN skills.version + 1 ELSE skills.version END,"
                        " updated_at=excluded.updated_at",
                        (
                            name,
                            rel,
                            str(meta.get("description", "")).strip(),
                            triggers,
                            status,
                            int(meta.get("version", 1)),
                            sha,
                            time.time(),
                        ),
                    )
                seen.add(name)
                if existing is None:
                    added += 1
                elif existing["sha256"] != sha:
                    updated += 1

        retired = 0
        for row in self.store.query("SELECT name FROM skills WHERE status != ?", (STATUS_RETIRED,)):
            if row["name"] not in seen:
                with self.store.tx() as conn:
                    conn.execute(
                        "UPDATE skills SET status=?, updated_at=? WHERE name=?",
                        (STATUS_RETIRED, time.time(), row["name"]),
                    )
                retired += 1
        return {"added": added, "updated": updated, "retired": retired, "total": len(seen)}

    # ------------------------------------------------------------------ read
    def _row_to_skill(self, row: dict[str, Any], with_body: bool = False) -> Skill:
        path = self.skills_dir.parent / row["path"]
        body = ""
        if with_body and path.exists():
            _meta, body = parse_skill_file(path)
        return Skill(
            name=row["name"],
            path=path,
            description=row["description"],
            triggers=json.loads(row["triggers"] or "[]"),
            status=row["status"],
            version=int(row["version"]),
            uses=int(row["uses"]),
            wins=int(row["wins"]),
            losses=int(row["losses"]),
            body=body,
        )

    def catalog(self, *, status: str = STATUS_ACTIVE) -> list[Skill]:
        """Только заголовки: имя + описание. Это всё, что видит агент сразу."""
        rows = self.store.query(
            "SELECT * FROM skills WHERE status=? ORDER BY name", (status,)
        )
        return [self._row_to_skill(r) for r in rows]

    def load(self, name: str) -> Skill | None:
        """Подтянуть тело навыка — по явному запросу агента."""
        row = self.store.one("SELECT * FROM skills WHERE name=?", (name,))
        if not row:
            return None
        skill = self._row_to_skill(row, with_body=True)
        with self.store.tx() as conn:
            conn.execute(
                "UPDATE skills SET uses=uses+1, updated_at=? WHERE name=?", (time.time(), name)
            )
        return skill

    def match(self, text: str, *, limit: int = 5) -> list[Skill]:
        """Подобрать навыки под задачу: по триггерам, имени и описанию."""
        lowered = text.lower()
        scored: list[tuple[float, Skill]] = []
        for skill in self.catalog():
            score = 0.0
            for trigger in skill.triggers:
                if trigger.lower() in lowered:
                    score += 2.0
            if skill.name.lower() in lowered:
                score += 1.5
            for word in {w for w in re.findall(r"\w+", skill.description.lower()) if len(w) > 4}:
                if word in lowered:
                    score += 0.25
            if score > 0:
                scored.append((score * (0.5 + skill.score), skill))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [skill for _score, skill in scored[:limit]]

    def record_outcome(self, name: str, *, success: bool) -> None:
        """Отметить исход применения — по нему навыки ранжируются и стареют."""
        column = "wins" if success else "losses"
        with self.store.tx() as conn:
            conn.execute(
                f"UPDATE skills SET {column}={column}+1, updated_at=? WHERE name=?",
                (time.time(), name),
            )

    def stats(self) -> dict[str, int]:
        rows = self.store.query("SELECT status, COUNT(*) AS n FROM skills GROUP BY status")
        return {r["status"]: int(r["n"]) for r in rows}
