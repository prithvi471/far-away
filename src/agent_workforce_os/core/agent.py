from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from .config import RuntimeConfig
from .llm import LLMProvider
from .models import AgentDecision, AgentRun, TraceEvent, new_id
from .storage import SQLiteStore


@dataclass
class AgentContext:
    config: RuntimeConfig
    storage: SQLiteStore
    llm: LLMProvider


class BaseAgent:
    name = "base_agent"

    def __init__(self, context: AgentContext):
        self.context = context

    def run(self, input_payload: dict[str, Any]) -> AgentDecision:
        started = time.perf_counter()
        try:
            decision = self._run(input_payload)
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.context.storage.record_agent_run(
                AgentRun(
                    id=new_id("run"),
                    agent_name=self.name,
                    input_payload=input_payload,
                    output_payload=asdict(decision),
                    status="ok",
                    duration_ms=duration_ms,
                )
            )
            aggregate_id = str(input_payload.get("task_id") or input_payload.get("document_id") or self.name)
            self.context.storage.record_trace_event(
                TraceEvent(
                    id=new_id("trace"),
                    trace_id=str(input_payload.get("trace_id") or aggregate_id),
                    aggregate_type="agent",
                    aggregate_id=aggregate_id,
                    event_type=f"{self.name}.{decision.action}",
                    payload={"confidence": decision.confidence, "reasons": decision.reasons},
                )
            )
            return decision
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.context.storage.record_agent_run(
                AgentRun(
                    id=new_id("run"),
                    agent_name=self.name,
                    input_payload=input_payload,
                    output_payload={},
                    status="failed",
                    error=str(exc),
                    duration_ms=duration_ms,
                )
            )
            raise

    def _run(self, input_payload: dict[str, Any]) -> AgentDecision:
        raise NotImplementedError
