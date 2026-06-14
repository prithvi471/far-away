from __future__ import annotations

import re

from .models import TraceEvent


def trace_to_mermaid(events: list[TraceEvent]) -> str:
    lines = ["flowchart TD"]
    if not events:
        lines.append('  empty["No trace events"]')
        return "\n".join(lines)
    previous_node = None
    for index, event in enumerate(events, start=1):
        node_id = f"n{index}"
        label = _label(f"{event.event_type}\\n{event.created_at}")
        lines.append(f'  {node_id}["{label}"]')
        if previous_node:
            lines.append(f"  {previous_node} --> {node_id}")
        previous_node = node_id
    return "\n".join(lines)


def _label(value: str) -> str:
    return re.sub(r'["<>]', "", value)

