# Claude Agent Harness Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build and locally validate a production-shaped vertical slice that publishes an Agent manifest, creates a Session and asynchronous Run, executes through a runtime worker, streams Harness/AG-UI events, supports approvals and artifacts, and can switch from a fake runtime to Claude Agent SDK through new-api.

**Architecture:** Use one Python distribution with strict internal package boundaries for Core, application services, runtime, storage, sandbox, API, worker, AG-UI, and observability. PostgreSQL is the authoritative store, Redis provides queue/event/lease coordination, MinIO stores artifacts, and a Next.js CopilotKit console consumes an AG-UI adapter. Local observability is no-op; production OTLP/Langfuse configuration remains pluggable.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI, SQLAlchemy 2, Alembic, asyncpg, redis-py, MinIO client, Claude Agent SDK, OpenTelemetry API, pytest, testcontainers or Docker Compose, React/Next.js, CopilotKit, AG-UI.

---

## Delivery rules

- Follow strict red/green/refactor TDD for each task.
- Keep `harness.core` free of framework and infrastructure imports.
- Use UUIDv7-compatible sortable IDs where available; otherwise use UUID4 behind an `IdGenerator` port.
- Every state transition and external side effect must be idempotent.
- Local default is `RUNTIME=fake` and `OTEL_ENABLED=false`.
- Never require a live model key for unit or integration tests.
- Commit after every task with the specified message.

### Task 1: Scaffold the Python project and quality gates

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/harness/__init__.py`
- Create: `src/harness/config.py`
- Create: `tests/unit/test_config.py`
- Create: `Makefile`

**Step 1: Write the failing configuration test**

```python
from harness.config import Settings


def test_local_defaults_disable_external_model_and_otel() -> None:
    settings = Settings(_env_file=None)
    assert settings.environment == "local"
    assert settings.runtime == "fake"
    assert settings.otel_enabled is False
```

**Step 2: Run the test and verify failure**

Run: `python -m pytest tests/unit/test_config.py -v`

Expected: FAIL because `harness.config` does not exist.

**Step 3: Add minimal package and settings**

Use `pydantic-settings`; include PostgreSQL, Redis, MinIO, new-api, official Anthropic fallback, runtime and OTEL settings. Secrets must default to empty strings and `.env.example` must contain placeholders only.

**Step 4: Add tooling**

Configure pytest, Ruff and Pyright in `pyproject.toml`. Add Make targets `install`, `test`, `lint`, `typecheck`, `verify`.

**Step 5: Verify**

Run: `python -m pytest tests/unit/test_config.py -v && python -m ruff check src tests`

Expected: PASS.

**Step 6: Commit**

```bash
git add pyproject.toml .gitignore .env.example Makefile src tests
git commit -m "build: scaffold harness python project"
```

### Task 2: Define Core domain models and Run state machine

**Files:**
- Create: `src/harness/core/__init__.py`
- Create: `src/harness/core/models.py`
- Create: `src/harness/core/events.py`
- Create: `src/harness/core/errors.py`
- Create: `src/harness/core/state_machine.py`
- Create: `tests/unit/core/test_state_machine.py`
- Create: `tests/unit/core/test_events.py`

**Step 1: Write failing state transition tests**

Cover allowed paths:

```python
assert transition(RunStatus.QUEUED, RunStatus.PROVISIONING) is RunStatus.PROVISIONING
assert transition(RunStatus.RUNNING, RunStatus.WAITING_APPROVAL) is RunStatus.WAITING_APPROVAL
assert transition(RunStatus.WAITING_APPROVAL, RunStatus.RUNNING) is RunStatus.RUNNING
```

Cover rejected transitions, terminal immutability and structured `InvalidRunTransition`.

**Step 2: Run and verify failure**

Run: `python -m pytest tests/unit/core -v`

Expected: FAIL on missing modules.

**Step 3: Implement minimal domain types**

Create enums and immutable Pydantic models for AgentVersion, Session, Run, Message, ToolCall, ApprovalRequest, Artifact, WorkspaceSnapshot and ModelRoute. Keep framework types out of Core.

**Step 4: Implement versioned RunEvent**

Require `event_id`, `run_id`, `session_id`, `tenant_id`, `sequence`, `type`, `timestamp`, `payload`, `schema_version`, optional trace/span IDs.

**Step 5: Run tests and commit**

Run: `python -m pytest tests/unit/core -v`

Expected: PASS.

```bash
git add src/harness/core tests/unit/core
git commit -m "feat: add harness core domain model"
```

### Task 3: Implement Agent Manifest parsing, validation and snapshots

**Files:**
- Create: `src/harness/core/manifest.py`
- Create: `src/harness/core/snapshot.py`
- Create: `tests/fixtures/agents/echo-agent/agent.yaml`
- Create: `tests/fixtures/agents/echo-agent/prompts/system.md`
- Create: `tests/unit/core/test_manifest.py`
- Create: `agents/echo-agent/agent.yaml`
- Create: `agents/echo-agent/prompts/system.md`

**Step 1: Write failing tests**

Test valid parsing, unknown runtime rejection, production `latest` subagent rejection, missing prompt rejection, secret-looking inline values rejection and deterministic content hash generation.

**Step 2: Verify red**

Run: `python -m pytest tests/unit/core/test_manifest.py -v`

Expected: FAIL.

**Step 3: Implement manifest schema**

Implement `AgentManifest`, `AgentSpec`, model route references, tools, skills, subagents, hooks, permissions, workspace and limits. Resolve paths relative to the manifest directory and calculate SHA-256 hashes without executing Python extensions.

**Step 4: Verify green and commit**

Run: `python -m pytest tests/unit/core/test_manifest.py -v`

Expected: PASS.

```bash
git add src/harness/core agents tests
git commit -m "feat: validate and snapshot agent manifests"
```

### Task 4: Define application ports and in-memory adapters

**Files:**
- Create: `src/harness/core/ports.py`
- Create: `src/harness/adapters/memory.py`
- Create: `tests/contract/test_repository_contract.py`
- Create: `tests/contract/test_event_bus_contract.py`
- Create: `tests/contract/test_artifact_store_contract.py`

**Step 1: Write async contract tests**

Define reusable suites for AgentRegistry, SessionRepository, RunRepository, EventRepository/EventBus, ArtifactStore, TranscriptStore, TaskQueue, LockManager, SandboxProvider and AgentRuntime.

**Step 2: Verify red**

Run: `python -m pytest tests/contract -v`

Expected: FAIL.

**Step 3: Implement Protocols and in-memory adapters**

Provide deterministic in-memory implementations for tests and local no-Docker smoke mode. Enforce tenant scoping and optimistic version checks.

**Step 4: Verify and commit**

Run: `python -m pytest tests/contract -v`

Expected: PASS.

```bash
git add src/harness/core/ports.py src/harness/adapters tests/contract
git commit -m "feat: add harness ports and memory adapters"
```

### Task 5: Build application services for Agent, Session and Run

**Files:**
- Create: `src/harness/application/__init__.py`
- Create: `src/harness/application/agents.py`
- Create: `src/harness/application/sessions.py`
- Create: `src/harness/application/runs.py`
- Create: `src/harness/application/events.py`
- Create: `tests/unit/application/test_agent_service.py`
- Create: `tests/unit/application/test_run_service.py`

**Step 1: Write failing service tests**

Cover validate/publish immutable AgentVersion, create Session only from published version, idempotent Run creation, ordered event append, cancel signal and duplicate idempotency key behavior.

**Step 2: Verify red**

Run: `python -m pytest tests/unit/application -v`

Expected: FAIL.

**Step 3: Implement minimal services**

Services depend only on Core ports. Use an injected clock and ID generator. Create Run and queue task in one application operation; in-memory mode can execute without transaction outbox until Task 9.

**Step 4: Verify and commit**

Run: `python -m pytest tests/unit/application -v`

Expected: PASS.

```bash
git add src/harness/application tests/unit/application
git commit -m "feat: add agent session and run services"
```

### Task 6: Implement FakeRuntime, LocalSandbox and Worker orchestration

**Files:**
- Create: `src/harness/runtime/base.py`
- Create: `src/harness/runtime/fake.py`
- Create: `src/harness/sandbox/local.py`
- Create: `src/harness/worker/orchestrator.py`
- Create: `src/harness/worker/main.py`
- Create: `tests/unit/worker/test_orchestrator.py`

**Step 1: Write failing vertical worker test**

Given a queued Run, assert transitions through provisioning/running/succeeded, ordered events are emitted, workspace is created and destroyed, and duplicate delivery does not execute twice.

Add cancellation and runtime failure cases.

**Step 2: Verify red**

Run: `python -m pytest tests/unit/worker -v`

Expected: FAIL.

**Step 3: Implement minimal worker**

FakeRuntime emits deterministic text deltas, optional tool events and artifacts from prompt directives. LocalSandbox uses a temporary directory and always cleans up in `finally`.

**Step 4: Verify and commit**

Run: `python -m pytest tests/unit/worker -v`

Expected: PASS.

```bash
git add src/harness/runtime src/harness/sandbox src/harness/worker tests/unit/worker
git commit -m "feat: execute runs with fake runtime worker"
```

### Task 7: Add FastAPI Harness API and SSE

**Files:**
- Create: `src/harness/api/__init__.py`
- Create: `src/harness/api/app.py`
- Create: `src/harness/api/dependencies.py`
- Create: `src/harness/api/schemas.py`
- Create: `src/harness/api/routes/agents.py`
- Create: `src/harness/api/routes/sessions.py`
- Create: `src/harness/api/routes/runs.py`
- Create: `src/harness/api/routes/approvals.py`
- Create: `src/harness/api/routes/artifacts.py`
- Create: `tests/integration/api/test_run_api.py`
- Create: `tests/integration/api/test_sse.py`

**Step 1: Write failing API tests**

Use `httpx.AsyncClient` with in-memory dependencies. Test manifest validation/publish, session/run creation, idempotency key, run query, cancel and SSE replay using `Last-Event-ID`.

**Step 2: Verify red**

Run: `python -m pytest tests/integration/api -v`

Expected: FAIL.

**Step 3: Implement endpoints**

Use `/v1` routes from the design. Add a local dev identity middleware that requires explicit `X-Tenant-ID` and `X-User-ID`; production auth remains an adapter.

**Step 4: Verify and commit**

Run: `python -m pytest tests/integration/api -v`

Expected: PASS.

```bash
git add src/harness/api tests/integration/api
git commit -m "feat: expose harness api and event stream"
```

### Task 8: Add approval policy and resumable tool decisions

**Files:**
- Create: `src/harness/policy/models.py`
- Create: `src/harness/policy/rules.py`
- Create: `src/harness/application/approvals.py`
- Modify: `src/harness/worker/orchestrator.py`
- Modify: `src/harness/api/routes/approvals.py`
- Create: `tests/unit/policy/test_rules.py`
- Create: `tests/integration/test_approval_flow.py`

**Step 1: Write failing policy tests**

Test low-risk Read allow, destructive Bash deny, configured Write ask, tenant/agent/tool/path matching and deterministic precedence.

**Step 2: Write failing approval flow test**

FakeRuntime requests a sensitive tool. Assert Run becomes waiting_approval, approval is idempotent, approved Run resumes, rejected Run receives a structured tool error, and expired approval cannot execute.

**Step 3: Verify red**

Run: `python -m pytest tests/unit/policy tests/integration/test_approval_flow.py -v`

Expected: FAIL.

**Step 4: Implement and verify**

Run the same command; expected PASS.

**Step 5: Commit**

```bash
git add src/harness/policy src/harness/application src/harness/worker src/harness/api tests
git commit -m "feat: add policy driven tool approvals"
```

### Task 9: Add PostgreSQL, Redis and MinIO adapters with local Compose

**Files:**
- Create: `deploy/docker-compose/compose.yaml`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/0001_initial.py`
- Create: `src/harness/storage/database.py`
- Create: `src/harness/storage/models.py`
- Create: `src/harness/storage/repositories.py`
- Create: `src/harness/storage/outbox.py`
- Create: `src/harness/storage/redis.py`
- Create: `src/harness/storage/minio.py`
- Create: `tests/integration/storage/test_postgres.py`
- Create: `tests/integration/storage/test_redis.py`
- Create: `tests/integration/storage/test_minio.py`
- Create: `scripts/wait_for_local_services.py`

**Step 1: Add Compose dependencies**

Use pinned PostgreSQL, Redis and MinIO images. Add health checks, named volumes and MinIO bucket initialization. Do not include Langfuse or OTel Collector in local Compose.

**Step 2: Write failing adapter contract executions**

Run existing contract suites against real services. Add outbox ordering, Run lease fencing, Redis duplicate delivery and artifact temporary-to-ready tests.

**Step 3: Start services and verify red**

Run:

```bash
docker compose -f deploy/docker-compose/compose.yaml up -d
python scripts/wait_for_local_services.py
python -m pytest tests/integration/storage -v
```

Expected: FAIL until adapters exist.

**Step 4: Implement adapters and migration**

PostgreSQL is authoritative. Redis loss must not lose Run/Event state. MinIO returns artifact metadata and presigned download URLs.

**Step 5: Verify green**

Run: `python -m pytest tests/contract tests/integration/storage -v`

Expected: PASS.

**Step 6: Commit**

```bash
git add deploy alembic.ini migrations src/harness/storage tests scripts
git commit -m "feat: add local postgres redis and minio stack"
```

### Task 10: Implement PostgreSQL Claude SDK SessionStore

**Files:**
- Create: `src/harness/runtime/session_store.py`
- Create: `tests/contract/test_sdk_session_store.py`
- Create: `tests/integration/runtime/test_session_resume.py`

**Step 1: Write failing conformance test**

Use `claude_agent_sdk.testing.run_session_store_conformance` against the PostgreSQL adapter.

**Step 2: Verify red**

Run: `python -m pytest tests/contract/test_sdk_session_store.py -v`

Expected: FAIL.

**Step 3: Implement append/load/list/list_subkeys/delete**

Preserve raw transcript entries and subagent subpaths. Enforce tenant/project scoping through adapter construction rather than altering SDK payloads.

**Step 4: Verify and commit**

Run: `python -m pytest tests/contract/test_sdk_session_store.py tests/integration/runtime/test_session_resume.py -v`

Expected: PASS.

```bash
git add src/harness/runtime/session_store.py tests
git commit -m "feat: persist claude sdk sessions in postgres"
```

### Task 11: Implement Claude Agent SDK runtime and model routing

**Files:**
- Create: `src/harness/runtime/claude_sdk.py`
- Create: `src/harness/runtime/model_router.py`
- Create: `src/harness/runtime/message_mapper.py`
- Create: `src/harness/runtime/hooks.py`
- Create: `tests/unit/runtime/test_model_router.py`
- Create: `tests/unit/runtime/test_message_mapper.py`
- Create: `tests/integration/runtime/test_claude_runtime_fake_transport.py`
- Create: `scripts/smoke_new_api.py`

**Step 1: Write failing routing tests**

Cover new-api priority, required capability rejection, explicit fallback event, no silent fallback, secret-free event payload and static model alias mapping.

**Step 2: Write failing SDK message mapping tests**

Map System/Assistant/User/Result/partial/tool/subagent lifecycle messages into ordered Harness events.

**Step 3: Verify red**

Run: `python -m pytest tests/unit/runtime tests/integration/runtime/test_claude_runtime_fake_transport.py -v`

Expected: FAIL.

**Step 4: Implement runtime**

Construct `ClaudeAgentOptions` from AgentVersion and ModelRoute, inject `ANTHROPIC_BASE_URL` plus auth token, configure agents/skills/MCP/hooks/session_store, stream events, support interrupt/cancel and never log secrets.

Abstract SDK client creation so tests use a fake transport without a model key.

**Step 5: Add optional live smoke script**

The script must require explicit `NEW_API_BASE_URL`, `NEW_API_KEY`, `NEW_API_MODEL`; test text streaming, tool use and a subagent. It must not run in default CI.

**Step 6: Verify and commit**

Run: `python -m pytest tests/unit/runtime tests/integration/runtime -v`

Expected: PASS.

```bash
git add src/harness/runtime tests scripts/smoke_new_api.py
git commit -m "feat: run agents through claude agent sdk"
```

### Task 12: Add workspace restore/archive and artifact lifecycle

**Files:**
- Create: `src/harness/application/workspaces.py`
- Create: `src/harness/application/artifacts.py`
- Modify: `src/harness/sandbox/local.py`
- Modify: `src/harness/worker/orchestrator.py`
- Create: `tests/integration/test_workspace_lifecycle.py`
- Create: `tests/integration/test_artifact_api.py`

**Step 1: Write failing lifecycle tests**

Upload input artifact, restore it into LocalSandbox, let FakeRuntime produce a file, archive workspace, publish output artifact, download and verify hash. Confirm failed uploads never become ready and cross-tenant reads fail.

**Step 2: Verify red**

Run: `python -m pytest tests/integration/test_workspace_lifecycle.py tests/integration/test_artifact_api.py -v`

Expected: FAIL.

**Step 3: Implement and verify**

Use temporary MinIO object keys and atomic metadata status transitions.

**Step 4: Commit**

```bash
git add src/harness/application src/harness/sandbox src/harness/worker tests
git commit -m "feat: persist workspaces and artifacts"
```

### Task 13: Add OpenTelemetry abstraction with local no-op mode

**Files:**
- Create: `src/harness/observability/__init__.py`
- Create: `src/harness/observability/provider.py`
- Create: `src/harness/observability/redaction.py`
- Modify: `src/harness/api/app.py`
- Modify: `src/harness/worker/orchestrator.py`
- Create: `deploy/otel-collector/collector.yaml`
- Create: `tests/unit/observability/test_redaction.py`
- Create: `tests/integration/test_trace_propagation.py`

**Step 1: Write failing tests**

Assert local defaults create no exporter, trace context propagates API -> queue task -> Worker -> runtime, and API keys/prompt-sensitive fields are redacted.

**Step 2: Verify red**

Run: `python -m pytest tests/unit/observability tests/integration/test_trace_propagation.py -v`

Expected: FAIL.

**Step 3: Implement provider**

Use OTel API everywhere. Configure SDK/exporter only when enabled. Add a production collector template for Langfuse OTLP HTTP but do not add it to local Compose.

**Step 4: Verify and commit**

Run: `python -m pytest tests/unit/observability tests/integration/test_trace_propagation.py -v`

Expected: PASS.

```bash
git add src/harness/observability src/harness/api src/harness/worker deploy/otel-collector tests
git commit -m "feat: add optional opentelemetry tracing"
```

### Task 14: Implement AG-UI protocol adapter

**Files:**
- Create: `src/harness/agui/__init__.py`
- Create: `src/harness/agui/mapper.py`
- Create: `src/harness/agui/routes.py`
- Modify: `src/harness/api/app.py`
- Create: `tests/unit/agui/test_mapper.py`
- Create: `tests/integration/agui/test_agui_stream.py`

**Step 1: Write failing mapper tests**

Map Run, text delta, tool, approval and state events to AG-UI standard events. Use versioned custom events for subagent, artifact, cost and trace link.

**Step 2: Verify red**

Run: `python -m pytest tests/unit/agui tests/integration/agui -v`

Expected: FAIL.

**Step 3: Implement adapter and stream route**

The adapter must be stateless and reconstruct state from Harness repositories. Preserve event IDs for reconnect and deduplication.

**Step 4: Verify and commit**

Run the same tests; expected PASS.

```bash
git add src/harness/agui src/harness/api tests
git commit -m "feat: expose agent runs through ag-ui"
```

### Task 15: Build CopilotKit validation console

**Files:**
- Create: `web/harness-console/package.json`
- Create: `web/harness-console/next.config.ts`
- Create: `web/harness-console/src/app/page.tsx`
- Create: `web/harness-console/src/app/layout.tsx`
- Create: `web/harness-console/src/components/agent-selector.tsx`
- Create: `web/harness-console/src/components/run-status.tsx`
- Create: `web/harness-console/src/components/tool-card.tsx`
- Create: `web/harness-console/src/components/approval-card.tsx`
- Create: `web/harness-console/src/components/artifact-list.tsx`
- Create: `web/harness-console/src/lib/harness-client.ts`
- Create: `web/harness-console/src/lib/agui.ts`
- Create: `web/harness-console/tests/approval.spec.ts`

**Step 1: Scaffold with CopilotKit and AG-UI client**

Pin versions in `package.json`; do not use hosted persistence.

**Step 2: Write failing component/E2E tests**

Test Agent version selection, streaming text, tool card, approval action, cancel, artifact download and page reload state recovery.

**Step 3: Verify red**

Run: `cd web/harness-console && npm test`

Expected: FAIL.

**Step 4: Implement the minimal console**

Use Harness API as authoritative state and AG-UI for live interaction. Hide Langfuse links when absent.

**Step 5: Verify and commit**

Run: `cd web/harness-console && npm test && npm run build`

Expected: PASS.

```bash
git add web/harness-console
git commit -m "feat: add copilotkit harness console"
```

### Task 16: Complete local end-to-end validation and documentation

**Files:**
- Create: `README.md`
- Create: `docs/local-development.md`
- Create: `scripts/dev_up.sh`
- Create: `scripts/dev_down.sh`
- Create: `scripts/e2e_fake_runtime.py`
- Create: `tests/e2e/test_local_stack.py`
- Modify: `.env.example`
- Modify: `Makefile`

**Step 1: Write the E2E verifier**

The verifier must:

1. Check PostgreSQL, Redis and MinIO health.
2. Publish `echo-agent`.
3. Create Session and Run.
4. Consume ordered SSE events.
5. Observe a tool approval.
6. Approve it and observe Run resume.
7. Download and hash an artifact.
8. Assert terminal success.
9. Assert OTEL/Langfuse is disabled and no endpoint is required.

**Step 2: Run and fix until green**

Run:

```bash
make dev-up
make migrate
make e2e
make verify
cd web/harness-console && npm run build
```

Expected: all commands exit 0.

**Step 3: Document local use**

Document prerequisites, commands, local URLs, fake runtime, optional new-api smoke test, troubleshooting and cleanup. Explicitly state that local Compose does not include Langfuse.

**Step 4: Final verification**

Run:

```bash
git status --short
make verify
make e2e
```

Expected: clean status after commit; all tests pass.

**Step 5: Commit**

```bash
git add README.md docs scripts tests .env.example Makefile
git commit -m "docs: complete phase one local validation"
```

## Phase 1 completion gate

Phase 1 is complete only when all of the following are proven by fresh command output:

- Python unit, contract and integration suites pass.
- PostgreSQL, Redis and MinIO adapter contracts pass against local containers.
- Fake runtime E2E passes without any external model or Langfuse service.
- Claude SDK runtime tests pass with fake transport.
- Optional live new-api smoke script is documented and skips safely without credentials.
- AG-UI stream contract tests pass.
- CopilotKit console tests and production build pass.
- Approval resume, cancellation, artifact lifecycle and session resume are covered.
- Local startup and cleanup instructions are reproducible.
- No secrets exist in tracked files.
