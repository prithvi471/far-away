from __future__ import annotations

import json
from pathlib import Path

from .base_imports import AgentDecision, Artifact, BaseAgent, TaskStatus, new_id
from agent_workforce_os.tools.workspace import safe_join


class CodingAgent(BaseAgent):
    name = "coding"

    def _run(self, input_payload: dict) -> AgentDecision:
        task_id = input_payload["task_id"]
        task = self.context.storage.get_task(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        workspace = self.context.config.workspace.root_path / task.id
        workspace.mkdir(parents=True, exist_ok=True)
        task_spec = workspace / "TASK.md"
        task_spec.write_text(
            f"# {task.title}\n\n{task.description}\n\nRequired skills: {', '.join(task.required_skills)}\n",
            encoding="utf-8",
        )
        self.context.storage.record_artifact(
            Artifact(id=new_id("artifact"), task_id=task.id, path=str(task_spec), artifact_type="task_spec")
        )

        if not self.context.llm.available:
            task.status = TaskStatus.BLOCKED
            task.metadata["coding"] = {
                "workspace": str(workspace),
                "blocked_reason": "Coding agent requires a configured LLM provider for arbitrary code generation.",
            }
            self.context.storage.update_task(task)
            return AgentDecision(
                agent_name=self.name,
                action="coding_blocked_needs_llm",
                confidence=1.0,
                reasons=["Created a controlled task workspace", "No LLM provider is configured for code generation"],
                payload={"task_id": task.id, "workspace": str(workspace)},
            )

        response = self.context.llm.complete(
            system=(
                "You are a coding agent. Return only valid JSON with keys files, commands, and notes. "
                "files must be a list of objects with relative path and content strings. "
                "commands must be shell commands that can run from the workspace root."
            ),
            user=(
                f"Build the requested project work inside a new workspace.\n"
                f"Title: {task.title}\nDescription: {task.description}\n"
                f"Required skills: {', '.join(task.required_skills)}\n"
                "Return JSON only."
            ),
        )
        plan = self._parse_json(response.text)
        files = plan.get("files", [])
        if not isinstance(files, list):
            raise ValueError("LLM response field files must be a list")

        written = []
        for file_spec in files:
            relative = str(file_spec["path"])
            content = str(file_spec["content"])
            target = safe_join(workspace, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(str(target))
            self.context.storage.record_artifact(
                Artifact(id=new_id("artifact"), task_id=task.id, path=str(target), artifact_type="generated_file")
            )

        commands = plan.get("commands", [])
        if isinstance(commands, list):
            task.metadata["test_commands"] = [str(command) for command in commands]
        task.metadata["coding"] = {"workspace": str(workspace), "files_written": written, "notes": plan.get("notes", "")}
        task.status = TaskStatus.REVIEW
        self.context.storage.update_task(task)
        self.context.storage.record_event("task", task.id, "coding_completed", {"workspace": str(workspace), "files": written})
        return AgentDecision(
            agent_name=self.name,
            action="coding_completed",
            confidence=0.75,
            reasons=[f"Wrote {len(written)} files into guarded workspace"],
            payload={"task_id": task.id, "workspace": str(workspace), "files_written": written, "commands": commands},
        )

    def _parse_json(self, value: str) -> dict:
        clean = value.strip()
        if clean.startswith("```"):
            clean = clean.strip("`")
            if clean.startswith("json"):
                clean = clean[4:].strip()
        data = json.loads(clean)
        if not isinstance(data, dict):
            raise ValueError("LLM coding response must be a JSON object")
        return data

