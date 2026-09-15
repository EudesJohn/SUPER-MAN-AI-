"""Project memory (section 17): SQLite at first, PostgreSQL later.

The schema is deliberately minimal and versioned through the events table.
Artifacts (big files) never go into the DB - only their metadata.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from core.models import (
    Artifact,
    Assumption,
    CalculationRecord,
    EventKind,
    Requirement,
    Task,
    VerificationResult,
    new_id,
    utc_now_iso,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calculations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verifications (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assumptions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS components (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    parent_id TEXT,
    summary TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL
);
"""


class ProjectMemory:
    """SQLite-backed memory for one AI ENGINEER installation."""

    def __init__(self, db_path: str = "ai_engineer.db") -> None:
        self.db_path = db_path
        # check_same_thread=False: the API server handles requests on worker
        # threads; sqlite3's internal locking keeps access serialized.
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------ #
    # Projects
    # ------------------------------------------------------------------ #
    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        pid = new_id("PRJ")
        self.conn.execute(
            "INSERT INTO projects (id, name, description, created_at) VALUES (?,?,?,?)",
            (pid, name, description, utc_now_iso()),
        )
        self.conn.commit()
        return {"id": pid, "name": name, "description": description}

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def list_projects(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM projects ORDER BY created_at")]

    # ------------------------------------------------------------------ #
    # Generic typed stores
    # ------------------------------------------------------------------ #
    def _insert(self, table: str, project_id: str, obj_id: str, data: dict[str, Any]) -> None:
        self.conn.execute(
            f"INSERT OR REPLACE INTO {table} (id, project_id, data, created_at) VALUES (?,?,?,?)",
            (obj_id, project_id, json.dumps(data, ensure_ascii=False), utc_now_iso()),
        )
        self.conn.commit()

    def _list(self, table: str, project_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            f"SELECT data FROM {table} WHERE project_id=? ORDER BY created_at, id", (project_id,)
        ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    # ------------------------------------------------------------------ #
    # Typed helpers
    # ------------------------------------------------------------------ #
    def add_requirement(self, project_id: str, req: Requirement) -> None:
        self._insert("requirements", project_id, req.id, req.model_dump())

    def list_requirements(self, project_id: str) -> list[dict[str, Any]]:
        return self._list("requirements", project_id)

    def save_task(self, project_id: str, task: Task) -> None:
        self._insert("tasks", project_id, task.id, task.model_dump())

    def list_tasks(self, project_id: str) -> list[dict[str, Any]]:
        return self._list("tasks", project_id)

    def add_calculation(self, project_id: str, rec: CalculationRecord) -> None:
        self._insert("calculations", project_id, rec.id, rec.model_dump())

    def list_calculations(self, project_id: str) -> list[dict[str, Any]]:
        return self._list("calculations", project_id)

    def add_verification(self, project_id: str, res: VerificationResult) -> None:
        self._insert("verifications", project_id, res.id, res.model_dump())

    def list_verifications(self, project_id: str) -> list[dict[str, Any]]:
        return self._list("verifications", project_id)

    def add_assumption(self, project_id: str, asm: Assumption) -> None:
        self._insert("assumptions", project_id, asm.id, asm.model_dump())

    def list_assumptions(self, project_id: str) -> list[dict[str, Any]]:
        return self._list("assumptions", project_id)

    def add_source(self, project_id: str, source: dict[str, Any]) -> str:
        sid = new_id("SRC")
        self._insert("sources", project_id, sid, source)
        return sid

    def list_sources(self, project_id: str) -> list[dict[str, Any]]:
        return self._list("sources", project_id)

    def add_artifact(self, project_id: str, art: Artifact) -> None:
        self._insert("artifacts", project_id, art.id, art.model_dump())

    def add_component(self, project_id: str, component: dict[str, Any]) -> None:
        """Sourced component record (status SOURCED / INSUFFICIENT_SOURCES / INCONNU)."""
        cid = component.get("id") or new_id("COMP")
        self._insert("components", project_id, cid, component)

    def list_components(self, project_id: str) -> list[dict[str, Any]]:
        return self._list("components", project_id)

    def list_artifacts(self, project_id: str) -> list[dict[str, Any]]:
        return self._list("artifacts", project_id)

    # ------------------------------------------------------------------ #
    # Events (event sourcing) + versions
    # ------------------------------------------------------------------ #
    def append_event(self, project_id: str | None, event: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO events (project_id, kind, payload, timestamp) VALUES (?,?,?,?)",
            (
                project_id,
                event.get("kind", "INFO"),
                json.dumps(event.get("payload", {}), ensure_ascii=False),
                event.get("timestamp", utc_now_iso()),
            ),
        )
        self.conn.commit()

    def list_events(self, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if project_id:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE project_id=? ORDER BY seq DESC LIMIT ?",
                (project_id, limit),
            )
        else:
            rows = self.conn.execute("SELECT * FROM events ORDER BY seq DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def create_version(self, project_id: str, summary: str, created_by: str = "system") -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT MAX(number) AS m FROM versions WHERE project_id=?", (project_id,)
        ).fetchone()
        number = (row["m"] or 0) + 1
        vid = new_id("VER")
        self.conn.execute(
            "INSERT INTO versions (id, project_id, number, parent_id, summary, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (vid, project_id, number, None, summary, created_by, utc_now_iso()),
        )
        self.conn.commit()
        return {"id": vid, "project_id": project_id, "number": number, "summary": summary}

    def list_versions(self, project_id: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM versions WHERE project_id=? ORDER BY number", (project_id,)
            )
        ]

    def close(self) -> None:
        self.conn.close()
