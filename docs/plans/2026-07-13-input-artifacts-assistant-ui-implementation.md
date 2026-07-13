# Input Artifacts and assistant-ui Implementation Plan

> Execute in small test-first slices. Each implementation step starts with a failing focused test, then the minimum code, then its focused verification.

**Goal:** Complete browser file upload through Claude SDK workspace reading, then migrate the full-page chat surface from CopilotKit to assistant-ui while preserving Harness-specific activity.

**Architecture:** A first-class `InputArtifact` service owns pre-run uploads. AG-UI messages reference server-issued IDs. The worker stages authorized bytes into `workspace/inputs` and gives those paths to the SDK runtime. assistant-ui talks to Harness only through same-origin Next.js proxies.

**Stack:** Python 3.12, FastAPI, Pydantic, pytest, Claude Agent SDK, Next.js 16, React 19, assistant-ui, AG-UI, Vitest.

---

## Task 1: InputArtifact domain and service

**Files:**

- Modify: `src/harness/core/models.py`
- Modify: `src/harness/core/ports.py`
- Modify: `src/harness/infrastructure/memory.py`
- Create: `src/harness/application/input_artifacts.py`
- Create: `tests/unit/test_input_artifacts.py`

Steps:

1. Add failing tests for upload metadata, ownership checks, size limits, total/count validation, and download.
2. Add `InputArtifact`, status, repository port, in-memory repository, and service.
3. Reuse `ArtifactStore` with opaque input-artifact IDs.
4. Run the focused unit tests.

## Task 2: Upload API and composition root

**Files:**

- Create: `src/harness/api/routes/input_artifacts.py`
- Modify: `src/harness/api/app.py`
- Modify: `src/harness/composition.py`
- Create: `tests/integration/test_input_artifact_api.py`

Steps:

1. Add failing multipart upload, size rejection, and identity-isolation tests.
2. Add `POST /v1/input-artifacts` and optional metadata/download endpoints needed by the UI.
3. Wire one service instance into API, AG-UI, and worker composition.
4. Run the focused integration tests.

## Task 3: AG-UI input reference extraction

**Files:**

- Modify: `src/harness/agui/service.py`
- Modify: `tests/integration/agui/test_agui_run.py`

Steps:

1. Add failing tests for document/binary attachment IDs, deduplication, limits, and forged URL/data rejection.
2. Extract trusted opaque IDs while retaining the latest text prompt.
3. Validate ownership before creating the run and store IDs in `Run.input`.
4. Run AG-UI integration tests.

## Task 4: Workspace staging and runtime inventory

**Files:**

- Modify: `src/harness/application/runtime.py`
- Modify: `src/harness/application/workspaces.py`
- Modify: `src/harness/worker/orchestrator.py`
- Modify: `src/harness/runtimes/claude_sdk.py`
- Create or modify: `tests/integration/test_input_staging.py`
- Modify: `tests/unit/test_claude_sdk_runtime.py`

Steps:

1. Add failing tests proving safe filenames, ownership enforcement, read-only bytes, metadata events, and runtime paths.
2. Stage inputs during provisioning and add `RuntimeContext.input_files`.
3. Append the file inventory to the Claude SDK prompt only when nonempty.
4. Run worker/runtime focused tests.

## Task 5: Same-origin Web proxies

**Files:**

- Create: `web/harness-console/src/app/api/agui/route.ts`
- Create: `web/harness-console/src/app/api/input-artifacts/route.ts`
- Add tests beside the routes.

Steps:

1. Add failing tests for identity injection, multipart forwarding, streaming preservation, and upstream error propagation.
2. Implement narrow server-only proxies.
3. Confirm internal identity values never enter client bundles or returned error bodies.

## Task 6: assistant-ui runtime and attachment composer

**Files:**

- Modify: `web/harness-console/package.json`
- Replace: `web/harness-console/src/app/providers.tsx` or current CopilotKit shell
- Modify: `web/harness-console/src/app/page.tsx`
- Create: `web/harness-console/src/components/agent-thread.tsx`
- Create: `web/harness-console/src/lib/input-attachment-adapter.ts`
- Add component and adapter tests.

Steps:

1. Install pinned compatible assistant-ui packages and inspect their shipped types.
2. Add failing tests for upload progress, remove/retry, submit blocking while uploading, and AG-UI content IDs.
3. Configure the assistant-ui AG-UI runtime against `/api/agui`.
4. Implement the full-page thread/composer using assistant-ui primitives.
5. Remove CopilotKit only after parity tests pass.

## Task 7: Harness-specific message and activity rendering

**Files:**

- Reuse/modify current activity, Markdown, JSON, code, approval, and artifact components.
- Modify related Vitest suites.

Steps:

1. Preserve reasoning, tool, sub-agent, approval, output-artifact, and run-status views.
2. Adapt custom AG-UI events to the assistant-ui external runtime/message parts.
3. Keep copy buttons for textual payloads and download buttons only for actual files.
4. Verify typography and responsive full-page layout.

## Task 8: End-to-end verification

Steps:

1. Run the entire Python suite.
2. Run web tests, lint/type checks, and production build.
3. Start API and production-mode web services.
4. Upload a fixture from the browser path and ask the real cc-switch-backed SDK to quote a unique fact from it.
5. Confirm events show metadata/tool activity but not raw uploaded bytes.
6. Verify refresh does not duplicate a run and explain that arbitrary local folder access still requires a trusted local bridge.

