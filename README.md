# Agent Workforce OS

Production-oriented v0 for a multi-agent startup system that can parse documents, understand resumes, route work to employees or digital agents, monitor execution, score performance, and run quality gates for agent-produced work.

This is not a demo script. It is a small real backend spine with durable SQLite storage, agent contracts, audit events, CLI operations, and a lightweight HTTP API. LLM-backed work is behind a provider interface so you can connect OpenAI-compatible models without changing the core agent lifecycle.

## What Exists

- Document intelligence agent: parses `.txt`, `.md`, `.json`, and `.docx`, extracts summaries, skills, and task-like requirements.
- Task router agent: assigns tasks to employees or digital agents using skills, experience, availability, workload, and performance score.
- Monitoring agent: finds unassigned, stale, overdue, blocked, and failed work.
- Performance agent: recalculates worker performance from live task state.
- Coding agent: creates controlled per-task workspaces and, when an LLM provider is configured, writes model-generated files under path guards.
- Quality gate and test harness: validates agent outputs, enforces workspace containment, runs configured test commands, and writes quality reports.
- Durable audit trail: all agent runs, events, tasks, workers, documents, and artifacts are stored in SQLite.
- Operator API: local HTTP API for health, workers, tasks, ingestion, routing, monitoring, and performance.

## Quick Start

From this folder:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os init
python -m unittest discover -s tests
```

Create real workers and tasks:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os add-worker --kind employee --name "Asha Rao" --title "Backend Engineer" --skills "python,sqlite,testing,api" --years 4
python -m agent_workforce_os add-worker --kind digital_agent --name "Builder Agent" --title "Coding Agent" --skills "python,testing,architecture,coding" --years 5
python -m agent_workforce_os create-task --title "Build ingestion API" --description "Create an API endpoint for document ingestion with validation and tests." --skills "python,api,testing" --priority 4
python -m agent_workforce_os list-tasks
python -m agent_workforce_os route --task-id TASK_ID_FROM_LIST
python -m agent_workforce_os monitor
python -m agent_workforce_os performance
```

Ingest a resume or business document:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os ingest-document "C:\path\to\resume.docx"
python -m agent_workforce_os add-worker --kind employee --name "Candidate Name" --resume "C:\path\to\resume.docx"
```

Run the API:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os serve --host 127.0.0.1 --port 8080
```

Then call:

- `GET /health`
- `GET /workers`
- `GET /tasks`
- `POST /tasks`
- `POST /workers`
- `POST /route`
- `POST /monitor`
- `POST /performance`
- `POST /ingest-document`

## OpenAI Provider

Core lifecycle agents run locally. Open-ended coding and richer reasoning use the OpenAI Responses API provider when `OPENAI_API_KEY` is configured.

Create a local `.env` from `.env.example`:

```powershell
Copy-Item .env.example .env
```

Then set:

```text
AGENTOS_LLM_PROVIDER=openai-responses
OPENAI_BASE_URL=https://api.openai.com/v1
AGENTOS_LLM_MODEL=gpt-5.5
OPENAI_API_KEY=your_key
```

Check the connection state without printing secrets:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os llm-status
```

The coding agent requests a strict structured JSON coding plan, validates every generated path, and only writes inside the configured workspace root.

## Configuration

Default config lives in [configs/default.toml](configs/default.toml). Runtime data is written under `runtime/`:

- `runtime/agentos.db`: SQLite database
- `runtime/workspaces/`: controlled coding agent workspaces
- `runtime/artifacts/`: quality reports and other artifacts

## Product Path

Recommended next build steps:

1. Replace the lightweight HTTP server with FastAPI once dependency installation is part of deployment.
2. Add auth, organizations, projects, and role-based permissions.
3. Add a queue worker for async agent runs.
4. Add richer document adapters for PDF, Google Drive, SharePoint, Slack, GitHub, and Jira.
5. Add trace visualization and human approval gates before code-writing agents modify customer repositories.
6. Add eval datasets for router accuracy, document extraction accuracy, and coding agent quality.
