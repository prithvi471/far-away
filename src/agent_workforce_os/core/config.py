from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SKILLS = [
    "python",
    "javascript",
    "typescript",
    "sql",
    "api",
    "testing",
    "architecture",
    "agents",
    "monitoring",
    "performance",
    "coding",
    "qa",
]


@dataclass
class StorageConfig:
    database_path: Path


@dataclass
class WorkspaceConfig:
    root_path: Path
    artifact_path: Path


@dataclass
class LLMConfig:
    provider: str = "none"
    endpoint_env: str = "AGENTOS_LLM_ENDPOINT"
    api_key_env: str = "OPENAI_API_KEY"
    model_env: str = "AGENTOS_LLM_MODEL"
    temperature: float = 0.2
    timeout_seconds: int = 60


@dataclass
class RoutingConfig:
    min_confidence: float = 0.25
    skill_weight: float = 0.46
    experience_weight: float = 0.16
    availability_weight: float = 0.14
    load_weight: float = 0.12
    performance_weight: float = 0.12


@dataclass
class MonitoringConfig:
    stale_hours: int = 24


@dataclass
class RuntimeConfig:
    root_dir: Path
    storage: StorageConfig
    workspace: WorkspaceConfig
    llm: LLMConfig = field(default_factory=LLMConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    skills_catalog: list[str] = field(default_factory=lambda: DEFAULT_SKILLS.copy())


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if isinstance(value, dict):
        return value
    return {}


def load_config(path: str | Path | None = None) -> RuntimeConfig:
    env_path = os.environ.get("AGENTOS_CONFIG")
    config_path = Path(path or env_path or "configs/default.toml")
    if config_path.exists():
        base_dir = config_path.resolve().parent.parent
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    else:
        base_dir = Path.cwd().resolve()
        data = {}

    storage = _section(data, "storage")
    workspace = _section(data, "workspace")
    llm = _section(data, "llm")
    routing = _section(data, "routing")
    monitoring = _section(data, "monitoring")
    skills = _section(data, "skills")

    return RuntimeConfig(
        root_dir=base_dir,
        storage=StorageConfig(
            database_path=_resolve_path(storage.get("database_path", "runtime/agentos.db"), base_dir)
        ),
        workspace=WorkspaceConfig(
            root_path=_resolve_path(workspace.get("root_path", "runtime/workspaces"), base_dir),
            artifact_path=_resolve_path(workspace.get("artifact_path", "runtime/artifacts"), base_dir),
        ),
        llm=LLMConfig(
            provider=str(llm.get("provider", "none")),
            endpoint_env=str(llm.get("endpoint_env", "AGENTOS_LLM_ENDPOINT")),
            api_key_env=str(llm.get("api_key_env", "OPENAI_API_KEY")),
            model_env=str(llm.get("model_env", "AGENTOS_LLM_MODEL")),
            temperature=float(llm.get("temperature", 0.2)),
            timeout_seconds=int(llm.get("timeout_seconds", 60)),
        ),
        routing=RoutingConfig(
            min_confidence=float(routing.get("min_confidence", 0.25)),
            skill_weight=float(routing.get("skill_weight", 0.46)),
            experience_weight=float(routing.get("experience_weight", 0.16)),
            availability_weight=float(routing.get("availability_weight", 0.14)),
            load_weight=float(routing.get("load_weight", 0.12)),
            performance_weight=float(routing.get("performance_weight", 0.12)),
        ),
        monitoring=MonitoringConfig(stale_hours=int(monitoring.get("stale_hours", 24))),
        skills_catalog=[str(skill).lower() for skill in skills.get("catalog", DEFAULT_SKILLS)],
    )

