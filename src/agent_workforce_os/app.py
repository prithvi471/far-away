from __future__ import annotations

import json
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .agents.orchestrator import AgentOrchestrator
from .core.agent import AgentContext
from .core.config import RuntimeConfig
from .core.llm import build_llm_provider
from .core.models import WorkerKind
from .core.storage import SQLiteStore


def build_orchestrator(config: RuntimeConfig) -> AgentOrchestrator:
    storage = SQLiteStore(config.storage.database_path)
    context = AgentContext(config=config, storage=storage, llm=build_llm_provider(config.llm))
    orchestrator = AgentOrchestrator(context)
    orchestrator.initialize()
    return orchestrator


class AgentOSHandler(BaseHTTPRequestHandler):
    orchestrator: AgentOrchestrator

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send({"status": "ok"})
        elif path == "/workers":
            self._send([asdict(worker) for worker in self.orchestrator.context.storage.list_workers()])
        elif path == "/tasks":
            self._send([asdict(task) for task in self.orchestrator.context.storage.list_tasks()])
        elif path == "/documents":
            self._send([asdict(document) for document in self.orchestrator.context.storage.list_documents()])
        else:
            self._send({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload = self._read_json()
        try:
            if path == "/workers":
                worker = self.orchestrator.register_worker(
                    kind=WorkerKind(payload.get("kind", "employee")),
                    name=payload["name"],
                    title=payload.get("title", ""),
                    resume_path=payload.get("resume_path"),
                    skills=payload.get("skills", []),
                    years_experience=float(payload.get("years_experience", 0)),
                    availability=float(payload.get("availability", 1)),
                )
                self._send(asdict(worker), HTTPStatus.CREATED)
            elif path == "/tasks":
                task = self.orchestrator.create_task(
                    title=payload["title"],
                    description=payload.get("description", ""),
                    required_skills=payload.get("required_skills", []),
                    priority=int(payload.get("priority", 3)),
                    due_at=payload.get("due_at"),
                    metadata=payload.get("metadata", {}),
                )
                self._send(asdict(task), HTTPStatus.CREATED)
            elif path == "/route":
                self._send(self.orchestrator.route_task(payload["task_id"]))
            elif path == "/monitor":
                self._send(self.orchestrator.monitor())
            elif path == "/performance":
                self._send(self.orchestrator.recalculate_performance())
            elif path == "/ingest-document":
                self._send(self.orchestrator.ingest_document(payload["path"], bool(payload.get("llm_summary", False))))
            elif path == "/build":
                self._send(
                    self.orchestrator.run_build_pipeline(
                        payload["task_id"],
                        test_commands=payload.get("test_commands"),
                        allow_no_tests=bool(payload.get("allow_no_tests", False)),
                    )
                )
            else:
                self._send({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=str, indent=2).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(config: RuntimeConfig, host: str, port: int) -> None:
    orchestrator = build_orchestrator(config)
    AgentOSHandler.orchestrator = orchestrator
    server = ThreadingHTTPServer((host, port), AgentOSHandler)
    print(f"Agent Workforce OS API listening on http://{host}:{port}")
    server.serve_forever()

