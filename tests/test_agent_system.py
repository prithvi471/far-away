from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workforce_os.agents.orchestrator import AgentOrchestrator
from agent_workforce_os.core.agent import AgentContext
from agent_workforce_os.core.config import LLMConfig, MonitoringConfig, RoutingConfig, RuntimeConfig, StorageConfig, WorkspaceConfig, load_env_file
from agent_workforce_os.core.llm import extract_responses_text, parse_json_text
from agent_workforce_os.core.llm import NoopLLMProvider
from agent_workforce_os.core.models import TaskStatus, WorkerKind
from agent_workforce_os.core.storage import SQLiteStore


class AgentSystemTest(unittest.TestCase):
    def make_orchestrator(self, root: Path) -> AgentOrchestrator:
        config = RuntimeConfig(
            root_dir=root,
            storage=StorageConfig(database_path=root / "agentos.db"),
            workspace=WorkspaceConfig(root_path=root / "workspaces", artifact_path=root / "artifacts"),
            llm=LLMConfig(),
            routing=RoutingConfig(min_confidence=0.25),
            monitoring=MonitoringConfig(stale_hours=24),
            skills_catalog=["python", "api", "testing", "sql", "coding", "monitoring"],
        )
        storage = SQLiteStore(config.storage.database_path)
        orchestrator = AgentOrchestrator(AgentContext(config=config, storage=storage, llm=NoopLLMProvider()))
        orchestrator.initialize()
        return orchestrator

    def test_document_ingestion_extracts_skills_and_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            doc = root / "brief.md"
            doc.write_text(
                "Python API work\n\nTask: Build ingestion endpoint\nTODO: Add testing coverage\n",
                encoding="utf-8",
            )
            orchestrator = self.make_orchestrator(root)
            decision = orchestrator.ingest_document(str(doc))
            self.assertEqual(decision["action"], "document_ingested")
            self.assertIn("python", decision["payload"]["skills"])
            self.assertEqual(len(decision["payload"]["candidate_tasks"]), 2)

    def test_router_assigns_best_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            orchestrator = self.make_orchestrator(Path(temp))
            weak = orchestrator.register_worker(
                WorkerKind.EMPLOYEE,
                name="Generalist",
                skills=["sql"],
                years_experience=1,
            )
            strong = orchestrator.register_worker(
                WorkerKind.DIGITAL_AGENT,
                name="Python Builder",
                skills=["python", "api", "testing", "coding"],
                years_experience=5,
            )
            task = orchestrator.create_task(
                title="Create API",
                description="Build and test an API.",
                required_skills=["python", "api", "testing"],
            )
            decision = orchestrator.route_task(task.id)
            updated = orchestrator.context.storage.get_task(task.id)
            self.assertEqual(decision["action"], "task_assigned")
            self.assertEqual(updated.assignee_id, strong.id)
            self.assertNotEqual(updated.assignee_id, weak.id)

    def test_coding_agent_blocks_without_llm_instead_of_faking_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            orchestrator = self.make_orchestrator(Path(temp))
            task = orchestrator.create_task(
                title="Build feature",
                description="Create a working module.",
                required_skills=["python", "testing"],
            )
            result = orchestrator.run_build_pipeline(task.id, allow_no_tests=True)
            updated = orchestrator.context.storage.get_task(task.id)
            self.assertEqual(result["build"]["action"], "coding_blocked_needs_llm")
            self.assertEqual(updated.status, TaskStatus.BLOCKED)
            self.assertTrue((Path(temp) / "workspaces" / task.id / "TASK.md").exists())

    def test_quality_gate_runs_real_test_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            orchestrator = self.make_orchestrator(Path(temp))
            task = orchestrator.create_task("Quality", "Run tests", ["python"])
            workspace = Path(temp) / "workspaces" / task.id
            workspace.mkdir(parents=True)
            (workspace / "test_ok.py").write_text("print('ok')\n", encoding="utf-8")
            task.metadata["coding"] = {"workspace": str(workspace)}
            task.metadata["test_commands"] = [f'"{sys.executable}" test_ok.py']
            orchestrator.context.storage.update_task(task)
            decision = orchestrator.quality_gate.run({"task_id": task.id})
            updated = orchestrator.context.storage.get_task(task.id)
            self.assertEqual(decision.action, "quality_gate_passed")
            self.assertEqual(updated.status, TaskStatus.DONE)

    def test_quality_gate_fails_without_tests_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            orchestrator = self.make_orchestrator(Path(temp))
            task = orchestrator.create_task("Quality", "Run tests", ["python"])
            workspace = Path(temp) / "workspaces" / task.id
            workspace.mkdir(parents=True)
            (workspace / "file.py").write_text("x = 1\n", encoding="utf-8")
            task.metadata["coding"] = {"workspace": str(workspace)}
            orchestrator.context.storage.update_task(task)
            decision = orchestrator.quality_gate.run({"task_id": task.id})
            updated = orchestrator.context.storage.get_task(task.id)
            self.assertEqual(decision.action, "quality_gate_failed")
            self.assertEqual(updated.status, TaskStatus.BLOCKED)

    def test_openai_responses_text_extraction(self) -> None:
        raw = {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "{\"files\": [], \"commands\": [], \"notes\": \"ok\"}"}
                    ]
                }
            ]
        }
        text = extract_responses_text(raw)
        parsed = parse_json_text(text)
        self.assertEqual(parsed["notes"], "ok")

    def test_env_file_loader_does_not_override_existing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / ".env"
            env_file.write_text("AGENTOS_TEST_ENV=from_file\nAGENTOS_KEEP_ENV=from_file\n", encoding="utf-8")
            os.environ["AGENTOS_KEEP_ENV"] = "already_set"
            try:
                load_env_file(env_file)
                self.assertEqual(os.environ["AGENTOS_TEST_ENV"], "from_file")
                self.assertEqual(os.environ["AGENTOS_KEEP_ENV"], "already_set")
            finally:
                os.environ.pop("AGENTOS_TEST_ENV", None)
                os.environ.pop("AGENTOS_KEEP_ENV", None)

    def test_llm_status_cli_does_not_print_api_key(self) -> None:
        from agent_workforce_os.cli import main
        from io import StringIO
        import contextlib

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config.toml"
            env_path = root / ".env"
            env_path.write_text("OPENAI_API_KEY=secret-value\nAGENTOS_LLM_MODEL=gpt-5.5\n", encoding="utf-8")
            config_path.write_text(
                f"""
[storage]
database_path = "{(root / 'agentos.db').as_posix()}"
[workspace]
root_path = "{(root / 'workspaces').as_posix()}"
artifact_path = "{(root / 'artifacts').as_posix()}"
[llm]
provider = "openai-responses"
env_file = "{env_path.as_posix()}"
api_key_env = "OPENAI_API_KEY"
model_env = "AGENTOS_LLM_MODEL"
""".strip(),
                encoding="utf-8",
            )
            output = StringIO()
            with contextlib.redirect_stdout(output):
                main(["--config", str(config_path), "llm-status"])
            self.assertNotIn("secret-value", output.getvalue())
            self.assertIn("openai-responses", output.getvalue())


if __name__ == "__main__":
    unittest.main()
