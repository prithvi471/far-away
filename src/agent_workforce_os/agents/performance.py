from __future__ import annotations

from .base_imports import AgentDecision, BaseAgent, TaskStatus


class PerformanceAgent(BaseAgent):
    name = "performance"

    def _run(self, input_payload: dict) -> AgentDecision:
        workers = self.context.storage.list_workers()
        tasks = self.context.storage.list_tasks()
        metrics = []
        for worker in workers:
            assigned = [task for task in tasks if task.assignee_id == worker.id]
            done = len([task for task in assigned if task.status == TaskStatus.DONE])
            failed = len([task for task in assigned if task.status == TaskStatus.FAILED])
            active = len([task for task in assigned if task.status in {TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.REVIEW}])
            closed = done + failed
            if closed == 0:
                completion_rate = 0.7
                reliability = 0.7
            else:
                completion_rate = done / closed
                reliability = 1.0 - (failed / closed)
            load_factor = 1.0 / (1.0 + active)
            score = round((completion_rate * 0.45) + (reliability * 0.35) + (load_factor * 0.20), 4)
            worker.active_tasks = active
            worker.performance_score = score
            self.context.storage.upsert_worker(worker)
            metrics.append(
                {
                    "worker_id": worker.id,
                    "name": worker.name,
                    "kind": worker.kind.value,
                    "assigned": len(assigned),
                    "done": done,
                    "failed": failed,
                    "active": active,
                    "performance_score": score,
                }
            )

        self.context.storage.record_event("system", "performance", "performance_recalculated", {"metrics": metrics})
        return AgentDecision(
            agent_name=self.name,
            action="performance_recalculated",
            confidence=1.0,
            reasons=[f"Updated {len(metrics)} worker profiles"],
            payload={"metrics": metrics},
        )
