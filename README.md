# Agent Workforce OS

Production-oriented v0 for a multi-agent startup system that can parse documents, understand resumes, route work to employees or digital agents, monitor execution, score performance, and run quality gates for agent-produced work.

This is not a demo script. It is a small real backend spine with durable SQLite storage, agent contracts, tenant-scoped records, token auth, async queue jobs, audit events, CLI operations, and a FastAPI operator API. LLM-backed work is behind a provider interface so you can connect OpenAI-compatible models without changing the core agent lifecycle.

## What Exists

- Document intelligence agent: parses `.txt`, `.md`, `.json`, `.docx`, and optional PDF, extracts summaries, skills, and task-like requirements.
- Task router agent: assigns tasks to employees or digital agents using skills, experience, availability, workload, and performance score.
- Monitoring agent: finds unassigned, stale, overdue, blocked, and failed work.
- Performance agent: recalculates worker performance from live task state.
- Coding agent: creates controlled per-task workspaces and, when an LLM provider is configured, writes model-generated files under path guards.
- Quality gate and test harness: validates agent outputs, enforces workspace containment, runs configured test commands, and writes quality reports.
- Human approval gates: block coding-agent writes for tasks marked with `customer_repository` until approval is recorded.
- Async queue worker: persists route/build/ingest/monitor/performance jobs and records completion or failure.
- Organizations, projects, users, bearer API tokens, memberships, and role-based permissions.
- Connector document adapters for local files, HTTPS, Google Drive, SharePoint, Slack, GitHub, and Jira.
- Trace visualization: agent trace events can be rendered as Mermaid flowcharts.
- Built-in eval datasets for routing, document extraction, and coding-plan quality.
- Durable audit trail: all agent runs, events, tasks, workers, documents, and artifacts are stored in SQLite.
- Operator API: FastAPI app for health, auth-scoped workers, tasks, ingestion, queueing, approvals, traces, monitoring, performance, and evals.

## Quick Start

From this folder:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os init
python -m unittest discover -s tests
```

Bootstrap a local owner token for the API:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os bootstrap-admin --email founder@example.com --name "Founder"
```

Store the returned token securely and call the API with:

```text
Authorization: Bearer agos_...
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
pip install ".[api]"
$env:PYTHONPATH = "src"
python -m agent_workforce_os serve --host 127.0.0.1 --port 8080
```

Then call:

- `GET /health`
- `GET /organizations`
- `GET /projects`
- `GET /workers`
- `GET /tasks`
- `POST /tasks`
- `POST /workers`
- `POST /queue`
- `POST /queue/work`
- `GET /approvals`
- `POST /approvals/{approval_id}/approve`
- `GET /traces/{aggregate_id}`
- `POST /evals/run`
- `POST /route`
- `POST /monitor`
- `POST /performance`
- `POST /ingest-document`

Async queue examples:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os enqueue --job-type route_task --payload-json '{"task_id":"TASK_ID"}'
python -m agent_workforce_os work-queue --limit 5
python -m agent_workforce_os list-queue
```

Connector ingestion examples:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os ingest-source "github://owner/repo/path/to/brief.md?ref=main"
python -m agent_workforce_os ingest-source "google_drive://FILE_ID"
```

Vendor adapters use token environment variables where needed:

- `GOOGLE_DRIVE_TOKEN`
- `MICROSOFT_GRAPH_TOKEN`
- `SLACK_BOT_TOKEN`
- `GITHUB_TOKEN`
- `JIRA_API_TOKEN`

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

Run a live structured-output smoke test after adding `OPENAI_API_KEY`:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os llm-smoke-test
```

The coding agent requests a strict structured JSON coding plan, validates every generated path, and only writes inside the configured workspace root.

## Configuration

Default config lives in [configs/default.toml](configs/default.toml). Runtime data is written under `runtime/`:

- `runtime/agentos.db`: SQLite database
- `runtime/workspaces/`: controlled coding agent workspaces
- `runtime/artifacts/`: quality reports and other artifacts

## Evals

Built-in datasets live under `evals/`:

- `router_accuracy.jsonl`
- `document_extraction.jsonl`
- `coding_quality.jsonl`

Run them with:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workforce_os run-evals
```
