from dataclasses import asdict
from typing import Any, Callable

from .agents.orchestrator import AgentOrchestrator
from .core.agent import AgentContext
from .core.auth import Principal, require_permission
from .core.config import RuntimeConfig
from .core.evals import run_all_evals
from .core.llm import build_llm_provider
from .core.models import QueueStatus, Role, WorkerKind
from .core.queue import QueueWorker
from .core.storage import SQLiteStore
from .core.tracing import trace_to_mermaid


def build_orchestrator(config: RuntimeConfig) -> AgentOrchestrator:
    storage = SQLiteStore(config.storage.database_path)
    context = AgentContext(config=config, storage=storage, llm=build_llm_provider(config.llm))
    orchestrator = AgentOrchestrator(context)
    orchestrator.initialize()
    return orchestrator


def create_app(config: RuntimeConfig):
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, status
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("FastAPI server requires deployment dependencies: pip install .[api]") from exc

    orchestrator = build_orchestrator(config)
    app = FastAPI(title="Agent Workforce OS", version="0.1.0")

    class WorkerCreate(BaseModel):
        kind: str = WorkerKind.EMPLOYEE.value
        name: str
        title: str = ""
        resume_path: str | None = None
        skills: list[str] = Field(default_factory=list)
        years_experience: float = 0
        availability: float = 1
        organization_id: str = "org_default"
        project_id: str = "project_default"

    class TaskCreate(BaseModel):
        title: str
        description: str = ""
        required_skills: list[str] = Field(default_factory=list)
        priority: int = 3
        due_at: str | None = None
        organization_id: str = "org_default"
        project_id: str = "project_default"
        metadata: dict[str, Any] = Field(default_factory=dict)

    class DocumentIngest(BaseModel):
        path: str | None = None
        uri: str | None = None
        llm_summary: bool = False
        organization_id: str = "org_default"
        project_id: str = "project_default"

    class RouteRequest(BaseModel):
        task_id: str

    class BuildRequest(BaseModel):
        task_id: str
        test_commands: list[str] | None = None
        allow_no_tests: bool = False

    class QueueRequest(BaseModel):
        job_type: str
        payload: dict[str, Any] = Field(default_factory=dict)

    class OrgCreate(BaseModel):
        name: str
        metadata: dict[str, Any] = Field(default_factory=dict)

    class ProjectCreate(BaseModel):
        organization_id: str
        name: str
        metadata: dict[str, Any] = Field(default_factory=dict)

    class UserCreate(BaseModel):
        organization_id: str
        email: str
        name: str
        role: str = Role.VIEWER.value
        project_id: str | None = None

    def current_principal(authorization: str | None = Header(default=None)) -> Principal:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        principal = orchestrator.context.storage.get_principal_by_token(token)
        if principal is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
        return principal

    def permission(permission_name: str) -> Callable[[Principal], Principal]:
        def dependency(principal: Principal = Depends(current_principal)) -> Principal:
            try:
                require_permission(principal, permission_name)
            except PermissionError as exc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
            return principal

        return dependency

    def authorize(principal: Principal, permission_name: str, project_id: str | None = None) -> None:
        try:
            require_permission(principal, permission_name, project_id)
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    def project_for_task(task_id: str) -> str | None:
        task = orchestrator.context.storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task.project_id

    def project_for_payload(payload: dict[str, Any]) -> str | None:
        if payload.get("project_id"):
            return str(payload["project_id"])
        if payload.get("task_id"):
            return project_for_task(str(payload["task_id"]))
        return None

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/organizations")
    def list_organizations(_: Principal = Depends(permission("org:read"))):
        return [asdict(item) for item in orchestrator.context.storage.list_organizations()]

    @app.post("/organizations", status_code=201)
    def create_organization(payload: OrgCreate, _: Principal = Depends(permission("org:write"))):
        return asdict(orchestrator.create_organization(payload.name, payload.metadata))

    @app.get("/projects")
    def list_projects(organization_id: str | None = None, _: Principal = Depends(permission("project:read"))):
        return [asdict(item) for item in orchestrator.context.storage.list_projects(organization_id)]

    @app.post("/projects", status_code=201)
    def create_project(payload: ProjectCreate, _: Principal = Depends(permission("project:write"))):
        return asdict(orchestrator.create_project(payload.organization_id, payload.name, payload.metadata))

    @app.post("/users", status_code=201)
    def create_user(payload: UserCreate, _: Principal = Depends(permission("users:write"))):
        return asdict(
            orchestrator.create_user(
                payload.organization_id,
                payload.email,
                payload.name,
                Role(payload.role),
                payload.project_id,
            )
        )

    @app.get("/workers")
    def list_workers(project_id: str | None = None, principal: Principal = Depends(current_principal)):
        authorize(principal, "workers:read", project_id)
        return [asdict(worker) for worker in orchestrator.context.storage.list_workers(project_id)]

    @app.post("/workers", status_code=201)
    def create_worker(payload: WorkerCreate, principal: Principal = Depends(current_principal)):
        authorize(principal, "workers:write", payload.project_id)
        worker = orchestrator.register_worker(
            kind=WorkerKind(payload.kind),
            name=payload.name,
            title=payload.title,
            resume_path=payload.resume_path,
            skills=payload.skills,
            years_experience=payload.years_experience,
            availability=payload.availability,
            organization_id=payload.organization_id,
            project_id=payload.project_id,
        )
        return asdict(worker)

    @app.get("/tasks")
    def list_tasks(project_id: str | None = None, principal: Principal = Depends(current_principal)):
        authorize(principal, "tasks:read", project_id)
        return [asdict(task) for task in orchestrator.context.storage.list_tasks(project_id=project_id)]

    @app.post("/tasks", status_code=201)
    def create_task(payload: TaskCreate, principal: Principal = Depends(current_principal)):
        authorize(principal, "tasks:write", payload.project_id)
        return asdict(
            orchestrator.create_task(
                title=payload.title,
                description=payload.description,
                required_skills=payload.required_skills,
                priority=payload.priority,
                due_at=payload.due_at,
                metadata=payload.metadata,
                organization_id=payload.organization_id,
                project_id=payload.project_id,
            )
        )

    @app.get("/documents")
    def list_documents(project_id: str | None = None, principal: Principal = Depends(current_principal)):
        authorize(principal, "documents:read", project_id)
        return [asdict(document) for document in orchestrator.context.storage.list_documents(project_id)]

    @app.post("/ingest-document")
    def ingest_document(payload: DocumentIngest, principal: Principal = Depends(current_principal)):
        authorize(principal, "documents:write", payload.project_id)
        if payload.uri:
            return orchestrator.ingest_source(payload.uri, payload.llm_summary, payload.organization_id, payload.project_id)
        if payload.path:
            return orchestrator.ingest_document(payload.path, payload.llm_summary, payload.organization_id, payload.project_id)
        raise HTTPException(status_code=400, detail="Either path or uri is required")

    @app.post("/route")
    def route_task(payload: RouteRequest, principal: Principal = Depends(current_principal)):
        authorize(principal, "agents:run", project_for_task(payload.task_id))
        return orchestrator.route_task(payload.task_id)

    @app.post("/build")
    def build_task(payload: BuildRequest, principal: Principal = Depends(current_principal)):
        authorize(principal, "agents:run", project_for_task(payload.task_id))
        return orchestrator.run_build_pipeline(payload.task_id, payload.test_commands, payload.allow_no_tests)

    @app.post("/queue", status_code=202)
    def enqueue(payload: QueueRequest, principal: Principal = Depends(current_principal)):
        authorize(principal, "queue:write", project_for_payload(payload.payload))
        return orchestrator.enqueue_agent_job(payload.job_type, payload.payload)

    @app.get("/queue")
    def list_queue(status_value: str | None = None, _: Principal = Depends(permission("queue:read"))):
        status_filter = QueueStatus(status_value) if status_value else None
        return [asdict(job) for job in orchestrator.context.storage.list_jobs(status_filter)]

    @app.post("/queue/work")
    def work_queue(limit: int = 10, _: Principal = Depends(permission("queue:write"))):
        return QueueWorker(orchestrator).run_batch(limit)

    @app.get("/approvals")
    def list_approvals(task_id: str | None = None, _: Principal = Depends(permission("approvals:read"))):
        return [asdict(item) for item in orchestrator.context.storage.list_approvals(task_id)]

    @app.post("/approvals/{approval_id}/approve")
    def approve(approval_id: str, principal: Principal = Depends(permission("approvals:write"))):
        return orchestrator.approve(approval_id, principal.user.id)

    @app.get("/traces/{aggregate_id}")
    def trace(aggregate_id: str, _: Principal = Depends(permission("traces:read"))):
        events = orchestrator.context.storage.list_trace_events(aggregate_id=aggregate_id)
        return {"events": [asdict(event) for event in events], "mermaid": trace_to_mermaid(events)}

    @app.post("/monitor")
    def monitor(_: Principal = Depends(permission("agents:run"))):
        return orchestrator.monitor()

    @app.post("/performance")
    def performance(_: Principal = Depends(permission("agents:run"))):
        return orchestrator.recalculate_performance()

    @app.post("/evals/run")
    def run_evals(_: Principal = Depends(permission("evals:run"))):
        return run_all_evals(orchestrator, config.root_dir / "evals")

    return app


def serve(config: RuntimeConfig, host: str, port: int) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("FastAPI server requires deployment dependencies: pip install .[api]") from exc

    app = create_app(config)
    uvicorn.run(app, host=host, port=port)
