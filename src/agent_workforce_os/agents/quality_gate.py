from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .base_imports import AgentDecision, Artifact, BaseAgent, TaskStatus, new_id
from agent_workforce_os.tools.workspace import ensure_within_root


class TestHarnessAgent(BaseAgent):
    name = "test_harness"

    def _run(self, input_payload: dict) -> AgentDecision:
        task_id = input_payload["task_id"]
        task = self.context.storage.get_task(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        workspace_value = input_payload.get("workspace") or task.metadata.get("coding", {}).get("workspace")
        if not workspace_value:
            raise ValueError("No workspace was provided for test harness execution.")
        workspace = ensure_within_root(self.context.config.workspace.root_path, Path(workspace_value))
        commands = input_payload.get("commands") or task.metadata.get("test_commands") or []
        allow_no_tests = bool(input_payload.get("allow_no_tests") or task.metadata.get("allow_no_tests"))

        checks = self._structural_checks(workspace)
        command_results = []
        for command in commands:
            result = subprocess.run(
                str(command),
                cwd=str(workspace),
                shell=True,
                capture_output=True,
                text=True,
                timeout=int(input_payload.get("timeout_seconds", 120)),
            )
            command_results.append(
                {
                    "command": command,
                    "returncode": result.returncode,
                    "stdout": result.stdout[-4000:],
                    "stderr": result.stderr[-4000:],
                }
            )

        issues = checks.copy()
        if not commands and not allow_no_tests:
            issues.append("No test commands configured for this workspace.")
        issues.extend(
            f"Command failed: {result['command']}" for result in command_results if int(result["returncode"]) != 0
        )
        passed = not issues

        report = {
            "task_id": task.id,
            "workspace": str(workspace),
            "passed": passed,
            "issues": issues,
            "commands": command_results,
        }
        self.context.config.workspace.artifact_path.mkdir(parents=True, exist_ok=True)
        report_path = self.context.config.workspace.artifact_path / f"{task.id}_quality_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.context.storage.record_artifact(
            Artifact(id=new_id("artifact"), task_id=task.id, path=str(report_path), artifact_type="quality_report")
        )

        task.metadata["quality_gate"] = report
        task.status = TaskStatus.DONE if passed else TaskStatus.BLOCKED
        self.context.storage.update_task(task)
        self.context.storage.record_event("task", task.id, "quality_gate_completed", {"passed": passed, "issues": issues})
        return AgentDecision(
            agent_name=self.name,
            action="quality_gate_passed" if passed else "quality_gate_failed",
            confidence=1.0,
            reasons=["All checks passed"] if passed else issues,
            payload=report,
        )

    def _structural_checks(self, workspace: Path) -> list[str]:
        issues = []
        if not workspace.exists():
            issues.append(f"Workspace does not exist: {workspace}")
        elif not any(workspace.iterdir()):
            issues.append(f"Workspace is empty: {workspace}")
        return issues


class QualityGateAgent(TestHarnessAgent):
    name = "quality_gate"

