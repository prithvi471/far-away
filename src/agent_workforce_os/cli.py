from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any

from .app import build_orchestrator, serve
from .core.auth import generate_token
from .core.config import load_config
from .core.evals import run_all_evals
from .core.models import Membership, QueueStatus, Role, User, WorkerKind, new_id
from .core.queue import QueueWorker
from .core.tracing import trace_to_mermaid


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentos", description="Agent Workforce OS operator CLI")
    parser.add_argument("--config", default=None, help="Path to config TOML")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize storage and runtime directories")

    ingest = sub.add_parser("ingest-document", help="Ingest and analyze a document")
    ingest.add_argument("path")
    ingest.add_argument("--llm-summary", action="store_true")

    ingest_source = sub.add_parser("ingest-source", help="Ingest a local or connector document URI")
    ingest_source.add_argument("uri")
    ingest_source.add_argument("--llm-summary", action="store_true")

    bootstrap = sub.add_parser("bootstrap-admin", help="Create an owner token for the default organization/project")
    bootstrap.add_argument("--email", required=True)
    bootstrap.add_argument("--name", required=True)
    bootstrap.add_argument("--token-name", default="local-admin")

    worker = sub.add_parser("add-worker", help="Register an employee or digital agent")
    worker.add_argument("--kind", choices=[kind.value for kind in WorkerKind], default=WorkerKind.EMPLOYEE.value)
    worker.add_argument("--name", required=True)
    worker.add_argument("--title", default="")
    worker.add_argument("--resume", default=None)
    worker.add_argument("--skills", default="")
    worker.add_argument("--years", type=float, default=0.0)
    worker.add_argument("--availability", type=float, default=1.0)

    task = sub.add_parser("create-task", help="Create a real task")
    task.add_argument("--title", required=True)
    task.add_argument("--description", required=True)
    task.add_argument("--skills", default="")
    task.add_argument("--priority", type=int, default=3)
    task.add_argument("--due-at", default=None)
    task.add_argument("--metadata-json", default="{}")

    route = sub.add_parser("route", help="Assign a task to the best employee or digital agent")
    route.add_argument("--task-id", required=True)

    build = sub.add_parser("build", help="Run coding agent and quality gate for a task")
    build.add_argument("--task-id", required=True)
    build.add_argument("--test-command", action="append", default=[])
    build.add_argument("--allow-no-tests", action="store_true")

    enqueue = sub.add_parser("enqueue", help="Create an async queue job")
    enqueue.add_argument("--job-type", required=True)
    enqueue.add_argument("--payload-json", default="{}")

    work_queue = sub.add_parser("work-queue", help="Run queued agent jobs")
    work_queue.add_argument("--limit", type=int, default=10)

    list_queue = sub.add_parser("list-queue", help="List async queue jobs")
    list_queue.add_argument("--status", default=None)

    approve = sub.add_parser("approve", help="Approve a pending human gate")
    approve.add_argument("--approval-id", required=True)
    approve.add_argument("--approved-by", default=None)

    approvals = sub.add_parser("list-approvals", help="List approval gates")
    approvals.add_argument("--task-id", default=None)

    trace = sub.add_parser("trace", help="Render trace events for an aggregate")
    trace.add_argument("--aggregate-id", required=True)
    trace.add_argument("--format", choices=["json", "mermaid"], default="json")

    sub.add_parser("run-evals", help="Run built-in eval datasets")
    sub.add_parser("monitor", help="Run monitoring cycle")
    sub.add_parser("performance", help="Recalculate performance scores")
    sub.add_parser("llm-status", help="Show configured LLM provider status without exposing secrets")
    sub.add_parser("llm-smoke-test", help="Run a live structured-output LLM connectivity check")
    sub.add_parser("list-workers", help="List workers and digital agents")
    sub.add_parser("list-tasks", help="List tasks")
    sub.add_parser("list-documents", help="List documents")

    api = sub.add_parser("serve", help="Start lightweight local HTTP API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8080)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    if args.command == "serve":
        serve(config, args.host, args.port)
        return

    orchestrator = build_orchestrator(config)
    if args.command == "init":
        _print(
            {
                "status": "initialized",
                "database_path": str(config.storage.database_path),
                "workspace_root": str(config.workspace.root_path),
                "artifact_path": str(config.workspace.artifact_path),
            }
        )
    elif args.command == "ingest-document":
        _print(orchestrator.ingest_document(args.path, args.llm_summary))
    elif args.command == "ingest-source":
        _print(orchestrator.ingest_source(args.uri, args.llm_summary))
    elif args.command == "bootstrap-admin":
        token = generate_token()
        user = User(id=new_id("user"), organization_id="org_default", email=args.email, name=args.name)
        orchestrator.context.storage.upsert_user(user)
        orchestrator.context.storage.add_membership(
            Membership(
                id=new_id("member"),
                user_id=user.id,
                organization_id="org_default",
                project_id=None,
                role=Role.OWNER,
            )
        )
        orchestrator.context.storage.issue_api_token(user.id, args.token_name, token)
        _print({"user_id": user.id, "token": token, "note": "Store this token securely. It is shown only once."})
    elif args.command == "add-worker":
        worker = orchestrator.register_worker(
            kind=WorkerKind(args.kind),
            name=args.name,
            title=args.title,
            resume_path=args.resume,
            skills=_csv(args.skills),
            years_experience=args.years,
            availability=args.availability,
        )
        _print(asdict(worker))
    elif args.command == "create-task":
        metadata = json.loads(args.metadata_json)
        task = orchestrator.create_task(
            title=args.title,
            description=args.description,
            required_skills=_csv(args.skills),
            priority=args.priority,
            due_at=args.due_at,
            metadata=metadata,
        )
        _print(asdict(task))
    elif args.command == "route":
        _print(orchestrator.route_task(args.task_id))
    elif args.command == "build":
        _print(orchestrator.run_build_pipeline(args.task_id, args.test_command, args.allow_no_tests))
    elif args.command == "enqueue":
        _print(orchestrator.enqueue_agent_job(args.job_type, json.loads(args.payload_json)))
    elif args.command == "work-queue":
        _print(QueueWorker(orchestrator).run_batch(args.limit))
    elif args.command == "list-queue":
        status_filter = QueueStatus(args.status) if args.status else None
        _print([asdict(job) for job in orchestrator.context.storage.list_jobs(status_filter)])
    elif args.command == "approve":
        _print(orchestrator.approve(args.approval_id, args.approved_by))
    elif args.command == "list-approvals":
        _print([asdict(gate) for gate in orchestrator.context.storage.list_approvals(args.task_id)])
    elif args.command == "trace":
        events = orchestrator.context.storage.list_trace_events(aggregate_id=args.aggregate_id)
        if args.format == "mermaid":
            print(trace_to_mermaid(events))
        else:
            _print([asdict(event) for event in events])
    elif args.command == "run-evals":
        _print(run_all_evals(orchestrator, config.root_dir / "evals"))
    elif args.command == "monitor":
        _print(orchestrator.monitor())
    elif args.command == "performance":
        _print(orchestrator.recalculate_performance())
    elif args.command == "llm-status":
        provider = orchestrator.context.llm
        _print(
            {
                "provider": provider.name,
                "available": provider.available,
                "model": getattr(provider, "model", None),
                "endpoint": getattr(provider, "endpoint", None),
                "api_key_env": config.llm.api_key_env,
                "env_file": str(config.llm.env_file) if config.llm.env_file else None,
            }
        )
    elif args.command == "llm-smoke-test":
        provider = orchestrator.context.llm
        _print(provider.smoke_test())
    elif args.command == "list-workers":
        _print([asdict(worker) for worker in orchestrator.context.storage.list_workers()])
    elif args.command == "list-tasks":
        _print([asdict(task) for task in orchestrator.context.storage.list_tasks()])
    elif args.command == "list-documents":
        _print([asdict(document) for document in orchestrator.context.storage.list_documents()])


if __name__ == "__main__":
    main()
