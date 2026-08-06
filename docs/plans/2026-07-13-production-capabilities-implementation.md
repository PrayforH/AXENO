# Production Capabilities and Docker Deployment Implementation Plan

> **Execution rule:** Implement each task test-first. Observe the focused test fail for
> the intended reason, make the smallest production change, run the focused test again,
> then run the relevant regression suite before committing.

**Goal:** Fix browser uploads, implement the five approved platform capabilities, and
produce a verified Docker deployment for the Claude Agent Harness.

**Architecture:** Keep the Claude Agent SDK as the only agent loop. Extend the Harness
ports-and-adapters boundary with request-scoped MCP credentials, durable memory and file
catalogs, pluggable Local/Daytona execution, input processors, and an SDK artifact tool.
Use PostgreSQL, Redis, and MinIO in production; use in-memory/local adapters for focused
tests. Run Claude Code inside Daytona through a custom SDK `Transport` rather than
claiming isolation while executing on the Worker host.

**Tech stack:** Python 3.12, FastAPI, Claude Agent SDK, SQLAlchemy/Alembic, Redis, MinIO,
Daytona async SDK, OpenTelemetry, python-docx, openpyxl, python-pptx, pypdf, Pillow,
Next.js 16, assistant-ui, AG-UI, Vitest, Docker Compose.

---

## Task 1: Fix the assistant-ui upload boundary

**Files:**

- Modify: `web/harness-console/tests/input-attachment-adapter.spec.ts`
- Create: `web/harness-console/src/lib/upload-feedback-store.ts`
- Create: `web/harness-console/tests/upload-feedback-store.spec.ts`
- Modify: `web/harness-console/src/lib/input-attachment-adapter.ts`
- Modify: `web/harness-console/src/components/assistant-runtime-shell.tsx`
- Modify: `web/harness-console/src/components/agent-thread.tsx`
- Modify: `web/harness-console/src/app/styles.css`

**Steps:**

1. Add a failing assertion that the adapter wildcard is exactly `"*"` and add tests for
   upload-start, success, failure, and reset feedback.
2. Run `cd web/harness-console && npm test -- input-attachment-adapter upload-feedback`.
3. Change the adapter wildcard, publish structured progress/errors, and render an
   accessible Composer notice with retry-safe state.
4. Re-run focused tests and then `npm test`.
5. Manually verify a selected fixture creates an attachment chip and a
   `/api/input-artifacts` request.
6. Commit as `fix: restore browser input uploads`.

## Task 2: Add execution identity and platform domain ports

**Files:**

- Modify: `src/harness/core/models.py`
- Modify: `src/harness/core/ports.py`
- Modify: `src/harness/runtime/base.py`
- Modify: `src/harness/adapters/memory.py`
- Create: `tests/unit/core/test_platform_models.py`
- Create: `tests/contract/test_platform_repository_contract.py`

**Steps:**

1. Add failing tests for immutable execution identity, versioned user memory, thread file
   records, derived input lineage, workspace snapshot lookup, and AG-UI thread bindings.
2. Introduce `ExecutionIdentity`, `UserMemory`, `ThreadFile`, `ProcessedInput`, and the
   required repository protocols.
3. Extend `RuntimeContext` with identity, memory projection, processed input paths, and an
   optional runtime transport factory without exposing secrets in model serialization.
4. Implement in-memory repositories used by tests and local composition.
5. Run `uv run pytest tests/unit/core/test_platform_models.py tests/contract/test_platform_repository_contract.py`.
6. Commit as `feat: define production platform ports`.

## Task 3: Resolve MCP credentials per run

**Files:**

- Create: `src/harness/runtime/mcp_credentials.py`
- Modify: `src/harness/runtime/tools.py`
- Modify: `src/harness/runtime/registry_runtime.py`
- Modify: `src/harness/runtime/claude_sdk.py`
- Modify: `src/harness/config.py`
- Create: `tests/unit/runtime/test_mcp_credentials.py`
- Modify: `tests/unit/runtime/test_tools.py`
- Modify: `tests/integration/runtime/test_claude_runtime_fake_transport.py`

**Steps:**

1. Add failing tests proving two concurrent identities receive different MCP headers,
   logical registrations contain no inline secret, missing required credentials fail
   before query execution, and secret values do not enter emitted events.
2. Implement `DynamicMcpCredentialProvider`, an empty provider, request credential
   provider, and server secret-reference provider.
3. Resolve external MCP configs asynchronously for the current `ExecutionIdentity` and
   merge only allowlisted headers/environment fields.
4. Ensure redaction covers resolved header names and values at runtime event boundaries.
5. Run focused runtime tests, Ruff, and Pyright.
6. Commit as `feat: resolve MCP credentials per execution`.

## Task 4: Implement durable user memory and SDK update tool

**Files:**

- Create: `src/harness/application/memory.py`
- Create: `src/harness/runtime/memory_tools.py`
- Modify: `src/harness/runtime/tools.py`
- Modify: `src/harness/worker/orchestrator.py`
- Modify: `src/harness/runtime/claude_sdk.py`
- Create: `tests/unit/application/test_memory_service.py`
- Create: `tests/unit/runtime/test_memory_tools.py`
- Create: `tests/integration/runtime/test_memory_injection.py`

**Steps:**

1. Add failing tests for tenant/user/agent isolation, bounded prompt projection,
   optimistic concurrency, cross-session recall, and update-tool validation.
2. Implement `UserMemoryService` with bounded retries and explicit version comparison.
3. Create a per-run `update_user_memory` SDK MCP tool whose callback receives identity
   through a safely reset execution context.
4. Load memory before runtime execution and prepend a delimited `<user_memory>` section.
5. Verify no memory body appears in normal run events or trace attributes.
6. Run focused tests and commit as `feat: add user-scoped durable memory`.

## Task 5: Add file catalog and input processing pipeline

**Files:**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/harness/inputs/__init__.py`
- Create: `src/harness/inputs/base.py`
- Create: `src/harness/inputs/processors.py`
- Create: `src/harness/application/file_catalog.py`
- Modify: `src/harness/application/input_artifacts.py`
- Modify: `src/harness/agui/service.py`
- Modify: `src/harness/worker/orchestrator.py`
- Modify: `src/harness/api/routes/input_artifacts.py`
- Create: `tests/unit/inputs/test_processors.py`
- Create: `tests/unit/application/test_file_catalog.py`
- Modify: `tests/integration/test_input_artifact_api.py`
- Create: `tests/integration/test_input_processing.py`

**Steps:**

1. Add processor fixtures generated in tests for TXT, JSON, DOCX, XLSX, PPTX, PDF, and
   PNG; assert normalized Markdown, outlines, extracted metadata/images, lineage, and
   unsupported-file behavior.
2. Add `python-docx`, `openpyxl`, `python-pptx`, `pypdf`, and `Pillow` with bounded major
   versions and update the lockfile.
3. Implement a media-type/extension-routed `InputProcessor` that never mutates the
   original object and returns deterministic derived files.
4. Persist thread file catalog entries scoped by tenant, user, and session.
5. Add catalog list API and mount deterministic `inputs/original` and
   `inputs/processed` paths before runtime execution.
6. Run processor, API, and input staging tests.
7. Commit as `feat: preprocess inputs and catalog thread files`.

## Task 6: Make workspace restore/archive authoritative

**Files:**

- Modify: `src/harness/application/workspaces.py`
- Modify: `src/harness/core/ports.py`
- Modify: `src/harness/worker/orchestrator.py`
- Modify: `src/harness/adapters/memory.py`
- Modify: `tests/integration/test_workspace_lifecycle.py`
- Modify: `tests/unit/worker/test_orchestrator.py`

**Steps:**

1. Add failing tests proving a later run restores the newest snapshot before input
   staging, manifest flags are respected, corrupt archives fail closed, and traversal or
   symlink members are rejected.
2. Add a `WorkspaceSnapshotRepository`; stop treating the Session's optional snapshot ID
   as the only lookup mechanism.
3. Harden archive/restore against unsafe tar members and record snapshot metadata only
   after object storage succeeds.
4. Wire restore and archive in the orchestrator in the correct order.
5. Run workspace/orchestrator tests and commit as `feat: restore session workspaces`.

## Task 7: Add Daytona provider and remote Claude transport

**Files:**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/harness/sandbox/base.py`
- Create: `src/harness/sandbox/daytona.py`
- Create: `src/harness/runtime/daytona_transport.py`
- Modify: `src/harness/runtime/claude_sdk.py`
- Modify: `src/harness/config.py`
- Create: `tests/unit/sandbox/test_daytona.py`
- Create: `tests/unit/runtime/test_daytona_transport.py`
- Create: `scripts/smoke_daytona.py`

**Steps:**

1. Add failing contract tests for create/get/start/stop/archive behavior, identity labels,
   remote workspace paths, command construction, stdin writes, fragmented NDJSON framing,
   non-JSON diagnostics, exit errors, bounded close, and cancellation.
2. Add the Daytona async SDK with a bounded version range.
3. Implement `DaytonaSandboxProvider` against a small client protocol so unit tests need
   no network.
4. Implement a pinned, minimal Claude CLI command builder and `DaytonaClaudeTransport`.
   The transport must launch the CLI remotely, stream stdout separately from stderr, send
   SDK control messages through command stdin, and never execute builtin tools locally.
5. Select the remote transport only for Daytona handles; retain the default SDK transport
   for Local handles.
6. Add an optional smoke script that safely skips without Daytona credentials/snapshot.
7. Run focused tests, type checking, and commit as `feat: execute SDK runs in Daytona`.

## Task 8: Publish generated workspace files

**Files:**

- Create: `src/harness/runtime/artifact_tools.py`
- Modify: `src/harness/runtime/tools.py`
- Modify: `src/harness/worker/orchestrator.py`
- Modify: `src/harness/agui/activity.py`
- Modify: `src/harness/agui/mapper.py`
- Modify: `web/harness-console/src/components/artifact-list.tsx`
- Create: `tests/unit/runtime/test_artifact_tools.py`
- Modify: `tests/integration/test_artifact_api.py`
- Modify: `tests/integration/agui/test_agui_run.py`
- Modify: `web/harness-console/tests/activity-ui.spec.tsx`

**Steps:**

1. Add failing tests for successful publication, SHA-256/download correctness, traversal,
   symlink escape, directory, missing file, size limit, and cross-run access.
2. Create a per-run `publish_artifact` SDK MCP tool backed by `ArtifactService` and the
   active sandbox workspace facade.
3. Emit the authoritative artifact event only after durable storage succeeds.
4. Map the event to AG-UI and render a stable assistant-ui preview/download card.
5. Run Python and Web focused suites and commit as `feat: publish SDK workspace artifacts`.

## Task 9: Add production database models and repositories

**Files:**

- Modify: `src/harness/storage/models.py`
- Modify: `src/harness/storage/repositories.py`
- Create: `src/harness/storage/platform_repositories.py`
- Create: `migrations/versions/0003_production_platform.py`
- Modify: `tests/integration/storage/test_postgres.py`
- Modify: `tests/contract/test_repository_contract.py`
- Modify: `tests/contract/test_platform_repository_contract.py`

**Steps:**

1. Add failing contract/integration tests for durable agent, session, approval, artifact,
   input artifact, user memory, workspace snapshot, file catalog, and AG-UI binding
   repositories.
2. Add relational rows and uniqueness/index constraints, keeping JSON payloads for
   immutable domain snapshots where appropriate.
3. Implement repositories with tenant scoping and compare-and-set semantics.
4. Add and run the Alembic migration against the integration PostgreSQL service.
5. Run all storage contracts and commit as `feat: persist production platform state`.

## Task 10: Wire production composition and worker loop

**Files:**

- Create: `src/harness/composition.py`
- Modify: `src/harness/api/dependencies.py`
- Modify: `src/harness/api/app.py`
- Modify: `src/harness/worker/main.py`
- Modify: `src/harness/config.py`
- Create: `tests/unit/test_production_composition.py`
- Create: `tests/integration/test_worker_queue.py`

**Steps:**

1. Add failing tests proving production mode does not instantiate in-memory authoritative
   repositories, API and Worker share durable state, and missing production configuration
   fails fast.
2. Build a lifecycle-aware production container using SQLAlchemy, Redis, MinIO, selected
   SandboxProvider, observability, credential provider, processors, and SDK session store.
3. Add an async Worker loop with bounded idle polling, graceful shutdown, tenant lookup,
   and retry-safe dequeue behavior.
4. Keep `build_memory_container` for focused tests and local unit workflows only.
5. Run composition/queue tests and commit as `feat: wire durable API and worker services`.

## Task 11: Complete OpenTelemetry and Langfuse export

**Files:**

- Modify: `src/harness/observability/provider.py`
- Modify: `src/harness/observability/redaction.py`
- Modify: `src/harness/application/input_artifacts.py`
- Modify: `src/harness/worker/orchestrator.py`
- Modify: `src/harness/runtime/claude_sdk.py`
- Create: `deploy/otel/collector.yaml`
- Modify: `.env.example`
- Modify: `tests/integration/test_trace_propagation.py`
- Modify: `tests/unit/observability/test_redaction.py`

**Steps:**

1. Add failing tests for spans around processing, sandbox, MCP, model, memory, and artifact
   stages and for absence of credentials, memory bodies, and file contents.
2. Add stable correlation attributes and explicit exception/status recording.
3. Configure an optional Collector to export OTLP/HTTP to a Langfuse endpoint with headers
   supplied only through environment variables.
4. Run observability tests and commit as `feat: trace production harness stages`.

## Task 12: Build deployable Docker artifacts

**Files:**

- Create: `deploy/docker/api.Dockerfile`
- Create: `deploy/docker/web.Dockerfile`
- Create: `deploy/docker/entrypoint-api.sh`
- Create: `deploy/docker/entrypoint-worker.sh`
- Create: `deploy/docker-compose/.env.docker.example`
- Modify: `deploy/docker-compose/compose.yaml`
- Modify: `web/harness-console/next.config.ts`
- Modify: `.dockerignore`
- Modify: `Makefile`
- Create: `scripts/e2e_docker.py`

**Steps:**

1. Add static deployment tests that assert non-root users, health checks, required service
   dependencies, production settings, volumes, and Daytona/OTel profiles.
2. Create multi-stage API/Worker and Next.js standalone images.
3. Expand Compose with `migrate`, `api`, `worker`, `web`, infrastructure health checks,
   MinIO initialization, optional OTel Collector, and Daytona production settings.
4. Build with `docker compose build` and start the default local profile.
5. Run migrations, API/Web health probes, and `scripts/e2e_docker.py` through upload,
   memory, processing, artifact, and restart persistence paths.
6. Stop the stack without deleting persisted volumes and commit as
   `feat: package deployable harness stack`.

## Task 13: Final documentation and completion audit

**Files:**

- Modify: `README.md`
- Modify: `docs/local-development.md`
- Modify: `docs/domain-agents.md`
- Create: `docs/deployment.md`
- Modify: `.gitignore`

**Steps:**

1. Document local, Docker, Daytona, new-api, MCP credential, memory, input processor,
   artifact, and Langfuse configuration with no real secrets.
2. Ignore `.DS_Store` and verify no unrelated files enter commits.
3. Run fresh completion verification:

   ```bash
   uv run ruff check src tests
   uv run pyright
   uv run pytest
   cd web/harness-console && npm test && npm run build
   docker compose -f deploy/docker-compose/compose.yaml config
   docker compose -f deploy/docker-compose/compose.yaml build
   docker compose -f deploy/docker-compose/compose.yaml up -d --wait
   uv run python scripts/e2e_docker.py
   ```

4. Re-run the real browser upload flow and verify the unique fixture marker reaches the
   SDK run.
5. Run optional real Daytona/new-api/Langfuse smoke tests only when credentials are
   present; otherwise report them as explicitly skipped, not passed.
6. Audit every objective requirement against current files and runtime evidence.
7. Commit documentation as `docs: explain production harness deployment`.

