from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class WorkerKind(str, Enum):
    EMPLOYEE = "employee"
    DIGITAL_AGENT = "digital_agent"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    AGENT_OPERATOR = "agent_operator"
    VIEWER = "viewer"


class QueueStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class Organization:
    id: str
    name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc)


@dataclass
class Project:
    id: str
    organization_id: str
    name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc)


@dataclass
class User:
    id: str
    organization_id: str
    email: str
    name: str
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc)


@dataclass
class ApiToken:
    id: str
    user_id: str
    name: str
    token_hash: str
    created_at: str = field(default_factory=now_utc)
    last_used_at: str | None = None
    revoked_at: str | None = None


@dataclass
class Membership:
    id: str
    user_id: str
    organization_id: str
    project_id: str | None
    role: Role
    created_at: str = field(default_factory=now_utc)


@dataclass
class DocumentRecord:
    id: str
    source_path: str
    content_hash: str
    text: str
    summary: str
    organization_id: str = "org_default"
    project_id: str = "project_default"
    skills: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc)


@dataclass
class WorkerProfile:
    id: str
    kind: WorkerKind
    name: str
    organization_id: str = "org_default"
    project_id: str = "project_default"
    title: str = ""
    resume_document_id: str | None = None
    skills: dict[str, float] = field(default_factory=dict)
    years_experience: float = 0.0
    availability: float = 1.0
    active_tasks: int = 0
    performance_score: float = 0.7
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc)


@dataclass
class Task:
    id: str
    title: str
    description: str
    organization_id: str = "org_default"
    project_id: str = "project_default"
    required_skills: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.QUEUED
    assignee_id: str | None = None
    priority: int = 3
    due_at: str | None = None
    source_document_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc)
    updated_at: str = field(default_factory=now_utc)


@dataclass
class AgentDecision:
    agent_name: str
    action: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRun:
    id: str
    agent_name: str
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]
    status: str
    error: str | None = None
    duration_ms: int = 0
    created_at: str = field(default_factory=now_utc)


@dataclass
class Artifact:
    id: str
    task_id: str | None
    path: str
    artifact_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc)


@dataclass
class QueueJob:
    id: str
    job_type: str
    payload: dict[str, Any]
    status: QueueStatus = QueueStatus.QUEUED
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    attempts: int = 0
    available_at: str = field(default_factory=now_utc)
    created_at: str = field(default_factory=now_utc)
    updated_at: str = field(default_factory=now_utc)


@dataclass
class ApprovalGate:
    id: str
    task_id: str
    gate_type: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_by: str | None = None
    approved_by: str | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc)
    updated_at: str = field(default_factory=now_utc)


@dataclass
class TraceEvent:
    id: str
    trace_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    parent_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc)


@dataclass
class EvalRun:
    id: str
    dataset_name: str
    status: str
    score: float
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc)
