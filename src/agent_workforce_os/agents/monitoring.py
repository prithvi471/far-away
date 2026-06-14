from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base_imports import AgentDecision, BaseAgent, TaskStatus


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class MonitoringAgent(BaseAgent):
    name = "monitoring"

    def _run(self, input_payload: dict) -> AgentDecision:
        now = datetime.now(timezone.utc)
        stale_after = now - timedelta(hours=self.context.config.monitoring.stale_hours)
        alerts = []
        terminal = {TaskStatus.DONE, TaskStatus.FAILED}
        for task in self.context.storage.list_tasks():
            if task.status in terminal:
                continue
            due_at = _parse_time(task.due_at)
            updated_at = _parse_time(task.updated_at)
            if task.assignee_id is None:
                alerts.append({"task_id": task.id, "severity": "medium", "type": "unassigned", "title": task.title})
            if due_at and due_at < now:
                alerts.append({"task_id": task.id, "severity": "high", "type": "overdue", "title": task.title})
            if updated_at and updated_at < stale_after:
                alerts.append({"task_id": task.id, "severity": "medium", "type": "stale", "title": task.title})
            if task.status == TaskStatus.BLOCKED:
                alerts.append({"task_id": task.id, "severity": "high", "type": "blocked", "title": task.title})

        self.context.storage.record_event("system", "monitoring", "monitoring_cycle", {"alerts": alerts})
        return AgentDecision(
            agent_name=self.name,
            action="monitoring_cycle_completed",
            confidence=1.0,
            reasons=[f"Evaluated {len(self.context.storage.list_tasks())} tasks", f"Raised {len(alerts)} alerts"],
            payload={"alerts": alerts},
        )

