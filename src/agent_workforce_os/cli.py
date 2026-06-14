from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any

from .app import build_orchestrator, serve
from .core.config import load_config
from .core.models import WorkerKind


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

    sub.add_parser("monitor", help="Run monitoring cycle")
    sub.add_parser("performance", help="Recalculate performance scores")
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
    elif args.command == "monitor":
        _print(orchestrator.monitor())
    elif args.command == "performance":
        _print(orchestrator.recalculate_performance())
    elif args.command == "list-workers":
        _print([asdict(worker) for worker in orchestrator.context.storage.list_workers()])
    elif args.command == "list-tasks":
        _print([asdict(task) for task in orchestrator.context.storage.list_tasks()])
    elif args.command == "list-documents":
        _print([asdict(document) for document in orchestrator.context.storage.list_documents()])


if __name__ == "__main__":
    main()

