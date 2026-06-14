from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import (
    AgentRun,
    Artifact,
    DocumentRecord,
    Task,
    TaskStatus,
    WorkerKind,
    WorkerProfile,
    now_utc,
)


def _to_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _from_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class SQLiteStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    @contextmanager
    def connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    skills_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workers (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    resume_document_id TEXT,
                    skills_json TEXT NOT NULL,
                    years_experience REAL NOT NULL,
                    availability REAL NOT NULL,
                    active_tasks INTEGER NOT NULL,
                    performance_score REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    required_skills_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assignee_id TEXT,
                    priority INTEGER NOT NULL,
                    due_at TEXT,
                    source_document_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    duration_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    path TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def save_document(self, record: DocumentRecord) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO documents
                (id, source_path, content_hash, text, summary, skills_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.source_path,
                    record.content_hash,
                    record.text,
                    record.summary,
                    _to_json(record.skills),
                    _to_json(record.metadata),
                    record.created_at,
                ),
            )

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return self._document_from_row(row) if row else None

    def list_documents(self) -> list[DocumentRecord]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        return [self._document_from_row(row) for row in rows]

    def upsert_worker(self, worker: WorkerProfile) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO workers
                (id, kind, name, title, resume_document_id, skills_json, years_experience, availability,
                 active_tasks, performance_score, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    worker.id,
                    worker.kind.value,
                    worker.name,
                    worker.title,
                    worker.resume_document_id,
                    _to_json(worker.skills),
                    worker.years_experience,
                    worker.availability,
                    worker.active_tasks,
                    worker.performance_score,
                    _to_json(worker.metadata),
                    worker.created_at,
                ),
            )

    def get_worker(self, worker_id: str) -> WorkerProfile | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM workers WHERE id = ?", (worker_id,)).fetchone()
        return self._worker_from_row(row) if row else None

    def list_workers(self) -> list[WorkerProfile]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM workers ORDER BY kind, name").fetchall()
        return [self._worker_from_row(row) for row in rows]

    def create_task(self, task: Task) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO tasks
                (id, title, description, required_skills_json, status, assignee_id, priority, due_at,
                 source_document_id, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._task_values(task),
            )
            db.execute(
                """
                INSERT INTO events (aggregate_type, aggregate_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("task", task.id, "task_created", _to_json({"title": task.title}), now_utc()),
            )

    def update_task(self, task: Task) -> None:
        task.updated_at = now_utc()
        with self.connect() as db:
            db.execute(
                """
                UPDATE tasks
                SET title = ?, description = ?, required_skills_json = ?, status = ?, assignee_id = ?,
                    priority = ?, due_at = ?, source_document_id = ?, metadata_json = ?, created_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    task.title,
                    task.description,
                    _to_json(task.required_skills),
                    task.status.value,
                    task.assignee_id,
                    task.priority,
                    task.due_at,
                    task.source_document_id,
                    _to_json(task.metadata),
                    task.created_at,
                    task.updated_at,
                    task.id,
                ),
            )

    def get_task(self, task_id: str) -> Task | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        with self.connect() as db:
            if status:
                rows = db.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY priority DESC, created_at",
                    (status.value,),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM tasks ORDER BY priority DESC, created_at").fetchall()
        return [self._task_from_row(row) for row in rows]

    def active_task_count(self, worker_id: str) -> int:
        active = (
            TaskStatus.ASSIGNED.value,
            TaskStatus.IN_PROGRESS.value,
            TaskStatus.BLOCKED.value,
            TaskStatus.REVIEW.value,
        )
        with self.connect() as db:
            row = db.execute(
                f"SELECT COUNT(*) AS count FROM tasks WHERE assignee_id = ? AND status IN ({','.join('?' for _ in active)})",
                (worker_id, *active),
            ).fetchone()
        return int(row["count"])

    def record_event(self, aggregate_type: str, aggregate_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO events (aggregate_type, aggregate_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (aggregate_type, aggregate_id, event_type, _to_json(payload), now_utc()),
            )

    def record_agent_run(self, run: AgentRun) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO agent_runs
                (id, agent_name, input_json, output_json, status, error, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.agent_name,
                    _to_json(run.input_payload),
                    _to_json(run.output_payload),
                    run.status,
                    run.error,
                    run.duration_ms,
                    run.created_at,
                ),
            )

    def record_artifact(self, artifact: Artifact) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO artifacts (id, task_id, path, artifact_type, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.task_id,
                    artifact.path,
                    artifact.artifact_type,
                    _to_json(artifact.metadata),
                    artifact.created_at,
                ),
            )

    def _task_values(self, task: Task) -> tuple[Any, ...]:
        return (
            task.id,
            task.title,
            task.description,
            _to_json(task.required_skills),
            task.status.value,
            task.assignee_id,
            task.priority,
            task.due_at,
            task.source_document_id,
            _to_json(task.metadata),
            task.created_at,
            task.updated_at,
        )

    def _document_from_row(self, row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            source_path=row["source_path"],
            content_hash=row["content_hash"],
            text=row["text"],
            summary=row["summary"],
            skills=_from_json(row["skills_json"], []),
            metadata=_from_json(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def _worker_from_row(self, row: sqlite3.Row) -> WorkerProfile:
        return WorkerProfile(
            id=row["id"],
            kind=WorkerKind(row["kind"]),
            name=row["name"],
            title=row["title"],
            resume_document_id=row["resume_document_id"],
            skills=_from_json(row["skills_json"], {}),
            years_experience=float(row["years_experience"]),
            availability=float(row["availability"]),
            active_tasks=int(row["active_tasks"]),
            performance_score=float(row["performance_score"]),
            metadata=_from_json(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def _task_from_row(self, row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            required_skills=_from_json(row["required_skills_json"], []),
            status=TaskStatus(row["status"]),
            assignee_id=row["assignee_id"],
            priority=int(row["priority"]),
            due_at=row["due_at"],
            source_document_id=row["source_document_id"],
            metadata=_from_json(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
