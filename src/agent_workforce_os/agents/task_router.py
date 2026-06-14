from __future__ import annotations

from .base_imports import AgentDecision, BaseAgent, TaskStatus


def _normalize_skill(skill: str) -> str:
    return skill.strip().lower()


class TaskRouterAgent(BaseAgent):
    name = "task_router"

    def _run(self, input_payload: dict) -> AgentDecision:
        task_id = input_payload["task_id"]
        task = self.context.storage.get_task(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        workers = self.context.storage.list_workers()
        if not workers:
            return AgentDecision(
                agent_name=self.name,
                action="assignment_blocked",
                confidence=0.0,
                reasons=["No workers or digital agents are registered"],
                payload={"task_id": task_id},
            )

        scored = []
        for worker in workers:
            active_count = self.context.storage.active_task_count(worker.id)
            score, parts = self._score(task.required_skills, worker.skills, worker.years_experience, worker.availability, active_count, worker.performance_score)
            scored.append(
                {
                    "worker_id": worker.id,
                    "name": worker.name,
                    "kind": worker.kind.value,
                    "score": round(score, 4),
                    "parts": parts,
                    "active_tasks": active_count,
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        best = scored[0]
        threshold = self.context.config.routing.min_confidence
        if best["score"] < threshold:
            task.status = TaskStatus.BLOCKED
            task.metadata["routing"] = {"candidates": scored, "reason": "No candidate met routing threshold"}
            self.context.storage.update_task(task)
            self.context.storage.record_event("task", task.id, "assignment_blocked", task.metadata["routing"])
            return AgentDecision(
                agent_name=self.name,
                action="assignment_blocked",
                confidence=best["score"],
                reasons=[f"Best candidate scored below threshold {threshold}"],
                payload={"task_id": task.id, "candidates": scored},
            )

        task.assignee_id = best["worker_id"]
        task.status = TaskStatus.ASSIGNED
        task.metadata["routing"] = {"selected": best, "candidates": scored}
        self.context.storage.update_task(task)
        self.context.storage.record_event("task", task.id, "task_assigned", {"assignee_id": best["worker_id"], "score": best["score"]})
        return AgentDecision(
            agent_name=self.name,
            action="task_assigned",
            confidence=best["score"],
            reasons=[
                f"Selected {best['name']} with score {best['score']}",
                f"Matched required skills: {', '.join(task.required_skills) or 'none specified'}",
            ],
            payload={"task_id": task.id, "assignee_id": best["worker_id"], "candidates": scored},
        )

    def _score(
        self,
        required_skills: list[str],
        worker_skills: dict[str, float],
        years_experience: float,
        availability: float,
        active_count: int,
        performance_score: float,
    ) -> tuple[float, dict[str, float]]:
        routing = self.context.config.routing
        required = [_normalize_skill(skill) for skill in required_skills if skill.strip()]
        normalized_worker = {_normalize_skill(skill): float(level) for skill, level in worker_skills.items()}
        if required:
            matched = sum(min(normalized_worker.get(skill, 0.0), 5.0) / 5.0 for skill in required)
            skill_score = matched / len(required)
        else:
            skill_score = 0.35
        experience_score = min(max(years_experience, 0.0) / 10.0, 1.0)
        availability_score = min(max(availability, 0.0), 1.0)
        load_score = 1.0 / (1.0 + max(active_count, 0))
        performance = min(max(performance_score, 0.0), 1.0)
        total = (
            skill_score * routing.skill_weight
            + experience_score * routing.experience_weight
            + availability_score * routing.availability_weight
            + load_score * routing.load_weight
            + performance * routing.performance_weight
        )
        return total, {
            "skill": round(skill_score, 4),
            "experience": round(experience_score, 4),
            "availability": round(availability_score, 4),
            "load": round(load_score, 4),
            "performance": round(performance, 4),
        }

