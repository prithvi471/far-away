from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import (
    AgentRun,
    ApiToken,
    ApprovalGate,
    ApprovalStatus,
    Artifact,
    DocumentRecord,
    EvalRun,
    Membership,
    Organization,
    Project,
    QueueJob,
    QueueStatus,
    Role,
    Task,
    TaskStatus,
    TraceEvent,
    User,
    WorkerKind,
    WorkerProfile,
    new_id,
    now_utc,
)
from .auth import Principal, hash_token


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
                    organization_id TEXT NOT NULL DEFAULT 'org_default',
                    project_id TEXT NOT NULL DEFAULT 'project_default',
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
                    organization_id TEXT NOT NULL DEFAULT 'org_default',
                    project_id TEXT NOT NULL DEFAULT 'project_default',
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
                    organization_id TEXT NOT NULL DEFAULT 'org_default',
                    project_id TEXT NOT NULL DEFAULT 'project_default',
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

                CREATE TABLE IF NOT EXISTS organizations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    is_active INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS memberships (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    project_id TEXT,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS queue_jobs (
                    id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    error TEXT,
                    attempts INTEGER NOT NULL,
                    available_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    gate_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_by TEXT,
                    approved_by TEXT,
                    reason TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trace_events (
                    id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    parent_id TEXT,
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eval_runs (
                    id TEXT PRIMARY KEY,
                    dataset_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score REAL NOT NULL,
                    metrics_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(db, "documents", "organization_id", "TEXT NOT NULL DEFAULT 'org_default'")
            self._ensure_column(db, "documents", "project_id", "TEXT NOT NULL DEFAULT 'project_default'")
            self._ensure_column(db, "workers", "organization_id", "TEXT NOT NULL DEFAULT 'org_default'")
            self._ensure_column(db, "workers", "project_id", "TEXT NOT NULL DEFAULT 'project_default'")
            self._ensure_column(db, "tasks", "organization_id", "TEXT NOT NULL DEFAULT 'org_default'")
            self._ensure_column(db, "tasks", "project_id", "TEXT NOT NULL DEFAULT 'project_default'")
            self._ensure_default_scope_db(db)

    def _ensure_column(self, db: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def ensure_default_scope(self) -> None:
        with self.connect() as db:
            self._ensure_default_scope_db(db)

    def _ensure_default_scope_db(self, db: sqlite3.Connection) -> None:
        db.execute(
            """
            INSERT OR IGNORE INTO organizations (id, name, metadata_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            ("org_default", "Default Organization", _to_json({}), now_utc()),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO projects (id, organization_id, name, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("project_default", "org_default", "Default Project", _to_json({}), now_utc()),
        )

    def save_document(self, record: DocumentRecord) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO documents
                (id, organization_id, project_id, source_path, content_hash, text, summary, skills_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.organization_id,
                    record.project_id,
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

    def list_documents(self, project_id: str | None = None) -> list[DocumentRecord]:
        with self.connect() as db:
            if project_id:
                rows = db.execute(
                    "SELECT * FROM documents WHERE project_id = ? ORDER BY created_at DESC",
                    (project_id,),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        return [self._document_from_row(row) for row in rows]

    def upsert_worker(self, worker: WorkerProfile) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO workers
                (id, organization_id, project_id, kind, name, title, resume_document_id, skills_json, years_experience, availability,
                 active_tasks, performance_score, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    worker.id,
                    worker.organization_id,
                    worker.project_id,
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

    def list_workers(self, project_id: str | None = None) -> list[WorkerProfile]:
        with self.connect() as db:
            if project_id:
                rows = db.execute(
                    "SELECT * FROM workers WHERE project_id = ? ORDER BY kind, name",
                    (project_id,),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM workers ORDER BY kind, name").fetchall()
        return [self._worker_from_row(row) for row in rows]

    def create_task(self, task: Task) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO tasks
                (id, organization_id, project_id, title, description, required_skills_json, status, assignee_id, priority, due_at,
                 source_document_id, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                SET organization_id = ?, project_id = ?, title = ?, description = ?, required_skills_json = ?, status = ?, assignee_id = ?,
                    priority = ?, due_at = ?, source_document_id = ?, metadata_json = ?, created_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    task.organization_id,
                    task.project_id,
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

    def list_tasks(self, status: TaskStatus | None = None, project_id: str | None = None) -> list[Task]:
        with self.connect() as db:
            if status and project_id:
                rows = db.execute(
                    "SELECT * FROM tasks WHERE status = ? AND project_id = ? ORDER BY priority DESC, created_at",
                    (status.value, project_id),
                ).fetchall()
            elif status:
                rows = db.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY priority DESC, created_at",
                    (status.value,),
                ).fetchall()
            elif project_id:
                rows = db.execute(
                    "SELECT * FROM tasks WHERE project_id = ? ORDER BY priority DESC, created_at",
                    (project_id,),
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

    def upsert_organization(self, organization: Organization) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO organizations (id, name, metadata_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (organization.id, organization.name, _to_json(organization.metadata), organization.created_at),
            )

    def list_organizations(self) -> list[Organization]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM organizations ORDER BY name").fetchall()
        return [self._organization_from_row(row) for row in rows]

    def upsert_project(self, project: Project) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO projects (id, organization_id, name, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project.id, project.organization_id, project.name, _to_json(project.metadata), project.created_at),
            )

    def get_project(self, project_id: str) -> Project | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._project_from_row(row) if row else None

    def list_projects(self, organization_id: str | None = None) -> list[Project]:
        with self.connect() as db:
            if organization_id:
                rows = db.execute(
                    "SELECT * FROM projects WHERE organization_id = ? ORDER BY name",
                    (organization_id,),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [self._project_from_row(row) for row in rows]

    def upsert_user(self, user: User) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO users
                (id, organization_id, email, name, is_active, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.organization_id,
                    user.email,
                    user.name,
                    1 if user.is_active else 0,
                    _to_json(user.metadata),
                    user.created_at,
                ),
            )

    def get_user_by_email(self, email: str) -> User | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return self._user_from_row(row) if row else None

    def add_membership(self, membership: Membership) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO memberships (id, user_id, organization_id, project_id, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    membership.id,
                    membership.user_id,
                    membership.organization_id,
                    membership.project_id,
                    membership.role.value,
                    membership.created_at,
                ),
            )

    def list_memberships(self, user_id: str) -> list[Membership]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM memberships WHERE user_id = ?", (user_id,)).fetchall()
        return [self._membership_from_row(row) for row in rows]

    def issue_api_token(self, user_id: str, name: str, raw_token: str) -> ApiToken:
        token = ApiToken(id=new_id("token"), user_id=user_id, name=name, token_hash=hash_token(raw_token))
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO api_tokens (id, user_id, name, token_hash, created_at, last_used_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token.id,
                    token.user_id,
                    token.name,
                    token.token_hash,
                    token.created_at,
                    token.last_used_at,
                    token.revoked_at,
                ),
            )
        return token

    def get_principal_by_token(self, raw_token: str) -> Principal | None:
        token_hash = hash_token(raw_token)
        with self.connect() as db:
            row = db.execute(
                """
                SELECT users.* FROM api_tokens
                JOIN users ON users.id = api_tokens.user_id
                WHERE api_tokens.token_hash = ? AND api_tokens.revoked_at IS NULL AND users.is_active = 1
                """,
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            user = self._user_from_row(row)
            db.execute("UPDATE api_tokens SET last_used_at = ? WHERE token_hash = ?", (now_utc(), token_hash))
            membership_rows = db.execute("SELECT * FROM memberships WHERE user_id = ?", (user.id,)).fetchall()
        return Principal(user=user, memberships=[self._membership_from_row(item) for item in membership_rows])

    def enqueue_job(self, job_type: str, payload: dict[str, Any]) -> QueueJob:
        job = QueueJob(id=new_id("job"), job_type=job_type, payload=payload)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO queue_jobs
                (id, job_type, status, payload_json, result_json, error, attempts, available_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.job_type,
                    job.status.value,
                    _to_json(job.payload),
                    _to_json(job.result),
                    job.error,
                    job.attempts,
                    job.available_at,
                    job.created_at,
                    job.updated_at,
                ),
            )
        return job

    def claim_next_job(self) -> QueueJob | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT * FROM queue_jobs
                WHERE status = ? AND available_at <= ?
                ORDER BY created_at
                LIMIT 1
                """,
                (QueueStatus.QUEUED.value, now_utc()),
            ).fetchone()
            if not row:
                return None
            job = self._queue_job_from_row(row)
            job.status = QueueStatus.RUNNING
            job.attempts += 1
            job.updated_at = now_utc()
            db.execute(
                "UPDATE queue_jobs SET status = ?, attempts = ?, updated_at = ? WHERE id = ?",
                (job.status.value, job.attempts, job.updated_at, job.id),
            )
        return job

    def complete_job(self, job_id: str, result: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE queue_jobs SET status = ?, result_json = ?, error = NULL, updated_at = ? WHERE id = ?",
                (QueueStatus.DONE.value, _to_json(result), now_utc(), job_id),
            )

    def fail_job(self, job_id: str, error: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE queue_jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (QueueStatus.FAILED.value, error, now_utc(), job_id),
            )

    def list_jobs(self, status: QueueStatus | None = None) -> list[QueueJob]:
        with self.connect() as db:
            if status:
                rows = db.execute("SELECT * FROM queue_jobs WHERE status = ? ORDER BY created_at", (status.value,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM queue_jobs ORDER BY created_at").fetchall()
        return [self._queue_job_from_row(row) for row in rows]

    def request_approval(self, task_id: str, gate_type: str, reason: str, requested_by: str | None = None) -> ApprovalGate:
        existing = self.get_approval(task_id, gate_type)
        if existing and existing.status == ApprovalStatus.PENDING:
            return existing
        gate = ApprovalGate(id=new_id("approval"), task_id=task_id, gate_type=gate_type, reason=reason, requested_by=requested_by)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO approvals
                (id, task_id, gate_type, status, requested_by, approved_by, reason, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gate.id,
                    gate.task_id,
                    gate.gate_type,
                    gate.status.value,
                    gate.requested_by,
                    gate.approved_by,
                    gate.reason,
                    _to_json(gate.metadata),
                    gate.created_at,
                    gate.updated_at,
                ),
            )
        return gate

    def approve_gate(self, approval_id: str, approved_by: str | None = None) -> ApprovalGate | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
            if not row:
                return None
            updated_at = now_utc()
            db.execute(
                "UPDATE approvals SET status = ?, approved_by = ?, updated_at = ? WHERE id = ?",
                (ApprovalStatus.APPROVED.value, approved_by, updated_at, approval_id),
            )
            row = db.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return self._approval_from_row(row)

    def get_approval(self, task_id: str, gate_type: str) -> ApprovalGate | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM approvals WHERE task_id = ? AND gate_type = ? ORDER BY created_at DESC LIMIT 1",
                (task_id, gate_type),
            ).fetchone()
        return self._approval_from_row(row) if row else None

    def has_approved_gate(self, task_id: str, gate_type: str) -> bool:
        gate = self.get_approval(task_id, gate_type)
        return bool(gate and gate.status == ApprovalStatus.APPROVED)

    def list_approvals(self, task_id: str | None = None) -> list[ApprovalGate]:
        with self.connect() as db:
            if task_id:
                rows = db.execute("SELECT * FROM approvals WHERE task_id = ? ORDER BY created_at DESC", (task_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
        return [self._approval_from_row(row) for row in rows]

    def record_trace_event(self, event: TraceEvent) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO trace_events
                (id, trace_id, parent_id, aggregate_type, aggregate_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.trace_id,
                    event.parent_id,
                    event.aggregate_type,
                    event.aggregate_id,
                    event.event_type,
                    _to_json(event.payload),
                    event.created_at,
                ),
            )

    def list_trace_events(self, aggregate_id: str | None = None, trace_id: str | None = None) -> list[TraceEvent]:
        with self.connect() as db:
            if trace_id:
                rows = db.execute("SELECT * FROM trace_events WHERE trace_id = ? ORDER BY created_at", (trace_id,)).fetchall()
            elif aggregate_id:
                rows = db.execute("SELECT * FROM trace_events WHERE aggregate_id = ? ORDER BY created_at", (aggregate_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM trace_events ORDER BY created_at").fetchall()
        return [self._trace_event_from_row(row) for row in rows]

    def record_eval_run(self, run: EvalRun) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO eval_runs (id, dataset_name, status, score, metrics_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run.id, run.dataset_name, run.status, run.score, _to_json(run.metrics), run.created_at),
            )

    def _task_values(self, task: Task) -> tuple[Any, ...]:
        return (
            task.id,
            task.organization_id,
            task.project_id,
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

    def _organization_from_row(self, row: sqlite3.Row) -> Organization:
        return Organization(
            id=row["id"],
            name=row["name"],
            metadata=_from_json(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def _project_from_row(self, row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            organization_id=row["organization_id"],
            name=row["name"],
            metadata=_from_json(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def _user_from_row(self, row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            organization_id=row["organization_id"],
            email=row["email"],
            name=row["name"],
            is_active=bool(row["is_active"]),
            metadata=_from_json(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def _membership_from_row(self, row: sqlite3.Row) -> Membership:
        return Membership(
            id=row["id"],
            user_id=row["user_id"],
            organization_id=row["organization_id"],
            project_id=row["project_id"],
            role=Role(row["role"]),
            created_at=row["created_at"],
        )

    def _queue_job_from_row(self, row: sqlite3.Row) -> QueueJob:
        return QueueJob(
            id=row["id"],
            job_type=row["job_type"],
            status=QueueStatus(row["status"]),
            payload=_from_json(row["payload_json"], {}),
            result=_from_json(row["result_json"], {}),
            error=row["error"],
            attempts=int(row["attempts"]),
            available_at=row["available_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _approval_from_row(self, row: sqlite3.Row) -> ApprovalGate:
        return ApprovalGate(
            id=row["id"],
            task_id=row["task_id"],
            gate_type=row["gate_type"],
            status=ApprovalStatus(row["status"]),
            requested_by=row["requested_by"],
            approved_by=row["approved_by"],
            reason=row["reason"],
            metadata=_from_json(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _trace_event_from_row(self, row: sqlite3.Row) -> TraceEvent:
        return TraceEvent(
            id=row["id"],
            trace_id=row["trace_id"],
            parent_id=row["parent_id"],
            aggregate_type=row["aggregate_type"],
            aggregate_id=row["aggregate_id"],
            event_type=row["event_type"],
            payload=_from_json(row["payload_json"], {}),
            created_at=row["created_at"],
        )

    def _document_from_row(self, row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            organization_id=row["organization_id"],
            project_id=row["project_id"],
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
            organization_id=row["organization_id"],
            project_id=row["project_id"],
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
            organization_id=row["organization_id"],
            project_id=row["project_id"],
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
