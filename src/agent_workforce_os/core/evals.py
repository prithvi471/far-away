from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_workforce_os.agents.orchestrator import AgentOrchestrator
from agent_workforce_os.agents.coding import CODING_PLAN_SCHEMA
from agent_workforce_os.core.models import EvalRun, WorkerKind, new_id
from agent_workforce_os.tools.document_parsers import extract_candidate_tasks, extract_skills
from agent_workforce_os.tools.workspace import safe_join


def run_all_evals(orchestrator: AgentOrchestrator, eval_root: Path) -> dict[str, Any]:
    results = {
        "router_accuracy": run_router_eval(orchestrator, eval_root / "router_accuracy.jsonl"),
        "document_extraction": run_document_eval(orchestrator, eval_root / "document_extraction.jsonl"),
        "coding_quality": run_coding_quality_eval(eval_root / "coding_quality.jsonl"),
    }
    total = sum(item["score"] for item in results.values()) / max(len(results), 1)
    run = EvalRun(id=new_id("eval"), dataset_name="builtin", status="ok", score=round(total, 4), metrics=results)
    orchestrator.context.storage.record_eval_run(run)
    return {"run": asdict(run), "datasets": results}


def run_router_eval(orchestrator: AgentOrchestrator, dataset_path: Path) -> dict[str, Any]:
    cases = _read_jsonl(dataset_path)
    passed = 0
    details = []
    for case in cases:
        worker_ids = []
        for worker_case in case["workers"]:
            worker = orchestrator.register_worker(
                kind=WorkerKind(worker_case["kind"]),
                name=f"eval_{case['name']}_{worker_case['name']}",
                skills=worker_case.get("skills", []),
                years_experience=float(worker_case.get("years", 0)),
            )
            worker_ids.append(worker.id)
        task_case = case["task"]
        task = orchestrator.create_task(
            title=f"eval_{case['name']}_{task_case['title']}",
            description=task_case["description"],
            required_skills=task_case.get("skills", []),
        )
        decision = orchestrator.route_task(task.id)
        assignee = orchestrator.context.storage.get_worker(decision["payload"]["assignee_id"])
        selected = assignee.name.removeprefix(f"eval_{case['name']}_") if assignee else ""
        ok = selected == case["expected_assignee"]
        passed += 1 if ok else 0
        details.append({"name": case["name"], "selected": selected, "expected": case["expected_assignee"], "passed": ok})
    return _score("router_accuracy", passed, len(cases), details)


def run_document_eval(orchestrator: AgentOrchestrator, dataset_path: Path) -> dict[str, Any]:
    cases = _read_jsonl(dataset_path)
    passed = 0
    details = []
    for case in cases:
        skills = extract_skills(case["text"], orchestrator.context.config.skills_catalog)
        tasks = extract_candidate_tasks(case["text"])
        ok = set(case["expected_skills"]).issubset(set(skills)) and len(tasks) == int(case["expected_task_count"])
        passed += 1 if ok else 0
        details.append({"name": case["name"], "skills": skills, "task_count": len(tasks), "passed": ok})
    return _score("document_extraction", passed, len(cases), details)


def run_coding_quality_eval(dataset_path: Path) -> dict[str, Any]:
    cases = _read_jsonl(dataset_path)
    passed = 0
    details = []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for case in cases:
            ok = _coding_plan_is_safe(root, case["plan"])
            expected = bool(case["should_pass"])
            passed_case = ok == expected
            passed += 1 if passed_case else 0
            details.append({"name": case["name"], "passed": passed_case, "safe": ok, "expected_safe": expected})
    return _score("coding_quality", passed, len(cases), details)


def _coding_plan_is_safe(root: Path, plan: dict[str, Any]) -> bool:
    if not _schema_shape_ok(plan):
        return False
    try:
        for file_spec in plan["files"]:
            safe_join(root, file_spec["path"])
    except ValueError:
        return False
    has_test = any("test" in file_spec["path"].lower() for file_spec in plan["files"])
    has_command = bool(plan.get("commands"))
    return has_test and has_command


def _schema_shape_ok(plan: dict[str, Any]) -> bool:
    required = set(CODING_PLAN_SCHEMA["required"])
    return required.issubset(plan) and isinstance(plan.get("files"), list) and isinstance(plan.get("commands"), list)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _score(name: str, passed: int, total: int, details: list[dict[str, Any]]) -> dict[str, Any]:
    return {"dataset": name, "passed": passed, "total": total, "score": round(passed / max(total, 1), 4), "details": details}

