from __future__ import annotations

from typing import Any

from agent_workforce_os.agents.orchestrator import AgentOrchestrator


class QueueWorker:
    def __init__(self, orchestrator: AgentOrchestrator):
        self.orchestrator = orchestrator

    def run_once(self) -> dict[str, Any]:
        job = self.orchestrator.context.storage.claim_next_job()
        if job is None:
            return {"status": "idle"}
        try:
            result = self._execute(job.job_type, job.payload)
            self.orchestrator.context.storage.complete_job(job.id, result)
            return {"status": "completed", "job_id": job.id, "result": result}
        except Exception as exc:
            self.orchestrator.context.storage.fail_job(job.id, str(exc))
            return {"status": "failed", "job_id": job.id, "error": str(exc)}

    def run_batch(self, limit: int = 10) -> list[dict[str, Any]]:
        results = []
        for _ in range(limit):
            result = self.run_once()
            results.append(result)
            if result["status"] == "idle":
                break
        return results

    def _execute(self, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if job_type == "route_task":
            return self.orchestrator.route_task(payload["task_id"])
        if job_type == "build_task":
            return self.orchestrator.run_build_pipeline(
                payload["task_id"],
                test_commands=payload.get("test_commands"),
                allow_no_tests=bool(payload.get("allow_no_tests", False)),
            )
        if job_type == "ingest_source":
            return self.orchestrator.ingest_source(
                payload["uri"],
                llm_summary=bool(payload.get("llm_summary", False)),
                organization_id=payload.get("organization_id", "org_default"),
                project_id=payload.get("project_id", "project_default"),
            )
        if job_type == "monitor":
            return self.orchestrator.monitor()
        if job_type == "performance":
            return self.orchestrator.recalculate_performance()
        raise ValueError(f"Unsupported queue job type: {job_type}")
