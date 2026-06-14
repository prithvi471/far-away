from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .base_imports import AgentContext, Task, WorkerKind, WorkerProfile, new_id
from .coding import CodingAgent
from .document_intelligence import DocumentIntelligenceAgent
from .monitoring import MonitoringAgent
from .performance import PerformanceAgent
from .quality_gate import QualityGateAgent
from .task_router import TaskRouterAgent


class AgentOrchestrator:
    def __init__(self, context: AgentContext):
        self.context = context
        self.document_intelligence = DocumentIntelligenceAgent(context)
        self.task_router = TaskRouterAgent(context)
        self.monitoring = MonitoringAgent(context)
        self.performance = PerformanceAgent(context)
        self.coding = CodingAgent(context)
        self.quality_gate = QualityGateAgent(context)

    def initialize(self) -> None:
        self.context.storage.initialize()
        self.context.config.workspace.root_path.mkdir(parents=True, exist_ok=True)
        self.context.config.workspace.artifact_path.mkdir(parents=True, exist_ok=True)

    def ingest_document(self, path: str, llm_summary: bool = False) -> dict:
        return asdict(self.document_intelligence.run({"path": path, "llm_summary": llm_summary}))

    def register_worker(
        self,
        kind: WorkerKind,
        name: str,
        title: str = "",
        resume_path: str | None = None,
        skills: list[str] | None = None,
        years_experience: float = 0.0,
        availability: float = 1.0,
    ) -> WorkerProfile:
        resume_document_id = None
        skill_map = {skill.strip().lower(): 3.0 for skill in skills or [] if skill.strip()}
        if resume_path:
            decision = self.document_intelligence.run({"path": resume_path, "llm_summary": False})
            resume_document_id = decision.payload["document_id"]
            for skill in decision.payload.get("skills", []):
                skill_map.setdefault(skill, 3.0)

        worker = WorkerProfile(
            id=new_id("worker"),
            kind=kind,
            name=name,
            title=title,
            resume_document_id=resume_document_id,
            skills=skill_map,
            years_experience=years_experience,
            availability=availability,
        )
        self.context.storage.upsert_worker(worker)
        self.context.storage.record_event("worker", worker.id, "worker_registered", {"name": name, "kind": kind.value})
        return worker

    def create_task(
        self,
        title: str,
        description: str,
        required_skills: list[str] | None = None,
        priority: int = 3,
        due_at: str | None = None,
        source_document_id: str | None = None,
        metadata: dict | None = None,
    ) -> Task:
        task = Task(
            id=new_id("task"),
            title=title,
            description=description,
            required_skills=[skill.strip().lower() for skill in required_skills or [] if skill.strip()],
            priority=priority,
            due_at=due_at,
            source_document_id=source_document_id,
            metadata=metadata or {},
        )
        self.context.storage.create_task(task)
        return task

    def route_task(self, task_id: str) -> dict:
        return asdict(self.task_router.run({"task_id": task_id}))

    def run_build_pipeline(self, task_id: str, test_commands: list[str] | None = None, allow_no_tests: bool = False) -> dict:
        task = self.context.storage.get_task(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if test_commands:
            task.metadata["test_commands"] = test_commands
            self.context.storage.update_task(task)
        build = self.coding.run({"task_id": task_id})
        task = self.context.storage.get_task(task_id)
        if build.action == "coding_completed" and task and task.metadata.get("coding", {}).get("workspace"):
            gate = self.quality_gate.run(
                {
                    "task_id": task_id,
                    "workspace": task.metadata["coding"]["workspace"],
                    "allow_no_tests": allow_no_tests,
                }
            )
        else:
            gate = None
        return {"build": asdict(build), "quality_gate": asdict(gate) if gate else None}

    def monitor(self) -> dict:
        return asdict(self.monitoring.run({}))

    def recalculate_performance(self) -> dict:
        return asdict(self.performance.run({}))

    def task_workspace(self, task_id: str) -> Path:
        return self.context.config.workspace.root_path / task_id
