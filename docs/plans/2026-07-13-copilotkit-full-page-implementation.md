# CopilotKit Full-Page Console Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the raw-event validation console with a full-page CopilotKit chat that talks to the Harness through a standard AG-UI endpoint and supports approval, artifacts, replay, and local interaction testing.

**Architecture:** The Harness exposes `POST /v1/agui` as the AG-UI agent endpoint, converts `RunAgentInput` into durable Harness Sessions/Runs, and streams projected repository events until terminal completion. Next.js hosts `CopilotRuntime` as a BFF, injects tenant/user identity, and renders CopilotKit v2 `CopilotChat`; Harness-specific approval and artifact data are rendered as domain cards while raw events remain in a closed developer drawer.

**Tech Stack:** Python 3.12, FastAPI, `ag-ui-protocol`, pytest/httpx, Next.js 16, React 19, CopilotKit 1.62, `@ag-ui/client`, TypeScript, Vitest.

---

### Task 1: Standard AG-UI run request contract

**Files:**
- Create: `src/harness/agui/service.py`
- Modify: `src/harness/agui/routes.py`
- Modify: `src/harness/api/dependencies.py`
- Test: `tests/integration/agui/test_agui_run.py`

**Step 1: Write the failing request test**

Add an integration test that publishes `echo-agent`, posts an official `RunAgentInput` shape to `/v1/agui?agent_name=echo-agent&agent_version=0.1.0`, and asserts an SSE response containing `RUN_STARTED`, assistant text, and `RUN_FINISHED`. Add a second assertion that the same `threadId` reuses one Harness Session.

**Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/integration/agui/test_agui_run.py -q`

Expected: FAIL because `POST /v1/agui` does not exist.

**Step 3: Implement the minimal request adapter**

Use `ag_ui.core.RunAgentInput` for request validation. Add `AguiRunService` with an in-memory `(tenant_id, user_id, thread_id) -> session_id` mapping guarded by `asyncio.Lock`; extract the latest user text, create/reuse a Session, and create a Run using the inbound `run_id` as the idempotency key. Store the service in `ApiContainer` so requests share mappings.

**Step 4: Implement live durable SSE**

Start `container.worker.execute()` in an `asyncio.Task` when local auto-execution is enabled. Poll `container.events.list_after(...)`, project each event through `map_harness_event`, preserve durable sequence IDs, and stop only when the Run is terminal and all persisted events have been emitted. Cancel only the polling generator on disconnect; do not cancel the Worker task.

**Step 5: Run focused and regression tests**

Run: `uv run pytest tests/integration/agui/test_agui_run.py tests/integration/agui/test_agui_stream.py -q`

Expected: PASS.

**Step 6: Commit**

```bash
git add src/harness/agui/service.py src/harness/agui/routes.py src/harness/api/dependencies.py tests/integration/agui/test_agui_run.py
git commit -m "feat: add standard ag-ui run endpoint"
```

### Task 2: Domain event projection for chat renderers

**Files:**
- Modify: `src/harness/agui/mapper.py`
- Modify: `tests/unit/agui/test_mapper.py`

**Step 1: Write failing mapper tests**

Assert that `approval.requested` becomes a synthetic `harness_request_approval` tool call with JSON arguments containing `approval_id`, `run_id`, `reason`, and `tool_call_id`. Assert that `artifact.ready` becomes a synthetic `harness_present_artifact` tool call with downloadable artifact metadata. Preserve `harness.subagent.v1` as a custom activity event.

**Step 2: Run focused test and verify RED**

Run: `uv run pytest tests/unit/agui/test_mapper.py -q`

Expected: FAIL because approval/artifact currently map only to `CUSTOM`.

**Step 3: Add one reusable synthetic-tool projector**

Create a helper that emits `TOOL_CALL_START`, `TOOL_CALL_ARGS`, and `TOOL_CALL_END` with deterministic IDs derived from durable event data. Use it for approval and artifact events so CopilotKit can attach registered renderers without a parallel message system.

**Step 4: Run tests and commit**

Run: `uv run pytest tests/unit/agui/test_mapper.py tests/integration/agui -q`

Expected: PASS.

```bash
git add src/harness/agui/mapper.py tests/unit/agui/test_mapper.py
git commit -m "feat: project harness domain cards over ag-ui"
```

### Task 3: CopilotRuntime BFF and identity boundary

**Files:**
- Modify: `web/harness-console/package.json`
- Modify: `web/harness-console/package-lock.json`
- Create: `web/harness-console/src/lib/server-config.ts`
- Create: `web/harness-console/src/app/api/copilotkit/route.ts`
- Test: `web/harness-console/tests/server-config.spec.ts`

**Step 1: Write failing server configuration tests**

Test that local defaults resolve the Harness URL, agent name/version, tenant, and user, and that the generated AG-UI URL contains only the agent query parameters while identity stays in server-side headers.

**Step 2: Run the focused Web test and verify RED**

Run: `cd web/harness-console && npm test -- tests/server-config.spec.ts`

Expected: FAIL because the server config module does not exist.

**Step 3: Install and implement the runtime route**

Add the matching `@copilotkit/runtime` version. Create a Next App Router POST handler with `CopilotRuntime`, `copilotRuntimeNextJSAppRouterEndpoint`, and an `HttpAgent` targeting Harness `POST /v1/agui`. Configure headers on the server only: `X-Tenant-ID` and `X-User-ID`.

**Step 4: Verify tests and type/build surface**

Run: `cd web/harness-console && npm test -- tests/server-config.spec.ts && npm run build`

Expected: PASS.

**Step 5: Commit**

```bash
git add web/harness-console/package.json web/harness-console/package-lock.json web/harness-console/src/lib/server-config.ts web/harness-console/src/app/api/copilotkit/route.ts web/harness-console/tests/server-config.spec.ts
git commit -m "feat: proxy harness agent through copilot runtime"
```

### Task 4: Full-page CopilotChat shell and persistent thread

**Files:**
- Modify: `web/harness-console/src/app/layout.tsx`
- Modify: `web/harness-console/src/app/page.tsx`
- Modify: `web/harness-console/src/app/styles.css`
- Modify: `web/harness-console/src/components/copilotkit-shell.tsx`
- Create: `web/harness-console/src/lib/thread-store.ts`
- Test: `web/harness-console/tests/thread-store.spec.ts`

**Step 1: Write failing thread-store tests**

Test stable local-storage key semantics: reuse an existing thread ID after refresh and create a new UUID only when the user chooses “新对话”. Keep storage access behind a small injected interface so Vitest does not require a browser DOM.

**Step 2: Run focused test and verify RED**

Run: `cd web/harness-console && npm test -- tests/thread-store.spec.ts`

Expected: FAIL because the thread store does not exist.

**Step 3: Replace the validation dashboard with CopilotChat**

Import CopilotKit v2 styles in the root layout. Wrap the page with `CopilotKit runtimeUrl="/api/copilotkit" agent="harness-agent"`. Render the v2 `CopilotChat` as the only main surface, with a compact header containing agent/version, connection state, “新对话”, and developer toggle. Pass the stable thread ID and Chinese labels/placeholders to the chat.

**Step 4: Add full-page responsive styling**

Make the app occupy `100dvh`, keep the composer visible, let only the message area scroll, and ensure the header/cards work at desktop and narrow widths. Remove the default raw JSON two-column layout.

**Step 5: Test, build, and commit**

Run: `cd web/harness-console && npm test && npm run build`

Expected: PASS.

```bash
git add web/harness-console/src/app web/harness-console/src/components/copilotkit-shell.tsx web/harness-console/src/lib/thread-store.ts web/harness-console/tests/thread-store.spec.ts
git commit -m "feat: add full-page copilotkit chat"
```

### Task 5: Approval and artifact domain cards

**Files:**
- Modify: `web/harness-console/src/components/approval-card.tsx`
- Modify: `web/harness-console/src/components/artifact-list.tsx`
- Create: `web/harness-console/src/components/harness-tool-renderers.tsx`
- Create: `web/harness-console/src/app/api/harness/approvals/[approvalId]/route.ts`
- Create: `web/harness-console/src/app/api/harness/artifacts/[artifactId]/route.ts`
- Create: `web/harness-console/src/lib/harness-server.ts`
- Modify: `web/harness-console/tests/approval.spec.ts`
- Create: `web/harness-console/tests/harness-server.spec.ts`

**Step 1: Write failing decision and download proxy tests**

Test request construction for approval decisions and artifact downloads, including server-only identity headers, JSON decision body, binary response headers, and no raw object-store URL exposure.

**Step 2: Run focused tests and verify RED**

Run: `cd web/harness-console && npm test -- tests/approval.spec.ts tests/harness-server.spec.ts`

Expected: FAIL for the missing proxy helper/routes.

**Step 3: Register CopilotKit tool renderers**

Use the installed v2 renderer hook/types discovered from package declarations. Register `harness_request_approval` with approve/reject pending states and a read-only decided state; call the approval BFF route and let the still-open Harness stream resume automatically. Register `harness_present_artifact` with metadata and an authenticated download link to the artifact BFF route.

**Step 4: Implement BFF routes**

Forward approval and artifact calls to Harness while injecting identity. Preserve upstream status codes and safe user-readable messages. Stream binary artifact bodies and copy only `Content-Type`, `Content-Length`, and `Content-Disposition`.

**Step 5: Test/build and commit**

Run: `cd web/harness-console && npm test && npm run build`

Expected: PASS.

```bash
git add web/harness-console/src/components web/harness-console/src/app/api/harness web/harness-console/src/lib/harness-server.ts web/harness-console/tests
git commit -m "feat: render approvals and artifacts in chat"
```

### Task 6: Developer drawer and local bootstrap

**Files:**
- Create: `web/harness-console/src/components/developer-drawer.tsx`
- Modify: `web/harness-console/src/app/page.tsx`
- Create: `scripts/bootstrap_local_agent.py`
- Modify: `scripts/dev_up.sh`
- Modify: `scripts/dev_down.sh`
- Modify: `.env.example`
- Test: `tests/e2e/test_local_stack.py`

**Step 1: Write failing local bootstrap test**

Extend local-stack coverage to assert the default `echo-agent@0.1.0` is published before the console is reported ready and that the standard AG-UI POST route can complete a prompt without a separate browser-side publish call.

**Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/e2e/test_local_stack.py -q`

Expected: FAIL because local startup does not bootstrap the agent.

**Step 3: Add deterministic bootstrap and developer drawer**

After API readiness, publish the fixture manifest idempotently from `bootstrap_local_agent.py`, then start/validate Web readiness. Add an initially closed drawer showing configured endpoint, thread ID, last run/status, and raw projected events only when developer mode is enabled. Do not restore the old event viewer as the main interface.

**Step 4: Verify local test and commit**

Run: `uv run pytest tests/e2e/test_local_stack.py -q`

Expected: PASS when local services are running; otherwise explicitly skipped by its existing marker/guard.

```bash
git add scripts web/harness-console/src/components/developer-drawer.tsx web/harness-console/src/app/page.tsx .env.example tests/e2e/test_local_stack.py
git commit -m "feat: bootstrap local copilot console"
```

### Task 7: Full verification and browser acceptance

**Files:**
- Modify if necessary: `README.md`
- Modify if necessary: `docs/runbooks/local-development.md`

**Step 1: Run all automated verification**

Run: `make verify && make web-test && make web-build`

Expected: Ruff, Pyright, all Python tests, all Vitest tests, and Next production build pass.

**Step 2: Restart the complete local stack**

Run: `make dev-down && make dev-up`

Expected: API at `http://127.0.0.1:8000/docs`, full-page Chat at `http://127.0.0.1:3000`, and startup output confirms Langfuse/OTLP disabled.

**Step 3: Browser acceptance test**

Open `http://127.0.0.1:3000` and verify:

1. The default view is conversation UI, not raw Events.
2. Sending `请简要说明这个 Harness` streams an assistant answer and reaches success.
3. Sending the Fake Runtime approval/artifact trigger displays an approval card; approving resumes the Run and displays a downloadable artifact.
4. Refresh preserves the thread and conversation.
5. Developer details appear only after opening the developer drawer.
6. Browser console and local API/Web logs contain no uncaught errors.

**Step 4: Update operator documentation**

Document `make dev-up`, the two URLs, local identity/default agent environment variables, Fake Runtime validation prompts, and the fact that Langfuse remains optional and disabled locally.

**Step 5: Re-run verification after documentation/config edits**

Run: `make verify && make web-test && make web-build`

Expected: PASS.

**Step 6: Commit final validation changes**

```bash
git add README.md docs/runbooks/local-development.md
git commit -m "docs: explain copilot console validation"
```
